import json

from eden.cli import main
from test_inspector import rap_project  # noqa: F401  (fixture)


def test_inspect_writes_reports(rap_project, tmp_path, capsys):  # noqa: F811
    md, js = tmp_path / "r.md", tmp_path / "r.json"
    assert main(["inspect", str(rap_project), "--markdown", str(md), "--json", str(js)]) == 0
    assert "Voix détectées" in md.read_text(encoding="utf-8")
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["project"]["tempo_bpm"] == 96
    assert "[6/6]" in capsys.readouterr().err


def test_inspect_error_exit_code(tmp_path, capsys):
    assert main(["inspect", str(tmp_path / "absent.flp")]) == 2
    assert "Lecture du fichier" in capsys.readouterr().err


def test_mix_requires_the_fl_set_up(rap_project, capsys):  # noqa: F811
    assert main(["mix", str(rap_project)]) == 2
    assert "fl-probe" in capsys.readouterr().err
