"""Whatever the tracks are called: Eden listens to each file to tell a voice from an instrument
(project/listen.py), and places on the song's timeline the voices whose names say nothing of their role
(project/inspector.py): the takes no other voice is under are the lead, the ones laid over it ad-libs or
backs."""

import numpy as np
import soundfile as sf

from eden.project.classify import guess_role
from eden.project.inspector import inspect_project
from eden.project.listen import Heard, listen
from eden.project.sources import SearchRoots
from flp_builder import Chan, Clip, Insert, build_flp
from test_render import BAR

SR = 22050


def _voice(seconds, rng, every_s=0.33, burst_s=0.2):
    """A take at the mic: mono, no low end, words with pauses between them."""
    t = np.arange(int(seconds * SR)) / SR
    words = (t % every_s) < burst_s
    hiss = rng.standard_normal(t.size)
    voiced = np.convolve(hiss, np.ones(8) / 8, mode="same") - np.convolve(hiss, np.ones(64) / 64, mode="same")
    return 0.3 * voiced * words


def _beat(seconds, rng):
    """A beat: stereo, an 808 under it, never stops."""
    t = np.arange(int(seconds * SR)) / SR
    low = 0.3 * np.sin(2 * np.pi * 50 * t)
    return np.stack([low + 0.1 * rng.standard_normal(t.size) for _ in range(2)], axis=1)


def test_a_voice_and_a_beat_are_told_apart_by_ear(tmp_path):
    rng = np.random.default_rng(1)
    sf.write(tmp_path / "v.wav", _voice(10, rng), SR)
    sf.write(tmp_path / "b.wav", _beat(10, rng), SR)
    sf.write(tmp_path / "v-stereo.wav", np.stack([_voice(10, rng)] * 2, axis=1), SR)  # bounced in stereo
    t = np.arange(10 * SR) / SR
    sf.write(tmp_path / "loop.wav", np.stack([0.2 * np.sin(2 * np.pi * 440 * t + k) for k in (0, 2)], axis=1), SR)
    assert listen(tmp_path / "v.wav").kind == "voice"
    assert listen(tmp_path / "v-stereo.wav").kind == "voice"
    beat = listen(tmp_path / "b.wav")
    assert beat.kind == "instrument" and beat.sub_share > 0.5 and not beat.mono
    assert listen(tmp_path / "loop.wav").kind == "instrument"  # stereo, never stops, no low end
    sf.write(tmp_path / "yeah.wav", _voice(1, rng), SR)
    assert listen(tmp_path / "yeah.wav") is None  # too short to tell: its name says more
    assert listen(tmp_path / "absent.wav") is None


def test_the_sound_says_voice_or_instrument_the_names_say_which():
    voice = Heard("voice", 0.0, 0.5, 10.0, True, "À l'écoute, une voix")
    synth = Heard("instrument", 0.0, 1.0, 30.0, False, "À l'écoute, un instrument")
    assert guess_role([("Canal", "beat 2")], heard=voice).role == "vocal"  # its name said beat
    assert guess_role([("Canal", "ad-lib fin")], heard=voice).role == "adlib"
    assert guess_role([("Canal", "Lead")], heard=synth).role == "music"  # a lead synth
    assert guess_role([("Canal", "Hats")], heard=synth).role == "drums"
    assert "le son l'emporte sur le nom" in guess_role([("Canal", "beat 2")], heard=voice).reasons


def test_tracks_named_anyhow_get_their_roles(tmp_path):
    # two takes of the lead one after the other, ad-libs laid over them, the beat: none named after what it is
    d = tmp_path / "Son"
    d.mkdir()
    rng = np.random.default_rng(3)
    files = {"kim 1": _voice(10, rng), "kim 2": _voice(10, rng), "mbappé": _voice(20, rng, every_s=3.0, burst_s=0.4),
             "zz": _beat(20, rng)}
    for name, audio in files.items():
        sf.write(d / f"{name}.wav", audio, SR)
    channels = [Chan(name, insert=0, sample_path=str(d / f"{name}.wav")) for name in files]
    clips = [Clip(1, 0, BAR * 5, channel=0), Clip(1, BAR * 5, BAR * 5, channel=1),
             Clip(2, 0, BAR * 10, channel=2), Clip(3, 0, BAR * 10, channel=3)]
    flp = d / "Son.flp"
    flp.write_bytes(build_flp(channels, [Insert(routes=())], clips, tempo=120))
    report = inspect_project(flp, roots=SearchRoots(), archive_report=False)
    roles = {s.label: s.role.role for s in report.sources}
    assert roles == {"kim 1": "lead_vocal", "kim 2": "lead_vocal", "mbappé": "adlib", "zz": "beat"}, roles
    assert not any(w.startswith("Aucune voix") for w in report.warnings)


def _deep(seconds, rng):
    """A deep voice close to the mic (its fundamental around 80-150 Hz, the proximity effect on top)."""
    t = np.arange(int(seconds * SR)) / SR
    words = (t % 0.33) < 0.2
    pitch = 0.25 * np.sin(2 * np.pi * (95 + 20 * np.sin(2 * np.pi * 0.5 * t)) * t)
    return (pitch + 0.1 * _voice(seconds, rng)) * words


def test_real_takes_are_heard_as_voices(tmp_path):
    rng = np.random.default_rng(4)
    leak = 0.03 * _beat(20, rng)  # the beat in the headphones, leaking into the mic: -20 dB and more under the voice
    take = _deep(20, rng)
    sf.write(tmp_path / "grave.wav", take, SR)
    sf.write(tmp_path / "fuite.wav", take + leak.mean(axis=1), SR)
    sf.write(tmp_path / "un-cote.wav", np.stack([take, 0.001 * rng.standard_normal(take.size)], axis=1), SR)
    for name in ("grave", "fuite", "un-cote"):
        heard = listen(tmp_path / f"{name}.wav")
        assert heard.kind == "voice", (name, heard)


def test_a_take_recorded_in_fl_stays_a_voice_unless_it_is_mostly_low_end():
    take = [("Canal", "lucki type beat - 'casino'_2026-10-25 19-13-21_AUTOTUNE")]
    unclear = Heard("instrument", 0.3, 0.97, 100.0, False, "À l'écoute, un instrument")
    assert guess_role(take, heard=unclear).is_vocal
    bass = Heard("instrument", 0.8, 1.0, 100.0, True, "À l'écoute, un instrument")
    assert not guess_role(take, heard=bass).is_vocal  # a bass recorded through the interface
