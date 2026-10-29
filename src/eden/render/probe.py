"""Find out, on the user's machine, how FL Studio can be driven by Eden.

Runs on temporary copies of a real project (deleted at the end, with their
test renders):
  1. each candidate command-line syntax → does FL Studio produce a WAV?
  2. with the syntax that works: are muted channels really silent?
  3. are muted mixer inserts really silent?
  4. are cut routes really cut?
The working syntax is saved in Eden's settings only if all checks pass.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from collections.abc import Callable

from eden.flp.edit import FlpEditor
from eden.project.inspector import inspect_project
from eden.project.model import MASTER_INSERT
from eden.render.fl_studio import (
    CANDIDATE_ARGS,
    FLStudioRenderer,
    RenderError,
    find_fl_studio,
    fl_is_running,
)
from eden.render.pipeline import sample_repairs
from eden.render.verify import check_audio
from eden.safety import Workspace, read_project_bytes
from eden.settings import load_settings, save_settings

Log = Callable[[str], None]


@dataclass
class ProbeResult:
    fl_path: str | None
    working_args: list[str] | None = None
    isolation_channels_ok: bool | None = None
    isolation_inserts_ok: bool | None = None
    isolation_routes_ok: bool | None = None
    audio_format: str | None = None
    lines: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.working_args and self.isolation_channels_ok
                    and self.isolation_inserts_ok and self.isolation_routes_ok)


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
