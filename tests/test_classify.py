import pytest

from eden.project.classify import guess_role
from eden.project.model import PluginInfo
from eden.project.plugins import categorize


@pytest.mark.parametrize("names,expected", [
    ([("Insert", "Voix Lead")], "lead_vocal"),
    ([("Canal", "Lead Vox")], "lead_vocal"),
    ([("Insert", "Backs")], "back_vocal"),
    ([("Piste de playlist", "BV refrain")], "back_vocal"),
    ([("Canal", "Adlibs")], "adlib"),
    ([("Canal", "ad-lib 2")], "adlib"),
    ([("Insert", "Double couplet")], "double"),
    ([("Canal", "Voix")], "vocal"),
    ([("Canal", "Instru")], "beat"),
    ([("Fichier", "type beat 140bpm")], "beat"),
    # a take recorded in FL, named after the project (here the beat's name), the date and the input
    ([("Canal", "lucki type beat - 'casino'_2026-10-25 15-45-47_VOICE")], "vocal"),
    ([("Fichier", "Vertige_2026-10-25 15-46-34_Insert 3")], "vocal"),
    ([("Canal", "lucki type beat - 'casino' [D# min, 149 BPM] [FFP]")], "beat"),
    ([("Canal", "808")], "bass"),
    ([("Canal", "Kick")], "drums"),
    ([("Canal", "Instrument track")], "unknown"),
    ([("Canal", "Sampler")], "unknown"),
])
def test_role_from_names(names, expected):
    assert guess_role(names).role == expected


def test_recording_folder_hint_and_mono():
    g = guess_role([("Canal", "Audio 3")], sample_path=r"C:\FL\Audio\Recorded\Rec 12.wav", channels=1)
    assert g.role == "vocal"
    assert any("enregistrements" in r for r in g.reasons)


def test_full_length_stereo_file_is_beat():
    g = guess_role([("Canal", "Audio 1")], channels=2, duration_s=170, project_duration_s=180)
    assert g.role == "beat"


def test_every_guess_has_reasons():
    assert guess_role([]).reasons


@pytest.mark.parametrize("internal,vst,expected", [
    ("Fruity Wrapper", "Auto-Tune Pro", "pitch_correction"),
    ("Fruity Wrapper", "Pro-Q 3", "eq"),
    ("Fruity parametric EQ 2", None, "eq"),
    ("Fruity Limiter", None, "compressor"),
    ("Fruity Reeverb 2", None, "reverb"),
    ("Fruity Delay 3", None, "delay"),
    ("Fruity Wrapper", "OTT", "compressor"),
    ("Fruity Wrapper", "FabFilter Pro-DS", "de_esser"),
    ("Soundgoodizer", None, "saturation"),
    ("Fruity Wrapper", "Valhalla VintageVerb", "reverb"),
    ("Fruity Wrapper", "Totally Unknown", "unknown"),
])
def test_plugin_categories(internal, vst, expected):
    assert categorize(PluginInfo(internal_name=internal, vst_name=vst)) == expected
