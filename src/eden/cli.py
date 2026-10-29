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
        report = inspect_project(args.project, keep_snapshot=not args.no_snapshot, on_step=progress)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eden", description="Eden — mixage automatique de voix rap")
    parser.add_argument("--version", action="version", version=f"Eden {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("inspect", help="Inspecter un projet FL Studio (lecture seule)")
    p.add_argument("project", help="Chemin du fichier .flp")
    p.add_argument("--markdown", help="Écrire le rapport lisible dans ce fichier")
    p.add_argument("--json", help="Écrire le rapport complet (JSON) dans ce fichier")
    p.add_argument("--no-snapshot", action="store_true",
                   help="Ne pas archiver de copie du projet dans l'espace de travail d'Eden")
    p.set_defaults(func=_cmd_inspect)

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
