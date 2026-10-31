"""A beat downloaded whole (one WAV from YouTube, already mixed and mastered): the complete beat
whatever its name says, its mix kept as it is, and a master that does not squash it a second time."""

import numpy as np
import pytest
import soundfile as sf

from eden.mix import master as M
from eden.mix import session
from eden.mix.engine import mix
from eden.mix.limiter import limit
from eden.mix.loudness import integrated_loudness
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render.pipeline import render_project
from flp_builder import Chan, Clip, Insert, build_flp
from synth_voice import FS, beat, voice
from test_engine_mix import _parts
from test_render import BAR, make_session, sim_renderer

SONG_S = 40.0  # bars of 2 s at 120 BPM


def _sound(rng, seconds, stereo, kind):
    """A take of a voice (mono, or bounced in stereo, both sides the same; pauses between its phrases), a beat
    (stereo, low end, never stops) or an 808 (low end only)."""
    t = np.arange(int(seconds * 22050)) / 22050
    if kind == "voice":
        mono = 0.2 * rng.standard_normal(t.size) * np.clip(np.sin(2 * np.pi * 3 * t), 0, None)
        return np.stack([mono, 0.9 * mono], axis=1) if stereo else mono
    low = 0.3 * np.sin(2 * np.pi * 50 * t)
    if kind == "808":
        return np.stack([low, low], axis=1) if stereo else low
    sides = [low + 0.1 * rng.standard_normal(t.size) for _ in range(2 if stereo else 1)]
    return np.stack(sides, axis=1) if stereo else sides[0]


def _project(folder, sources):
    """A project of (channel name, seconds, stereo, sound) audio files, each played from the start."""
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(3)
    channels, clips = [], []
    for i, (name, seconds, stereo, kind) in enumerate(sources):
        sf.write(folder / f"{name}.wav", _sound(rng, seconds, stereo, kind), 22050)
        channels.append(Chan(name, insert=0, sample_path=str(folder / f"{name}.wav")))
        clips.append(Clip(i + 1, 0, BAR * max(1, int(seconds / 2)), channel=i))
    flp = folder / "Mon son.flp"
    flp.write_bytes(build_flp(channels, [Insert(routes=())], clips, tempo=120))
    return {s.label: s.role for s in inspect_project(flp, roots=SearchRoots(), archive_report=False).sources}


VOICES = [("Lead", SONG_S, False, "voice"), ("Adlib", SONG_S / 2, False, "voice")]


@pytest.mark.parametrize("name", ["UK Drill - Hats & Percs", "Dark 808 Melody", "Kick Back", "y2mate.com - LEGEND",
                                  "Freeze Corleone Type Beat - HATS (Prod. Kosei)"])
def test_a_beat_downloaded_whole_is_the_complete_beat_whatever_its_name(tmp_path, name):
    roles = _project(tmp_path, [*VOICES, (name, SONG_S, True, "beat")])
    assert roles[name].role == "beat" and roles[name].confidence == "haute", roles[name].reasons
    assert roles["Lead"].is_vocal and roles["Adlib"].is_vocal


def test_stems_keep_what_their_names_say(tmp_path):
    # one file per instrument, each as long as the song: the names tell them apart
    roles = _project(tmp_path, [*VOICES, ("Hats", SONG_S, True, "beat"), ("808", SONG_S, True, "808")])
    assert roles["Hats"].role == "drums" and roles["808"].role == "bass"


def test_a_long_stereo_voice_stays_a_voice_beside_a_beat_of_its_own(tmp_path):
    # the voice bounced in stereo over the whole song, and the beat made of samples: the voice stays one
    roles = _project(tmp_path, [("Lead", SONG_S, True, "voice"), ("Kick", 1.0, False, "beat"),
                                ("Snare", 1.0, False, "beat")])
    assert roles["Lead"].role == "lead_vocal" and roles["Kick"].role == "drums"


# -- the mix and the master --------------------------------------------------------------------

def _mastered(x, lufs):
    """A beatmaker's master: pushed into a limiter at −0.3 dBTP until it reaches ``lufs``."""
    for gain in np.arange(0.0, 30.0, 0.5):
        y = limit(x * 10 ** (gain / 20), FS, -0.3).audio
        if integrated_loudness(y, FS) >= lufs:
            return y
    raise AssertionError("never that loud")


def test_the_mix_keeps_a_complete_beat_as_it_is():
    told = []
    parts = _parts([("ch0", "Lead", "lead_vocal", voice(8.0, seed=11), None)],
                   [("g1", "UK Drill - Hats & Percs", "beat", beat(8.0))])
    out = mix(parts, 1.0, 95.0, {"ch0": "none"}, progress=lambda text, share: told.append(text))
    assert told[0] == "Analyse du morceau : tonalité et tempo"  # no kick nor 808 looked for in it
    assert any("instru complète, déjà mixée et masterisée" in t for t in told)
    assert not any(t.startswith("Basses") for t in told) and not any("808" in w for w in out.warnings)
    beat_part = next(p for p in out.parts if p.role == "beat")
    # only room for the words, while the voice sings: no EQ, compression nor 808 work on the beat
    assert [t.kind for t in beat_part.treatments] in ([], ["carve"]), [t.label for t in beat_part.treatments]


def test_the_master_does_not_squash_a_mastered_beat_a_second_time():
    seconds = 12.0
    song = _mastered(beat(seconds), -11.0) + 0.5 * voice(seconds, seed=11)
    normal = M.master(song, FS, 1.0, 95.0)
    finished = M.master(song, FS, 1.0, 95.0, finished_beat=True)
    squash = lambda r: r.treatments[-1].measured["peak_reduction_db"]  # noqa: E731
    # both masters are stopped by their budgets (6 dB normal, 5 dB finished): the finished one takes less
    assert squash(normal) > squash(finished) + 0.2
    assert squash(finished) <= M.FINISHED_BEAT_PEAK_REDUCTION_DB + 0.1
    assert finished.checks.integrated_lufs < normal.checks.integrated_lufs
    assert any("ton instru est déjà mixée et masterisée" in w for w in finished.warnings)


def test_a_session_with_a_complete_beat_masters_it_as_finished(tmp_path, monkeypatch):
    project = make_session(tmp_path)  # its "Instru" is a stereo beat played straight into the Master
    report = inspect_project(project, roots=SearchRoots())
    renders = render_project(project, sim_renderer(), timeout_s=120, report=report)
    asked = []
    real = session.master
    monkeypatch.setattr(session, "master", lambda *a, **kw: asked.append(kw["finished_beat"]) or real(*a, **kw))
    session.mix_project(project, report, renders, intensity=1.0)
    assert asked == [True]
