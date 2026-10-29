from eden.gui import viewmodel
from eden.mix.export import ExportResult
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
    assert [r["name"] for r in rows][-1] == "verification"
    marked = viewmodel.mark_step(rows, 2)
    assert [r["status"] for r in marked[:4]] == ["done", "done", "running", "pending"]

    result = render_project(project, sim_renderer(), timeout_s=120, report=report)
    final, summary = viewmodel.render_view(rows, result)
    assert {r["status"] for r in final} == {"done"}
    assert summary["ok"] and summary["stemCount"] == 3 and summary["vocalCount"] == 2


def test_mix_view_and_versions(tmp_path):
    import json

    from eden.mix.session import list_versions, mix_project

    project = make_session(tmp_path)
    report = inspect_project(project, roots=SearchRoots())
    renders = render_project(project, sim_renderer(), timeout_s=120, report=report)
    version = mix_project(project, report, renders, intensity=1.0)
    view = viewmodel.mix_view(json.loads(version.to_json()))
    assert view["intensity"] == 100 and view["finalWav"] == version.final_wav
    assert view["original"]["lufs"].endswith("LUFS") and view["final"]["truePeak"].endswith("dBTP")
    lead = next(p for p in view["parts"] if p["label"] == "Lead")
    assert lead["role"] == "Voix principale" and all(t["reason"] for t in lead["treatments"])
    assert any("gardés tels quels" in n for n in lead["notes"])  # FL reverb rendered apart
    # the 808 is also sent to the vocal bus, but the toy beat's tones cover the voices by more than 12 dB, where
    # a dip uncovers nothing: nothing is carved, so the rest of the mix has no line (a carved one is shown:
    # test_engine_mix.test_a_beat_that_shares_a_bus_with_the_voices_is_carved_and_shown)
    assert [p["roleKey"] for p in view["parts"][2:]] == ["bass", "beat"]
    assert any(line.startswith("Tempo : 120") for line in view["song"])
    assert view["master"] and view["platforms"][0]["heard"].endswith("LUFS") and len(view["checks"]) == 3
    versions = viewmodel.versions_view(list_versions(project))
    assert versions[0]["id"] == version.id and versions[0]["intensity"] == 100


def test_export_message_gives_the_final_peak():
    result = ExportResult("C:/Musique/Son.wav", 48000, 24, True, False, -3.04)
    assert viewmodel.export_message(result) == (
        "WAV exporté : C:/Musique/Son.wav (48 kHz, 24 bits, fréquence convertie, crête -3.0 dBTP)")
