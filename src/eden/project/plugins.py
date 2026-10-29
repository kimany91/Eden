"""Classify known plugins by the kind of processing they apply.

Used to tell which treatments already exist in the signal path of a track,
so that Eden does not apply the same processing a second time. Matching is
done on the plugin name only: the parameters of third-party plugins are not
readable from the .flp (their state is an opaque blob).
"""

from __future__ import annotations

import re

from eden.project.model import PluginInfo

# Order matters: the first matching category wins.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("pitch_correction", (
        "auto-tune", "autotune", "auto tune", "waves tune", "melodyne", "newtone", "pitcher",
        "graillon", "mautopitch", "melda autopitch", "metatune", "nectar.*pitch", "revoice",
        "gsnap", "pitch correct",
    )),
    ("de_esser", ("de-?ess", "pro-ds", "sibilance")),
    ("reverb", (
        "reverb", "reeverb", "valhalla(?!.*delay)", "verb", "raum", "pro-r", "room", "plate",
        "convolver", "seventh heaven", "h-reverb", "blackhole", r"emt ?\d", "lexicon", r"\bpcm\b",
        "chamber", "shimmer", "spring", r"\brev\b", r"\bir-?1\b",
    )),
    ("delay", (
        "delay", "echo", "echoboy", "timeless", "h-delay", "manny marroquin delay", "primaltap",
        "supertap", "replika", "crystallizer", "tal-dub", "ohmboyz", "cla epic",
    )),
    ("compressor", (
        "compressor", "comp", "limiter", "cla-76", "cla-2a", "1176", "la-2a", "rcompressor",
        "pro-c", "pro-l", "maxim", "multiband", r"\bott\b", "vulf", "rvox", "renaissance vox",
        "fruity limiter", "dynamic", r"\bgate\b",
    )),
    ("eq", (r"\beq\b", r"\beq\d", "equali", "equo", "pro-q", "pultec", "filter", "fruity parametric")),
    ("saturation", (
        "satur", "dist", "decapitator", "soundgoodizer", "soft clipper", "clipper",
        "tape", "fresh air", "exciter", "waveshaper", "blood overdrive", "trash",
    )),
    ("stereo", ("stereo", "balance", "imager", "microshift", "doubler", "widen", "chorus")),
    ("utility", ("send", "notebook", "gain", "tuner", "spectroman", "wave candy", "analy",
                 "control surface", "patcher", "peak controller", "meter", "edison")),
]


def categorize(plugin: PluginInfo) -> str:
    names = " ".join(
        n.lower() for n in (plugin.vst_name, plugin.internal_name, plugin.display_name) if n
    )
    if plugin.internal_name == "Fruity Wrapper" and plugin.vst_name:
        names = " ".join(n.lower() for n in (plugin.vst_name, plugin.display_name) if n)
    for category, patterns in _RULES:
        for pat in patterns:
            if re.search(pat, names):
                return category
    return "unknown"


CATEGORY_LABELS_FR = {
    "pitch_correction": "Correction de hauteur",
    "de_esser": "De-esser",
    "reverb": "Reverb",
    "delay": "Delay",
    "compressor": "Compression / limiteur",
    "eq": "Égalisation / filtre",
    "saturation": "Saturation",
    "stereo": "Image stéréo",
    "utility": "Utilitaire",
    "unknown": "Non identifié",
}
