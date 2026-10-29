"""The dry voice: which effects count, which renders Eden plans for it, how FL's dry
render is checked, and the fl-probe check that FL really bypasses an effect slot."""

import sys
import tracemalloc

import numpy as np
import pytest
import soundfile as sf

from eden.mix.parts import Part, Parts, dry_render_problem, split
from eden.mix.session import fl_space_status
from eden.project.classify import RoleGuess
from eden.project.inspector import SourceAnalysis, _effects_on, _signal_path, inspect_project
from eden.project.model import FlpProject, MixerInsert, MixerSlot, PluginInfo, Route
from eden.project.plugins import categorize
from eden.project.sources import SearchRoots
from eden.render.pipeline import render_project
from eden.render.plan import _dry_edits, plan_renders
from eden.render.probe import probe_fl_studio
from eden.report import render_markdown
from eden.settings import load_settings
from flp_builder import Chan, Clip, Insert, Slot, build_flp
from synth_voice import FS, voice
from test_render import SIM, make_session, sim_renderer

BAR = 96 * 4  # 2 s at 120 BPM
SR = 22050


def make_project(folder, inserts):
    """A lead on insert 1 and a beat on the last insert, 2 s long, with the given mixer."""
    folder.mkdir(parents=True)
    t = np.arange(int(2.0 * SR)) / SR
    syllables = np.clip(np.sin(2 * np.pi * 3 * t), 0, None)  # broadband and in syllables, like a voice
    sf.write(folder / "Lead.wav", 0.15 * np.random.default_rng(3).standard_normal(t.size) * syllables, SR)
    sf.write(folder / "Beat.wav", np.stack([0.2 * np.sin(2 * np.pi * 55 * t)] * 2, axis=1), SR)
    channels = [Chan("Lead", insert=1, sample_path=str(folder / "Lead.wav")),
                Chan("Instru", insert=len(inserts) - 1, sample_path=str(folder / "Beat.wav"))]
    flp = folder / "Dry.flp"
    flp.write_bytes(build_flp(channels, inserts, [Clip(1, 0, BAR, channel=0), Clip(2, 0, BAR, channel=1)],
                              tempo=120))
    return flp


def _report(path):
    return inspect_project(path, roots=SearchRoots())


def _lead(project, insert=1):
    path, reaches = _signal_path(project, insert)
    return SourceAnalysis(0, "Lead", "sampler", insert, "Lead", path, reaches,
                          _effects_on(project, [i for i in path if i]), RoleGuess("lead_vocal"), 1, 0.0, 2.0)


def _slot(index, name, enabled=True, mix_raw=None):
    return MixerSlot(index, PluginInfo(name), enabled=enabled, mix_raw=mix_raw)


# -- which effects are heard ------------------------------------------------------------

def send_to_return(**reverb_insert):
    """Lead to the Master, plus a send to a reverb return on insert 2."""
    return [Insert(routes=()),
            Insert(name="Lead", routes=(0, 2), slots={0: Slot("Fruity parametric EQ 2")}),
            Insert(name="Reverb", slots={0: Slot("Fruity Reeverb 2")}, **{"routes": (0,), **reverb_insert}),
            Insert(name="Instru", routes=(0,))]


@pytest.mark.parametrize("reverb_insert,shown", [({"enabled": False}, "inaudible (insert coupé)"),
                                                  ({"routes": ()}, "inaudible (insert sans sortie vers le Master)")],
                         ids=["muted", "routed-nowhere"])
def test_a_reverb_return_fl_never_plays_is_not_a_space_effect(tmp_path, reverb_insert, shown):
    project = make_project(tmp_path / "Projet", send_to_return(**reverb_insert))
    report = _report(project)
    lead = report.sources[0]
    assert [(e.plugin, e.active) for e in lead.existing_effects if e.insert == 2] == [("Fruity Reeverb 2", False)]
    assert lead.space_effects == []
    assert f"Fruity Reeverb 2 [Reverb] — {shown}" in render_markdown(report)
    plan = plan_renders(report)
    assert not any(j.kind == "vocal_dry" for j in plan.jobs)
    result = render_project(project, sim_renderer(), timeout_s=120, report=report)
    assert result.ok
    parts = split(report, result)
    assert fl_space_status(report, parts) == {"ch0": "none"}  # Eden may add its own space


