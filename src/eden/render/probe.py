"""Find out, on the user's machine, how FL Studio can be driven by Eden.

Runs on temporary copies of a real project (deleted at the end, with their
test renders):
  1. each candidate command-line syntax → does FL Studio produce a WAV?
  2. with the syntax that works: are muted channels really silent?
  3. are muted mixer inserts really silent?
  4. are cut routes really cut?
  5. is a bypassed effect slot really bypassed? One source with a reverb or
     delay whose on/off state FL stored is rendered alone, with and without
     that slot: the two renders must differ by more than SLOT_BYPASS_MIN_DB.
     A slot can leave the render unchanged for a reason of its own (a plugin
     set to let the sound through, a return fader at the bottom), so when it
     does, other slots are tried, up to SLOT_CHECK_TRIES in all: the check
     fails only when no slot tried changes the render. Not checked when the
     project has no such slot (the dry voices rely on these bypasses).
The working syntax is saved in Eden's settings only if every check that could run passes.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from collections.abc import Callable

from eden.flp.edit import FlpEditor
from eden.project.inspector import SPACE_CATEGORIES, ExistingEffect, SourceAnalysis, inspect_project
from eden.project.model import MASTER_INSERT, FlpProject
from eden.render.fl_studio import (
    CANDIDATE_ARGS,
    FLStudioRenderer,
    RenderError,
    find_fl_studio,
    fl_is_running,
)
from eden.render.pipeline import sample_repairs
from eden.render.verify import check_audio, null_test
from eden.safety import Workspace, read_project_bytes
from eden.settings import load_settings, save_settings

Log = Callable[[str], None]
# A bypassed slot must change the render by more than this (the null test's threshold).
SLOT_BYPASS_MIN_DB = -60.0
# Slots tried before deciding that FL does not bypass a slot (choix d'Eden).
SLOT_CHECK_TRIES = 3


@dataclass
class ProbeResult:
    fl_path: str | None
    working_args: list[str] | None = None
    isolation_channels_ok: bool | None = None
    isolation_inserts_ok: bool | None = None
    isolation_routes_ok: bool | None = None
    isolation_slots_ok: bool | None = None  # None: no slot to check it with, or only silent renders
    audio_format: str | None = None
    lines: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.working_args and self.isolation_channels_ok and self.isolation_inserts_ok
                    and self.isolation_routes_ok and self.isolation_slots_ok is not False)


def _space_slots(project: FlpProject, sources: list[SourceAnalysis]) -> list[tuple[SourceAnalysis, ExistingEffect]]:
    """Up to SLOT_CHECK_TRIES pairs of a source played in the playlist and one of its active
    reverbs or delays whose on/off state FL stored (the record a dry-voice render rewrites), in
    the order to try them. Each next pair is, in project order, the first one on an insert not
    picked yet, else on a slot not picked yet, and among those the first with a source not
    picked yet; a slot already picked comes back, with another source, only when no other slot
    is left."""
    pairs = []
    for s in sources:
        if not s.clip_count:
            continue
        for e in s.existing_effects:
            ins = project.insert(e.insert)
            slot = next((sl for sl in ins.slots if sl.index == e.slot), None) if ins else None
            if e.active and e.category in SPACE_CATEGORIES and slot is not None and slot.enabled is not None:
                pairs.append((s, e))
    picked: list[tuple[SourceAnalysis, ExistingEffect]] = []
    while pairs and len(picked) < SLOT_CHECK_TRIES:
        best = max(range(len(pairs)), key=lambda i: (
            all(pairs[i][1].insert != e.insert for _, e in picked),
            all((pairs[i][1].insert, pairs[i][1].slot) != (e.insert, e.slot) for _, e in picked),
            all(pairs[i][0].channel != s.channel for s, _ in picked)))
        picked.append(pairs.pop(best))
    return picked


def probe_fl_studio(
    project: str | Path,
    fl_path: str | None = None,
    command: list[str] | None = None,
    candidates: list[tuple[str, list[str]]] | None = None,
    timeout_s: float = 600.0,
    workspace_home: Path | None = None,
    settings_file: Path | None = None,
    log: Log = print,
) -> ProbeResult:
    project = Path(project)
    settings = load_settings(settings_file)

    def say(msg: str) -> None:
        result.lines.append(msg)
        log(msg)

    exe: Path | None = None
    if command is None:
        exe = find_fl_studio(fl_path or settings.fl_path)
        result = ProbeResult(fl_path=str(exe) if exe else None)
        if exe is None:
            say("FL Studio introuvable. Indiquez le chemin de FL64.exe avec --fl.")
            return result
        command = [str(exe)]
        if fl_is_running():
            say("FL Studio est ouvert : fermez-le avant le test (il pourrait intercepter la commande).")
            return result
    else:
        result = ProbeResult(fl_path=" ".join(command))
    say(f"FL Studio : {result.fl_path}")

    report = inspect_project(project, workspace_home=workspace_home)
    try:
        repairs = sample_repairs(report)
    except RenderError as exc:
        say(str(exc))
        return result
    original, _ = read_project_bytes(project)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = Workspace(project, workspace_home).root / "probe" / stamp

    def _run_checks() -> None:
        def copy_with(edits: Callable[[FlpEditor], None], name: str) -> Path:
            ed = FlpEditor(original)
            for ch, p in repairs.items():
                ed.set_sample_path(ch, p)
            edits(ed)
            folder = root / name
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{name}.flp"
            path.write_bytes(ed.to_bytes())
            return path

        working: FLStudioRenderer | None = None
        for i, (label, args) in enumerate(candidates or CANDIDATE_ARGS, 1):
            renderer = FLStudioRenderer(command, args)
            copy = copy_with(lambda ed: None, f"essai-{i}")
            say(f"Essai {i} ({label}) : {' '.join(renderer.build_args(copy))}")
            outcome = renderer.run(copy, timeout_s)
            if outcome.timed_out:
                say(f"  → pas terminé après {timeout_s:.0f} s (fenêtre bloquante ?)")
            if not outcome.outputs:
                say(f"  → aucun fichier WAV produit (code de sortie {outcome.returncode})")
                continue
            check = check_audio(outcome.outputs[0])
            say(f"  → {outcome.outputs[0].name} : {check.duration_s:.1f} s, {check.sample_rate} Hz, "
                f"{check.subtype}, crête {check.peak_db:.1f} dBFS, en {outcome.seconds:.0f} s")
            if check.silent:
                say("  → fichier silencieux : rendu non valide")
                continue
            if check.ends_with_sound:
                say("  Attention : le rendu s'arrête alors que le son continue. Réglez l'export de "
                    "FL Studio pour laisser la fin des effets (« Leave remainder »), sinon les "
                    "échos et delays de fin seraient coupés.")
            working = renderer
            result.working_args = args
            result.audio_format = f"{check.sample_rate} Hz {check.subtype}"
            if "FLOAT" not in check.subtype.upper():
                say("  Conseil : réglez l'export WAV de FL Studio en 32 bits flottant pour éviter "
                    "tout écrêtage des pistes séparées.")
            break

        if working is None:
            say("Aucune syntaxe n'a fonctionné : le rendu automatique n'est pas possible tel quel.")
            return

        sources = [s for s in report.sources if s.reaches_master]

        def mute_channels(ed: FlpEditor) -> None:
            for s in sources:
                ed.set_channel_enabled(s.channel, False)

        def mute_inserts(ed: FlpEditor) -> None:
            for ins in report.project.inserts:
                if ins.index != MASTER_INSERT:
                    ed.set_insert_enabled(ins.index, False)
            for s in sources:
                if s.insert in (None, MASTER_INSERT):
                    ed.set_channel_enabled(s.channel, False)

        def cut_routes_to_master(ed: FlpEditor) -> None:
            for ins in report.project.inserts:
                if any(r.target == MASTER_INSERT for r in ins.routes):
                    ed.set_route(ins.index, MASTER_INSERT, False)
            for s in sources:
                if s.insert in (None, MASTER_INSERT):
                    ed.set_channel_enabled(s.channel, False)

        for attr, edits, label in (
            ("isolation_channels_ok", mute_channels, "canaux coupés"),
            ("isolation_inserts_ok", mute_inserts, "inserts du Mixer coupés"),
            ("isolation_routes_ok", cut_routes_to_master, "envois vers le Master coupés"),
        ):
            copy = copy_with(edits, f"isolation-{attr.split('_')[1]}")
            try:
                wav = working.render(copy, timeout_s)
            except RenderError as exc:
                say(f"Test d'isolation ({label}) : échec du rendu ({exc})")
                setattr(result, attr, False)
                continue
            check = check_audio(wav)
            ok = check.silent
            setattr(result, attr, ok)
            say(f"Test d'isolation ({label}) : " + ("silence obtenu ✔" if ok else
                f"le son reste présent (crête {check.peak_db:.1f} dBFS) ✘"))

        found = _space_slots(report.project, sources)
        if not found:
            say("Test d'isolation (slot d'effet contourné) : non vérifié sur ce projet (aucune piste de la "
                "playlist ne passe par une reverb ou un delay actif dont FL a enregistré l'état "
                "activé/désactivé)")

        def alone(s: SourceAnalysis, bypassed: ExistingEffect | None = None) -> Callable[[FlpEditor], None]:
            def edits(ed: FlpEditor) -> None:
                for other in sources:
                    if other.channel != s.channel:
                        ed.set_channel_enabled(other.channel, False)
                if bypassed is not None:
                    ed.set_slot_enabled(bypassed.insert, bypassed.slot, False)
            return edits

        alone_renders: dict[int, Path] = {}  # channel → its render alone, every effect on
        for n, (s, fx) in enumerate(found, 1):
            what = (f"slot d'effet contourné, essai {n} sur {len(found)} : « {fx.plugin} » sur "
                    f"« {fx.insert_label} », {s.label} seule")
            try:
                if s.channel not in alone_renders:
                    alone_renders[s.channel] = working.render(copy_with(alone(s), f"isolation-slot-{n}-actif"),
                                                              timeout_s)
                with_fx = alone_renders[s.channel]
                if check_audio(with_fx).silent:
                    say(f"Test d'isolation ({what}) : non vérifié (rendu silencieux)")
                    continue
                without = working.render(copy_with(alone(s, fx), f"isolation-slot-{n}-contourne"), timeout_s)
            except RenderError as exc:
                say(f"Test d'isolation ({what}) : échec du rendu ({exc}) ✘")
                result.isolation_slots_ok = False
                continue
            gap = null_test(with_fx, [without], SLOT_BYPASS_MIN_DB)  # the two must not null
            if not gap.passed:
                result.isolation_slots_ok = True
                say(f"Test d'isolation ({what}) : le rendu change (écart de {gap.residual_db:.1f} dB) ✔")
                break
            result.isolation_slots_ok = False
            say(f"Test d'isolation ({what}) : le rendu ne change pas (écart sous {SLOT_BYPASS_MIN_DB:.0f} dB) ✘")
        if len(found) > 1 and result.isolation_slots_ok is False:
            say(f"Test d'isolation (slot d'effet contourné) : aucun des {len(found)} essais ne montre que "
                "FL Studio contourne un slot désactivé ✘")

        if result.ok:
            if exe is not None:
                settings.fl_path = str(exe)
            settings.render_args = result.working_args
            save_settings(settings, settings_file)
            say("Rendu automatique opérationnel : réglages enregistrés.")
        else:
            say("Rendu possible, mais l'isolation des pistes n'est pas fiable : "
                "envoyez ce compte rendu pour analyse.")
    try:
        _run_checks()
    finally:  # test copies and test renders are not kept
        shutil.rmtree(root, ignore_errors=True)
    return result
