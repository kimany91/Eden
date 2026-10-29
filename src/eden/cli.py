"""Command-line entry point: ``eden inspect``, ``eden gui``, ``eden update``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eden import __version__


def _cmd_inspect(args: argparse.Namespace) -> int:
    from eden.project.inspector import InspectionError, inspect_project
    from eden.report import render_markdown

    def progress(i: int, total: int, label: str) -> None:
        print(f"[{i + 1}/{total}] {label}…", file=sys.stderr)

    try:
        report = inspect_project(args.project, on_step=progress)
    except InspectionError as exc:
        print(f"Échec à l'étape « {exc.step} » : {exc.message}", file=sys.stderr)
        return 2
    md = render_markdown(report)
    if args.markdown:
        Path(args.markdown).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(report.to_json(), encoding="utf-8")
    if not args.markdown and not args.json:
        print(md)
    if report.report_path:
        print(f"Rapport archivé : {report.report_path}", file=sys.stderr)
    return 0


def _cmd_gui(_args: argparse.Namespace) -> int:
    from eden.gui.app import run

    return run()


def _cmd_update(args: argparse.Namespace) -> int:
    from eden.updater import UpdateConfig, check_and_download

    result = check_and_download(UpdateConfig(token=args.token), force=True)
    print(result.message)
    return 0 if result.status != "error" else 1


def _cmd_probe(args: argparse.Namespace) -> int:
    from eden.project.inspector import InspectionError
    from eden.render.probe import probe_fl_studio

    try:
        result = probe_fl_studio(args.project, fl_path=args.fl, timeout_s=args.timeout)
    except InspectionError as exc:
        print(f"Échec à l'étape « {exc.step} » : {exc.message}", file=sys.stderr)
        return 2
    return 0 if result.ok else 1


def _progress(i: int, total: int, label: str) -> None:
    print(f"[{i + 1}/{total}] {label}…", file=sys.stderr)


def _configured_renderer():
    from eden.render.fl_studio import FLStudioRenderer, find_fl_studio
    from eden.settings import load_settings

    settings = load_settings()
    exe = find_fl_studio(settings.fl_path)
    if exe is None or not settings.render_args:
        print("Rendu automatique pas encore configuré : lancez d'abord « eden fl-probe <projet.flp> ».",
              file=sys.stderr)
        return None, settings
    return FLStudioRenderer([str(exe)], settings.render_args), settings


def _render(args: argparse.Namespace, renderer, settings, report=None):
    from eden.render.pipeline import render_project

    result = render_project(args.project, renderer, timeout_s=settings.render_timeout_s,
                            threshold_db=settings.null_test_threshold_db,
                            allow_missing=args.allow_missing, report=report, on_step=_progress)
    for w in result.warnings:
        print(f"Avertissement : {w}")
    if result.null_test:
        print(result.null_test.message)
    return result


def _cmd_render(args: argparse.Namespace) -> int:
    from eden.project.inspector import InspectionError
    from eden.render.fl_studio import RenderError

    renderer, settings = _configured_renderer()
    if renderer is None:
        return 2
    try:
        result = _render(args, renderer, settings)
    except (InspectionError, RenderError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Pistes rendues dans : {result.folder}")
    return 0 if result.ok else 1


def _cmd_mix(args: argparse.Namespace) -> int:
    from eden.mix.export import ExportError, export_wav
    from eden.mix.session import MixError, mix_project
    from eden.project.inspector import InspectionError, inspect_project
    from eden.render.fl_studio import RenderError

    renderer, settings = _configured_renderer()
    if renderer is None:
        return 2
    project = Path(args.project)
    try:
        report = inspect_project(project, on_step=_progress)
        renders = _render(args, renderer, settings, report)
        version = mix_project(project, report, renders, renderer, args.intensite / 100,
                              timeout_s=settings.render_timeout_s, on_step=_progress)
    except (InspectionError, RenderError, MixError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for part in version.parts:
        print(f"{part.label} :")
        for t in part.treatments:
            print(f"  - {t.label} ({t.reason})")
        if not part.treatments:
            print("  - laissé tel quel")
    print(f"Origine : {version.original.loudness_lufs:.1f} LUFS, crête {version.original.true_peak_db:.1f} dBTP")
    print(f"Eden    : {version.final.loudness_lufs:.1f} LUFS, crête {version.final.true_peak_db:.1f} dBTP")
    for w in version.warnings:
        print(f"Avertissement : {w}")
    if args.export:
        try:
            result = export_wav(Path(version.final_wav), Path(args.export), args.frequence, args.bits)
        except ExportError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"WAV exporté : {result.path}")
    else:
        print(f"Mix final : {version.final_wav}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eden", description="Eden — mixage automatique de voix rap")
    parser.add_argument("--version", action="version", version=f"Eden {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("inspect", help="Inspecter un projet FL Studio (lecture seule)")
    p.add_argument("project", help="Chemin du fichier .flp")
    p.add_argument("--markdown", help="Écrire le rapport lisible dans ce fichier")
    p.add_argument("--json", help="Écrire le rapport complet (JSON) dans ce fichier")
    p.set_defaults(func=_cmd_inspect)

    pr = sub.add_parser("fl-probe", help="Tester le pilotage de FL Studio sur ce PC")
    pr.add_argument("project", help="Un projet .flp réel (il n'est pas modifié)")
    pr.add_argument("--fl", help="Chemin de FL64.exe si non détecté")
    pr.add_argument("--timeout", type=float, default=600.0, help="Délai maximum par rendu (s)")
    pr.set_defaults(func=_cmd_probe)

    r = sub.add_parser("render", help="Faire rendre par FL Studio toutes les pistes nécessaires au mixage")
    r.add_argument("project", help="Chemin du fichier .flp")
    r.add_argument("--allow-missing", action="store_true",
                   help="Continuer même si des fichiers audio sont introuvables")
    r.set_defaults(func=_cmd_render)

    m = sub.add_parser("mix", help="Mixer automatiquement puis passer dans le Master FL Studio")
    m.add_argument("project", help="Chemin du fichier .flp")
    m.add_argument("--intensite", type=float, default=100.0, help="Intensité des corrections, 0 à 100")
    m.add_argument("--export", help="Fichier WAV à écrire (sans écraser un fichier existant)")
    m.add_argument("--frequence", type=int, choices=[44100, 48000, 88200, 96000],
                   help="Fréquence d'échantillonnage du WAV (par défaut : celle de FL Studio)")
    m.add_argument("--bits", type=int, choices=[16, 24, 32], default=24, help="Profondeur de bits")
    m.add_argument("--allow-missing", action="store_true",
                   help="Continuer même si des fichiers audio sont introuvables")
    m.set_defaults(func=_cmd_mix)

    g = sub.add_parser("gui", help="Ouvrir l'interface graphique")
    g.set_defaults(func=_cmd_gui)

    u = sub.add_parser("update", help="Rechercher une mise à jour maintenant")
    u.add_argument("--token", help="Jeton GitHub (uniquement si le dépôt est privé)")
    u.set_defaults(func=_cmd_update)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return _cmd_gui(args)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