def test_a_muted_return_costs_no_dry_render(tmp_path):
    live = plan_renders(_report(make_project(tmp_path / "Live", send_to_return())))
    muted = plan_renders(_report(make_project(tmp_path / "Muted", send_to_return(enabled=False))))
    assert [j.name for j in live.jobs if j.kind == "vocal_dry"] == ["dry-ch000-lead"]
    assert [j.name for j in muted.jobs] == [j.name for j in live.jobs if j.kind != "vocal_dry"]


def test_a_slot_with_its_mix_at_zero_is_not_heard():
    project = FlpProject(inserts=[
        MixerInsert(0, "Master", routes=[]),
        MixerInsert(1, "Lead", routes=[Route(0)], slots=[_slot(0, "Fruity Delay 3", mix_raw=0),
                                                        _slot(1, "Fruity Reeverb 2", mix_raw=6400)])])
    assert [(e.plugin, e.active) for e in _effects_on(project, [1])] == [
        ("Fruity Delay 3", False), ("Fruity Reeverb 2", True)]


# -- vocal bus or effect return ---------------------------------------------------------

def bus_and_return(bus, ret):
    """Lead into a vocal bus (compressor, then an in-line delay) and into a reverb return."""
    inserts = [Insert(routes=())] + [Insert() for _ in range(4)]
    inserts[1] = Insert(name="Lead", routes=(bus, ret))
    inserts[bus] = Insert(name="Bus voix", routes=(0,), slots={0: Slot("Fruity Compressor"), 1: Slot("Fruity Delay 3")})
    inserts[ret] = Insert(name="Reverb", routes=(0,), slots={0: Slot("Fruity Reeverb 2")})
    inserts[4] = Insert(name="Instru", routes=(0,))
    return inserts


@pytest.mark.parametrize("bus,ret", [(2, 3), (3, 2)])
def test_a_vocal_bus_and_a_reverb_return_are_told_apart_whatever_their_numbers(tmp_path, monkeypatch, bus, ret):
    monkeypatch.setenv("EDEN_SIM_WET_REVERB", "1")  # the return's reverb gives its tail only
    project = make_project(tmp_path / "Projet", bus_and_return(bus, ret))
    report = _report(project)
    dry = next(j for j in plan_renders(report).jobs if j.kind == "vocal_dry")
    assert dry.mute_inserts == [ret]  # the return
    assert dry.bypass_slots == [(bus, 1)]  # the bus's delay; the bus and its compressor stay
    result = render_project(project, sim_renderer(), timeout_s=120, report=report)
    assert result.ok
    parts = split(report, result)
    assert parts.voices[0].dry is not None and not parts.warnings
    assert fl_space_status(report, parts) == {"ch0": "tracked"}


@pytest.mark.parametrize("first", [{0: Slot("Fruity Compressor")}, {}], ids=["two-buses", "two-returns"])
def test_alternative_ways_eden_cannot_tell_apart_get_no_dry_render(tmp_path, first):
    # the lead reaches the Master through insert 2 or insert 3, each holding a reverb or delay,
    # both starting with a compressor (two buses) or both with the effect (two returns)
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(2, 3)),
        Insert(name="Bus 2", routes=(0,), slots={**first, 1: Slot("Fruity Delay 3")}),
        Insert(name="Bus 3", routes=(0,), slots={**first, 1: Slot("Fruity Reeverb 2")}),
        Insert(name="Instru", routes=(0,))])
    report = _report(project)
    assert _dry_edits(report.project, report.sources[0]) == (
        [], [], "elle atteint le Master par plusieurs inserts avec reverb ou delay (« Bus 2 », « Bus 3 ») "
                "sans qu'Eden puisse dire lesquels sont des retours d'effet")
    plan = plan_renders(report)
    assert not any(j.kind == "vocal_dry" for j in plan.jobs)
    assert "« Lead » : pas de voix sèche, elle atteint le Master par plusieurs inserts avec reverb ou delay " \
           "(« Bus 2 », « Bus 3 ») sans qu'Eden puisse dire lesquels sont des retours d'effet ; ses reverbs " \
           "et delays FL seront traités avec prudence au mixage" in plan.notes


