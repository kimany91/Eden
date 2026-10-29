from eden.gui import viewmodel
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render.pipeline import render_project
from eden.render.plan import plan_renders
from test_render import make_session, sim_renderer


def test_report_view(tmp_path):
    report = inspect_project(make_session(tmp_path), roots=SearchRoots())
    v = viewmodel.report_view(report)
    assert v["name"] == "Session" and v["tempo"] == "120 BPM"
    lead = v["voices"][0]
    assert lead["label"] == "Lead" and lead["roleKey"] == "lead_vocal"
    assert lead["fileInfo"].startswith("22.05 kHz · mono")
    assert {e["name"] for e in lead["effects"]} == {"Fruity parametric EQ 2", "Fruity Reeverb 2"}
    assert [m["name"] for m in v["masterEffects"]] == ["Fruity Limiter"]


def test_render_rows_follow_pipeline_steps(tmp_path):
    project = make_session(tmp_path)
    report = inspect_project(project, roots=SearchRoots())
    rows = viewmodel.render_rows(plan_renders(report))
    assert [r["name"] for r in rows][-3:] == ["verification", "controle-master", "controle-eden-0"]
    marked = viewmodel.mark_step(rows, 2)
    assert [r["status"] for r in marked[:4]] == ["done", "done", "running", "pending"]

    result = render_project(project, sim_renderer(), timeout_s=120, report=report)
    final, summary = viewmodel.render_view(rows, result)
    assert {r["status"] for r in final} == {"done"}
    assert summary["ok"] and summary["stemCount"] == 3 and summary["vocalCount"] == 2
    assert "Master FL est conservé" in summary["masterMessage"]


def test_mix_view_and_versions(tmp_path):
    import json

    from eden.mix.session import list_versions, mix_project

    project = make_session(tmp_path)
    report = inspect_project(project, roots=SearchRoots())
    renders = render_project(project, sim_renderer(), timeout_s=120, report=report)
    version = mix_project(project, report, renders, sim_renderer(), intensity=1.0, timeout_s=120)
    view = viewmodel.mix_view(json.loads(version.to_json()))
    assert view["intensity"] == 100 and view["finalWav"] == version.final_wav
    assert view["original"]["lufs"].endswith("LUFS") and view["final"]["truePeak"].endswith("dBTP")
    lead = next(p for p in view["parts"] if p["label"] == "Lead")
    assert lead["role"] == "Voix principale" and all(t["reason"] for t in lead["treatments"])
    assert view["parts"][-1]["role"] == "Instru et reste du morceau"
    versions = viewmodel.versions_view(list_versions(project))
    assert versions[0]["id"] == version.id and versions[0]["intensity"] == 100
