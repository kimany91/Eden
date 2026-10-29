import os
import shutil

import numpy as np
import pytest
import soundfile as sf

from eden.project.inspector import InspectionError, inspect_project
from eden.project.sources import SearchRoots
from eden.report import render_markdown
from flp_builder import Chan, Clip, Insert, Slot, build_flp, vst_data

BAR = 96 * 4


def _write_wav(path, seconds, channels, sr=48000):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * sr)
    data = np.zeros((frames, channels), dtype=np.float32)
    sf.write(path, data, sr, subtype="PCM_24")


@pytest.fixture
def rap_project(tmp_path):
    """A small rap session: lead + adlib through a vocal bus, a stereo beat."""
    proj_dir = tmp_path / "Mon son"
    _write_wav(proj_dir / "Recorded" / "Lead take 1.wav", 20, 1)
    _write_wav(proj_dir / "Recorded" / "Adlibs.wav", 20, 1)
    _write_wav(proj_dir / "Beat.wav", 60, 2)
    inserts = [
        Insert(routes=()),
        Insert(name="Voix", routes=(3,), slots={
            0: Slot("Fruity Wrapper", data=vst_data("Auto-Tune Pro", "Antares", r"C:\VST3\Auto-Tune Pro.vst3")),
            1: Slot("Fruity parametric EQ 2"),
        }),
        Insert(name="Adlib", routes=(3,), slots={0: Slot("Fruity Delay 3", enabled=False)}),
        Insert(name="Bus voix", routes=(0,), slots={0: Slot("Fruity Reeverb 2")}),
        Insert(name="Instru", routes=(0,)),
        Insert(name="Nulle part", routes=()),
    ]
    # Absolute Windows paths from the original machine: the project was moved since.
    channels = [
        Chan("Audio 1", insert=1, sample_path=r"D:\Old\Mon son\Recorded\Lead take 1.wav"),
        Chan("Audio 2", insert=2, sample_path=r"D:\Old\Mon son\Recorded\Adlibs.wav"),
        Chan("Audio 3", insert=4, sample_path=r"D:\Old\Mon son\Beat.wav"),
        Chan("Perdu", insert=5, sample_path=r"D:\Old\Mon son\Recorded\Perdu.wav"),
    ]
    clips = [
        Clip(1, 0, BAR * 8, channel=0),
        Clip(2, BAR * 2, BAR * 8, channel=1),
        Clip(3, 0, BAR * 24, channel=2),
        Clip(4, 0, BAR, channel=3),
    ]
    flp = proj_dir / "Mon son.flp"
    flp.write_bytes(build_flp(channels, inserts, clips, track_names={1: "Lead", 3: "Instru"}, tempo=96))
    return flp


def _inspect(path, **kw):
    return inspect_project(path, roots=SearchRoots(), **kw)


def test_original_project_is_untouched(rap_project):
    before_bytes = rap_project.read_bytes()
    before_stat = os.stat(rap_project)
    folder_before = sorted(p.name for p in rap_project.parent.rglob("*"))
    report = _inspect(rap_project)
    assert rap_project.read_bytes() == before_bytes
    assert os.stat(rap_project).st_mtime_ns == before_stat.st_mtime_ns
    # Nothing was written in the project folder
    assert sorted(p.name for p in rap_project.parent.rglob("*")) == folder_before
    assert report.file.sha256 and report.snapshot_path
    assert open(report.snapshot_path, "rb").read() == before_bytes
    assert os.environ["EDEN_HOME"] in report.snapshot_path


def test_snapshot_is_deduplicated(rap_project):
    a = _inspect(rap_project)
    b = _inspect(rap_project)
    assert a.snapshot_path == b.snapshot_path
    assert a.report_path != b.report_path


def test_sources_roles_and_routing(rap_project):
    r = _inspect(rap_project)
    by_label = {s.label: s for s in r.sources}
    lead, adlib, beat = by_label["Audio 1"], by_label["Audio 2"], by_label["Audio 3"]

    assert lead.role.role == "lead_vocal"
    assert adlib.role.role == "adlib"
    assert beat.role.role == "beat"

    assert lead.signal_path == [1, 3, 0] and lead.reaches_master
    cats = {(fx.plugin, fx.category, fx.active) for fx in lead.existing_effects}
    assert ("Auto-Tune Pro", "pitch_correction", True) in cats
    assert ("Fruity Reeverb 2", "reverb", True) in cats  # from the vocal bus
    assert {(fx.plugin, fx.active) for fx in adlib.existing_effects} >= {("Fruity Delay 3", False)}


def test_moved_project_files_are_found(rap_project):
    r = _inspect(rap_project)
    lead = next(s for s in r.sources if s.label == "Audio 1")
    assert lead.sample.status == "found_elsewhere"
    assert lead.sample.audio.channels == 1
    assert lead.sample.audio.sample_rate == 48000
    assert abs(lead.sample.audio.duration_s - 20) < 1e-6
    assert lead.first_seconds == 0 and abs(lead.last_seconds - 20) < 1e-9  # 8 bars at 96 BPM


def test_missing_file_and_unrouted_insert_warnings(rap_project):
    r = _inspect(rap_project)
    perdu = next(s for s in r.sources if s.label == "Perdu")
    assert perdu.sample.status == "missing"
    assert perdu.role.role == "vocal"  # only hint: it lived in the Recorded folder
    assert not perdu.reaches_master
    assert any("introuvable" in w and "Perdu" in w for w in r.warnings)
    assert any("n'atteint pas le Master" in w for w in r.warnings)


def test_progress_steps_are_real_and_ordered(rap_project):
    seen = []
    _inspect(rap_project, on_step=lambda i, n, s: seen.append((i, n)))
    assert seen == [(i, 6) for i in range(6)]


def test_markdown_report(rap_project):
    md = render_markdown(_inspect(rap_project))
    assert "## Voix détectées (3)" in md  # lead, adlib, and the missing take in Recorded/
    assert "Auto-Tune Pro" in md and "Correction de hauteur" in md
    assert "Limites de cette analyse" in md


def test_errors_name_the_failed_step(tmp_path):
    with pytest.raises(InspectionError) as e:
        _inspect(tmp_path / "absent.flp")
    assert e.value.step == "Lecture du fichier"

    bad = tmp_path / "faux.flp"
    bad.write_bytes(b"RIFF....WAVEfmt ")
    with pytest.raises(InspectionError) as e:
        _inspect(bad)
    assert e.value.step == "Décodage du projet"

    wav = tmp_path / "son.wav"
    wav.write_bytes(b"x")
    with pytest.raises(InspectionError, match="n'est pas un fichier .flp"):
        _inspect(wav)


def test_detects_project_saved_during_analysis(rap_project, monkeypatch):
    import eden.project.inspector as insp

    real = insp.resolve_source

    def save_from_fl_meanwhile(*a, **k):
        with open(rap_project, "ab") as fh:
            fh.write(b"\0")
        return real(*a, **k)

    monkeypatch.setattr(insp, "resolve_source", save_from_fl_meanwhile)
    with pytest.raises(InspectionError) as e:
        _inspect(rap_project)
    assert e.value.step == "Vérification de l'intégrité du projet"


def test_no_snapshot_option(rap_project):
    r = _inspect(rap_project, keep_snapshot=False)
    assert r.snapshot_path is None and r.report_path is None
    assert not os.path.exists(os.environ["EDEN_HOME"])