# -- reverbs and delays Eden did not know ------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("Blackhole", "reverb"), ("Eventide Blackhole", "reverb"), ("UAD EMT 140", "reverb"),
    ("UAD Lexicon 224", "reverb"), ("PCM Random Hall", "reverb"), ("Abbey Road Chambers", "reverb"),
    ("Shimmer", "reverb"), ("Rev INTENSITY", "reverb"), ("Rev SPRING-636", "reverb"),
    ("IR1 Full Stereo", "reverb"),
    ("PrimalTap", "delay"), ("Replika XT", "delay"), ("Crystallizer", "delay"), ("CLA Epic", "delay"),
    ("TAL-Dub-X", "delay"), ("SuperTap 2-Taps Stereo", "delay"), ("OhmBoyz", "delay"),
    # earlier rules unchanged
    ("ValhallaDelay", "delay"), ("Valhalla Supermassive", "reverb"), ("H-Delay Stereo", "delay"),
    ("MicroShift", "stereo"), ("S1 Stereo Imager", "stereo"), ("Revoice Pro", "pitch_correction"),
])
def test_more_reverb_and_delay_plugins_are_recognised(name, expected):
    assert categorize(PluginInfo("Fruity Wrapper", vst_name=name)) == expected


def unknown_on(name, routes_to_master=True):
    """Lead sends to insert 2, named ``name``, holding a plugin Eden does not identify."""
    lead_routes = (0, 2) if routes_to_master else (2,)
    return [Insert(routes=()), Insert(name="Lead", routes=lead_routes),
            Insert(name=name, routes=(0,), slots={0: Slot("Mystery FX")}),
            Insert(name="Instru", routes=(0,))]


def _status_without_dry(report):
    silent = np.zeros((10, 2))
    parts = Parts([Part("ch0", "Lead", "lead_vocal", silent, [0])], [],
                  Part("residual", "Reste", "residual", silent), SR, silent)
    return fl_space_status(report, parts)


def test_an_unknown_plugin_on_an_insert_named_reverb_is_a_return(tmp_path):
    report = _report(make_project(tmp_path / "Projet", unknown_on("Reverb")))
    assert categorize(report.project.insert(2).slots[0].plugin) == "unknown"
    plan = plan_renders(report)
    dry = next(j for j in plan.jobs if j.kind == "vocal_dry")
    assert dry.mute_inserts == [2] and dry.bypass_slots == []
    assert "« Mystery FX » (insert « Reverb ») : plugin non identifié, compté comme reverb ou delay " \
           "d'après le nom de l'insert" in plan.notes


def test_an_unknown_plugin_on_the_voices_way_leaves_it_untracked(tmp_path):
    report = _report(make_project(tmp_path / "Projet", unknown_on("Verb bus", routes_to_master=False)))
    plan = plan_renders(report)
    assert not any(j.kind == "vocal_dry" for j in plan.jobs)
    assert "« Lead » : pas de voix sèche, « Mystery FX » (insert « Verb bus »), non identifié, est sur son " \
           "chemin vers le Master ; ses reverbs et delays FL seront traités avec prudence au mixage" in plan.notes
    assert _status_without_dry(report) == {"ch0": "untracked"}  # no Eden reverb on top of it


@pytest.mark.parametrize("name", ["Bus 2", "Insert 2"])
def test_an_unknown_plugin_on_an_insert_named_otherwise_does_not_count(tmp_path, name):
    report = _report(make_project(tmp_path / "Projet", unknown_on(name)))
    assert report.sources[0].space_effects == []
    assert not any(j.kind == "vocal_dry" for j in plan_renders(report).jobs)
    assert _status_without_dry(report) == {"ch0": "none"}


def test_an_unknown_plugin_on_the_voices_own_insert_does_not_count():
    project = FlpProject(inserts=[MixerInsert(0, "Master", routes=[]),
                                  MixerInsert(1, "Lead delay", routes=[Route(0)], slots=[_slot(0, "Mystery FX")])])
    assert _lead(project).space_effects == []


# -- checking FL's dry render ------------------------------------------------------------

@pytest.mark.parametrize("shift,problem", [
    (64, "décalée de 1.5 ms"), (512, "décalée de 11.6 ms"), (2048, "décalée de 46.4 ms"),
    (4410, "décalée de 100.0 ms"), (4420, "décalée de plus de 100 ms"), (6000, "décalée de plus de 100 ms"),
])
def test_the_offset_of_a_shifted_dry_render_is_stated_right(shift, problem):
    v = voice(12, seed=5)
    full = v + 0.3 * np.roll(v, int(0.25 * FS), axis=0)
    assert dry_render_problem(full, np.roll(v, shift, axis=0), FS) == problem


