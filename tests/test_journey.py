"""The journey Eden shows while it works: the mix and the master tell each step with the share of the work
done, the journal says what was found and decided, and the stages of the work are the tree's."""

import numpy as np
import pytest

from eden.gui import garden, viewmodel
from eden.mix.engine import mix
from eden.mix.master import master
from synth_voice import FS, beat, voice
from test_engine_mix import _808, _parts

SECONDS = 8.0


def _told(run):
    """(steps, details) a run told: steps are (text, share)."""
    steps, details = [], []

    def progress(text, share):
        (details.append(text) if share is None else steps.append((text, share)))

    run(progress)
    return steps, details


def test_the_mix_tells_each_step_with_the_share_of_the_mix_done():
    parts = _parts([("ch0", "Lead", "lead_vocal", voice(SECONDS, seed=11), None),
                    ("ch1", "Double", "double", 0.4 * voice(SECONDS, seed=13), None),
                    ("ch2", "Ad-libs", "adlib", 0.3 * voice(SECONDS, seed=17), None)],
                   [("g1", "Instru", "beat", beat(SECONDS)), ("g2", "808", "bass", _808(SECONDS))])
    steps, details = _told(lambda progress: mix(parts, 1.0, 95.0, {"ch0": "none", "ch1": "none", "ch2": "none"},
                                                 progress=progress))
    shares = [share for _, share in steps]
    # the song, the lead, the low end, room for the words, the balance, the two other voices, the whole mix
    assert len(steps) == 8 and shares == sorted(shares) and shares[0] == 0 and shares[-1] < 1
    assert np.allclose(np.diff(shares), 1 / 8)
    texts = [t for t, _ in steps]
    assert texts[0].startswith("Analyse du morceau") and texts[-1] == "Reverb de tout le morceau et niveau du mix"
    assert texts[1].startswith("Voix « Lead »") and texts[2].startswith("Basses")
    assert texts[5].startswith("Voix « Double »") and texts[6].startswith("Voix « Ad-libs »")
    # what was decided, part by part, as the treatments' own labels
    assert details[0].startswith("Tonalité ")
    assert any(d.startswith("« Lead » : ") and " · " in d for d in details)  # its chain, step by step
    assert any(d.startswith("« Double » : ") for d in details)
    assert any(d.startswith("Espace pour « Lead » : Ambiance courte") for d in details)


def test_an_untouched_mix_tells_only_the_song():
    parts = _parts([("ch0", "Lead", "lead_vocal", voice(SECONDS, seed=11), None)],
                   [("g1", "Instru", "beat", beat(SECONDS))])
    steps, details = _told(lambda progress: mix(parts, 0.0, 95.0, {"ch0": "none"}, progress=progress))
    assert [share for _, share in steps] == [0.0] and details[0].startswith("Tonalité ")


def test_the_master_tells_its_passes_and_its_result():
    x = 0.3 * np.stack([voice(SECONDS, seed=11)[:, 0] + beat(SECONDS)[:, 0]] * 2, axis=1)
    steps, details = _told(lambda progress: master(x, FS, 1.0, 95.0, progress=progress))
    shares = [share for _, share in steps]
    assert shares == sorted(shares) and shares[0] == 0 and shares[-1] == 0.9
    texts = [t for t, _ in steps]
    assert any(t.startswith("Volume final : viser -9.0 LUFS") for t in texts)
    assert any(t.startswith("Écrêtage doux puis limiteur, passage 1") for t in texts)
    assert details[-1].startswith("Master : ") and "LUFS" in details[-1]


def test_the_journal_says_what_the_analysis_found_and_what_fl_rendered():
    report = {"name": "Mon son", "flVersion": "21.2", "tempo": "140 BPM", "timeSignature": "4/4",
              "duration": "3:12", "insertCount": 12, "warnings": ["Un sample manque"],
              "voices": [{"label": "Lead", "role": "Voix principale",
                          "effects": [{"name": "Auto-Tune", "active": True}, {"name": "Delay", "active": False}]}],
              "others": [{"label": f"Piste {i}", "role": "Batterie"} for i in range(9)],
              "masterEffects": [{"name": "Limiter", "active": True}]}
    lines = viewmodel.analysis_lines(report)
    assert lines[0] == ("Projet « Mon son » : FL Studio 21.2, 140 BPM, mesure 4/4, durée 3:12, "
                        "12 pistes de Mixer utilisées", "done")
    assert ("Voix trouvée : « Lead » → Voix principale ; effets : Auto-Tune", "detail") in lines
    assert any(t.startswith("Instru : « Piste 0 »") and t.endswith("et 3 autre(s)") for t, _ in lines)
    assert any(t.startswith("Effets de ton Master FL : Limiter") for t, _ in lines)
    assert lines[-1] == ("Un sample manque", "warn")
    rows = [{"name": "stem-1", "description": "Groupe Batterie", "status": "done", "detail": "180.0 s · crête -1.0 dBFS"},
            {"name": "verification", "description": "Vérification", "status": "done", "detail": ""}]
    summary = {"ok": True, "nullMessage": "Somme des pistes = mix d'origine", "warnings": ["Fin coupée"]}
    assert viewmodel.render_lines(rows, summary) == [
        ("Groupe Batterie : 180.0 s · crête -1.0 dBFS", "done"), ("Somme des pistes = mix d'origine", "done"),
        ("Fin coupée", "warn")]


def test_the_stages_of_the_work_are_the_stages_of_the_tree():
    pytest.importorskip("PySide6.QtCore")
    from eden.gui.controller import JOURNEY, SPANS

    spans = [(start, end) for *_, start, end in JOURNEY]
    assert spans[0][0] == 0 and spans[-1][1] == 1
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:], strict=False))  # one growth, no gap
    # the garden's own schedule: sprout by the analysis' end, first leaves by the renders' end,
    # everything grown by the master's end
    assert dict(garden.TRUNK_SCHEDULE)[SPANS["analysis"][1]] == pytest.approx(0.32)
    assert SPANS["render"][1] == 0.40 and SPANS["master"][1] == garden.GROWN


def test_the_tree_never_shrinks_during_a_journey():
    pytest.importorskip("PySide6.QtCore")
    from eden.gui.controller import EdenController

    c = EdenController(check_updates=False)
    c._enter("render")
    c._grow("render", 0.5)
    high = c.growth
    c._grow("render", 0.2)  # a step reported late
    assert c.growth == high == pytest.approx(0.24)
    c._enter("mix")
    assert [s["status"] for s in c.journeyStages] == ["done", "done", "running", "pending", "pending"]
    assert c.journeyLines()[-1] == {"time": "00:00", "text": "Mixage Eden", "kind": "stage"}
