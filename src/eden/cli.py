"""Command-line entry point: ``eden inspect``, ``eden fl-probe``, ``eden render``, ``eden mix``,
``eden gui``, ``eden update``."""

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
    from eden.render.fl_studio import configured_renderer
    from eden.settings import load_settings

    renderer = configured_renderer()
    if renderer is None:
        print("Rendu automatique pas encore configuré : lance d'abord « eden fl-probe <projet.flp> ».",
              file=sys.stderr)
    return renderer, load_settings()


def _render(args: argparse.Namespace, renderer, settings, report=None):
    from eden.render.pipeline import render_project

    result = render_project(args.project, renderer, timeout_s=settings.render_timeout_s,
                            threshold_db=settings.null_test_threshold_db,
                            allow_missing=args.allow_missing, report=report, on_step=_progress)
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
    for w in result.warnings:  # ``eden mix`` prints them with the mix's own, or before its error
        print(f"Avertissement : {w}")
    print(f"Pistes rendues dans : {result.folder}")
    return 0 if result.ok else 1


def _print_treatments(treatments) -> None:
    from eden.gui.viewmodel import reduction_text

    for t in treatments:
        print(f"  - {t.label} ({t.reason})")
        measured = reduction_text(t.kind, t.measured)
        if measured:
            print(f"    {measured}")


def _print_version(version) -> None:
    """What ``eden mix`` reports: every decision with its reason and, for the compressors and
    de-essers, the reduction they really applied; then the master's checks."""
    song = version.song
    print(f"Morceau : {song.key or 'tonalité inconnue'}"
          + (f" (confiance {song.key_confidence})" if song.key_confidence else "")
          + (f", {song.tempo_bpm:g} BPM" if song.tempo_bpm else "")
          + (f", 808 sur {song.bass_root}" if song.bass_root else ""))
    for part in version.parts:
        print(f"{part.label} :")
        _print_treatments(part.treatments)
        for line in part.space:
            print(f"  - {line}")
        if part.placement:
            print(f"  - {part.placement}")
        if not part.treatments and not part.space:
            print("  - laissé tel quel")
    print("Mastering Eden :")
    _print_treatments(version.master)
    c = version.checks
    print(f"Export FL : {version.original.loudness_lufs:.1f} LUFS, crête {version.original.true_peak_db:.1f} dBTP")
    print(f"Eden      : {c.integrated_lufs:.1f} LUFS, crête {c.true_peak_dbtp:.1f} dBTP, "
          f"plage {c.loudness_range_lu:.1f} LU, crête/volume {c.plr_db:.1f} dB")
    for p in c.platforms:
        print(f"  {p.name} : {p.gain_db:+.1f} dB à la lecture → {p.heard_lufs:.1f} LUFS")
    for w in version.warnings:
        print(f"Avertissement : {w}")


def _cmd_mix(args: argparse.Namespace) -> int:
    from eden.mix.export import ExportError, check_format, export_wav
    from eden.mix.session import MixError, mix_project
    from eden.project.inspector import InspectionError, inspect_project
    from eden.render.fl_studio import RenderError

    try:  # before FL renders and Eden mixes for minutes
        check_format(args.frequence, args.bits)
    except ExportError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    renderer, settings = _configured_renderer()
    if renderer is None:
        return 2
    project = Path(args.project)
    try:
        report = inspect_project(project, on_step=_progress)
        renders = _render(args, renderer, settings, report)
    except (InspectionError, RenderError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    from dataclasses import replace

    from eden.settings import master_settings
    chosen = master_settings(settings)
    if args.master:
        chosen = replace(chosen, mode=args.master)
    try:
        version = mix_project(project, report, renders, args.intensite / 100, on_step=_progress,
                              master_settings=chosen)
    except MixError as exc:
        for w in renders.warnings:  # a mix carries them in its own warnings; without one, said here
            print(f"Avertissement : {w}")
        print(str(exc), file=sys.stderr)
        return 2
    _print_version(version)
    if args.export:
        try:
            result = export_wav(Path(version.final_wav), Path(args.export), args.frequence, args.bits)
        except ExportError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"WAV exporté : {result.path} (crête {result.true_peak_dbtp:.1f} dBTP)")
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

    m = sub.add_parser("mix", help="Mixer les voix puis masteriser avec Eden "
                                   "(les effets du Master FL Studio ne sont pas utilisés)")
    m.add_argument("project", help="Chemin du fichier .flp")
    m.add_argument("--intensite", type=float, default=100.0, help="Intensité des corrections, 0 à 100")
    m.add_argument("--master", choices=["aucun", "simple", "complet"],
                   help="Mastering : aucun, simple (crêtes et niveau, sans saturation — par défaut) ou "
                        "complet (la chaîne entière, réglée dans la fenêtre Mastering de l'interface)")
    m.add_argument("--export", help="Fichier WAV à écrire (sans écraser un fichier existant)")
    # the rates and depths are checked against the export's own lists, in _cmd_mix: importing the
    # export module here would load scipy for every eden command
    m.add_argument("--frequence", type=int,
                   help="Fréquence d'échantillonnage du WAV, en Hz (par défaut : celle de FL Studio)")
    m.add_argument("--bits", type=int, default=24, help="Profondeur de bits (par défaut : 24)")
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