@pytest.mark.parametrize("kept,echo", [(0.5, 1.0), (0.3, 0.5)])
def test_a_dry_wet_knob_that_lowers_the_voice_is_not_taken_for_an_offset(kept, echo):
    # an in-line delay whose mix knob also lowers the voice: the dry render is in place,
    # but the full one holds the voice at half its level or less
    v = voice(12, seed=5)
    full = kept * v + echo * np.roll(v, int(0.25 * FS), axis=0)
    assert dry_render_problem(full, v, FS) == \
        "la voix elle-même reste dans la part des effets (retour d'effet ou réglage dry/wet d'un plugin)"


def test_a_dry_render_equal_to_the_full_one_is_refused():
    v = voice(6, seed=2)
    full = v + 0.3 * np.roll(v, int(0.25 * FS), axis=0)
    assert dry_render_problem(full, full.copy(), FS) == \
        "FL Studio n'a rien retiré (effets coupés non respectés ou inaudibles)"


def test_the_dry_render_check_needs_no_whole_song_buffers():
    n = 30 * FS
    rng = np.random.default_rng(0)
    dry = (0.1 * rng.standard_normal((n, 2))).astype(np.float32)  # voices are kept in 32-bit float
    full = dry + np.float32(0.3) * np.roll(dry, 4000, axis=0)
    tracemalloc.start()
    try:
        assert dry_render_problem(full, dry, FS) is None
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    # a few mono copies of the song; a whole-song FFT needed about ten of them
    assert peak < 5 * n * 8


def test_a_dry_render_fl_did_not_bypass_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("EDEN_SIM_IGNORE_SLOTS", "1")
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(0,), slots={0: Slot("Fruity Delay 3")}),
        Insert(name="Instru", routes=(0,))])
    report = _report(project)
    result = render_project(project, sim_renderer(), timeout_s=120, report=report)
    parts = split(report, result)
    assert parts.voices[0].dry is None
    assert parts.warnings == ["« Lead » : la voix sèche rendue par FL Studio ne colle pas à la voix complète "
                              "(FL Studio n'a rien retiré (effets coupés non respectés ou inaudibles)) ; "
                              "ses effets FL sont traités avec prudence"]
    assert fl_space_status(report, parts) == {"ch0": "untracked"}


# -- fl-probe: is a bypassed slot really bypassed? ---------------------------------------

def _probe(project, tmp_path):
    settings = tmp_path / "settings.json"
    res = probe_fl_studio(project, command=[sys.executable, SIM], timeout_s=120,
                          settings_file=settings, log=lambda m: None)
    return res, load_settings(settings)


def test_probe_checks_that_a_bypassed_slot_is_bypassed(tmp_path):
    res, settings = _probe(make_session(tmp_path), tmp_path)
    assert res.isolation_slots_ok is True and res.ok
    assert any("« Fruity Reeverb 2 » sur « Bus voix », Lead seule) : le rendu change" in line for line in res.lines)
    assert settings.render_args


def test_probe_fails_when_fl_plays_a_bypassed_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("EDEN_SIM_IGNORE_SLOTS", "1")
    res, settings = _probe(make_session(tmp_path), tmp_path)
    assert res.isolation_channels_ok and res.isolation_inserts_ok and res.isolation_routes_ok
    assert res.isolation_slots_ok is False and not res.ok
    assert any("le rendu ne change pas (écart sous -60 dB) ✘" in line for line in res.lines)
    assert settings.render_args is None  # nothing saved


def test_probe_without_reverb_or_delay_cannot_check_slots(tmp_path):
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(0,), slots={0: Slot("Fruity parametric EQ 2")}),
        Insert(name="Instru", routes=(0,))])
    res, settings = _probe(project, tmp_path)
    assert res.isolation_slots_ok is None and res.ok
    assert "Test d'isolation (slot d'effet contourné) : non vérifié sur ce projet (aucune piste de la " \
           "playlist ne passe par une reverb ou un delay actif dont FL a enregistré l'état " \
           "activé/désactivé)" in res.lines
    assert settings.render_args
