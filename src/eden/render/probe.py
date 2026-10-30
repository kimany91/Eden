"""Find out, on the user's machine, how FL Studio can be driven by Eden.

Each candidate command-line syntax is tried on a temporary copy of a real project (deleted at the
end, with its test render), until FL Studio produces a WAV: that syntax is saved in Eden's
settings. One render, once: whether FL respects what Eden changes in its copies (channels muted,
sends cut, effects bypassed) is checked on every song by the renders themselves, whose sum must
give back the song (``verify.null_test``) and whose dry voices must differ from the full ones.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from collections.abc import Callable

from eden.flp.edit import FlpEditor
from eden.project.inspector import inspect_project
from eden.render.fl_studio import CANDIDATE_ARGS, FLStudioRenderer, RenderError, find_fl_studio, fl_is_running
from eden.render.pipeline import plays_to_the_end, sample_repairs
from eden.render.verify import check_audio
from eden.safety import Workspace, read_project_bytes
from eden.settings import load_settings, save_settings

Log = Callable[[str], None]


@dataclass
class ProbeResult:
    fl_path: str | None
    working_args: list[str] | None = None
    audio_format: str | None = None
    lines: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.working_args)


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
            say("FL Studio introuvable. Indique le chemin de FL64.exe avec --fl.")
            return result
        command = [str(exe)]
        if fl_is_running():
            say("FL Studio est ouvert : ferme-le avant le test (il pourrait intercepter la commande).")
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

    def _find_syntax() -> None:
        def copy_with(name: str) -> Path:
            ed = FlpEditor(original)
            for ch, p in repairs.items():
                ed.set_sample_path(ch, p)
            folder = root / name
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{name}.flp"
            path.write_bytes(ed.to_bytes())
            return path

        for i, (label, args) in enumerate(candidates or CANDIDATE_ARGS, 1):
            renderer = FLStudioRenderer(command, args)
            copy = copy_with(f"essai-{i}")
            say(f"Essai {i} ({label}) : {' '.join(renderer.build_args(copy))}")
            outcome = renderer.run(copy, timeout_s)
            if outcome.dialog:
                say(f"  → FL Studio attendait une réponse : « {outcome.dialog} » (fermé par Eden)")
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
            if check.ends_with_sound and not plays_to_the_end(report, [s.channel for s in report.sources]):
                say("  Attention : le rendu s'arrête alors que le son continue. Règle l'export de "
                    "FL Studio pour laisser la fin des effets (« Leave remainder »), sinon les "
                    "échos et delays de fin seraient coupés.")
            result.working_args = args
            result.audio_format = f"{check.sample_rate} Hz {check.subtype}"
            if "FLOAT" not in check.subtype.upper():
                say("  Conseil : règle l'export WAV de FL Studio en 32 bits flottant pour éviter "
                    "tout écrêtage des pistes séparées.")
            break

        if result.working_args is None:
            say("Aucune syntaxe n'a fonctionné : le rendu automatique n'est pas possible tel quel.")
            return
        if exe is not None:
            settings.fl_path = str(exe)
        settings.render_args = result.working_args
        save_settings(settings, settings_file)
        say("Rendu automatique opérationnel : réglages enregistrés.")
    try:
        _find_syntax()
    finally:  # test copies and test renders are not kept
        shutil.rmtree(root, ignore_errors=True)
    return result
