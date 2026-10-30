"""Guess the role of each audio source (lead vocal, backs, ad-libs, beat...).

This is a transparent heuristic, not an oracle: every guess carries the
reasons that produced it and a confidence level. Nothing lets the user
override a guess yet: a track read wrong is renamed in FL Studio and the
project analysed again. Hints come from names (channel, mixer insert,
playlist track, file), the recording folder and basic audio properties.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from eden.project.listen import Heard

ROLE_LABELS_FR = {
    "lead_vocal": "Voix principale",
    "double": "Doublage",
    "back_vocal": "Back / chœurs",
    "adlib": "Ad-lib",
    "vocal": "Voix (type à confirmer)",
    "beat": "Instru (stéréo complète)",
    "drums": "Batterie / percussions",
    "bass": "Basse / 808",
    "music": "Élément musical",
    "fx": "Effet sonore / transition",
    "unknown": "Inconnu",
}

VOCAL_ROLES = {"lead_vocal", "double", "back_vocal", "adlib", "vocal"}

# (role, weight, regex) - patterns are matched on lower-cased names.
_NAME_RULES: list[tuple[str, int, str]] = [
    ("adlib", 5, r"ad[\s\-_.]?libs?|\badl\b|\badlb"),
    ("back_vocal", 4, r"\bbacks?\b|\bbv'?s?\b|backing|ch(oe|œ)urs?|choir|harmo"),
    ("double", 4, r"doubl|\bdbl\b|\bx2\b|\bstack|\bdub\b"),
    ("lead_vocal", 4, r"\blead\b|\bmain\b|principal|\blv\b|lead[\s_\-]?vo"),
    ("vocal", 3, r"\bvox\b|\bvoc|vocal|\bvoix\b|\bvoice|acap|a[\s_\-]?cappella|\btakes?\b|\bprises?\b"),
    ("vocal", 1, r"couplet|verse|refrain|\bhook\b|\bintro\b|\boutro\b|\bpont\b|bridge|\bcouplet"),
    ("beat", 5, r"\binstrus?\b|instrumental|\bbeat\b|type[\s_\-]?beat|\bprod\b|2[\s_\-]?track|\binst\b"),
    ("drums", 4, r"\bkick|snare|\bhh\b|hi[\s\-]?hat|\bhats?\b|\bclap|\bperc|\bdrums?\b|\brim\b|\bcrash"),
    ("bass", 4, r"\b808s?\b|\bbass\b|\bsub\b"),
    ("fx", 3, r"\bs?fx\b|riser|impact|sweep|transition|\bdown[\s\-]?lifter"),
    ("music", 2, r"\bpiano|guitar|guitare|\bsynth|\bpad\b|\bstrings?\b|\bkeys\b|\bmelod|\bloop\b|\bsample\b"),
]

_RECORDED_DIR = re.compile(r"[\\/](recorded|recordings|enregistrements?)[\\/]", re.I)
_RECORDED_FILE = re.compile(r"^(rec|recording|take|prise)\b", re.I)
# A take recorded in the DAW: "<project>_<date> <time>_<input>" ("lucki type beat - 'casino'_2026-10-25
# 15-45-47_VOICE"). Its start is the project's name (often the beat's), not what the take is.
_RECORDED_NAME = re.compile(r"^.*?[\s_\-]*\d{4}-\d{2}-\d{2}[\s_]\d{2}[-.:h]\d{2}(?:[-.:m]\d{2})?[\s_\-]*(.*)$")


@dataclass
class RoleGuess:
    role: str = "unknown"
    confidence: str = "faible"  # haute | moyenne | faible
    reasons: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return ROLE_LABELS_FR.get(self.role, self.role)

    @property
    def is_vocal(self) -> bool:
        return self.role in VOCAL_ROLES


def _score_name(name: str, origin: str, scores: dict[str, int], reasons: list[str]) -> None:
    lowered = name.lower().replace("_", " ")
    for role, weight, pattern in _NAME_RULES:
        if re.search(pattern, lowered):
            scores[role] = scores.get(role, 0) + weight
            reasons.append(f"{origin} « {name} » → {ROLE_LABELS_FR[role]}")


def guess_role(
    names: list[tuple[str, str]],
    sample_path: str | None = None,
    channels: int | None = None,
    duration_s: float | None = None,
    project_duration_s: float | None = None,
    heard: Heard | None = None,
) -> RoleGuess:
    """``names`` is a list of (origin, text), e.g. ("Insert", "Voix lead"). What the file sounds like
    (``heard``), when it is clear, says whether it is a voice, whatever its names: they then only say
    which voice or which instrument."""
    scores: dict[str, int] = {}
    reasons: list[str] = []
    recorded = False
    for origin, text in names:
        take = _RECORDED_NAME.match(text or "")
        if take:
            recorded = True
            text = take.group(1)
        if text:
            _score_name(text, origin, scores, reasons)
    if recorded:
        scores["vocal"] = scores.get("vocal", 0) + 2
        reasons.append("Prise enregistrée (date et heure dans son nom ; le début du nom est celui du projet)")

    if sample_path:
        if _RECORDED_DIR.search(sample_path):
            scores["vocal"] = scores.get("vocal", 0) + 2
            reasons.append("Fichier situé dans un dossier d'enregistrements")
        base = re.split(r"[\\/]", sample_path)[-1]
        if _RECORDED_FILE.search(base):
            scores["vocal"] = scores.get("vocal", 0) + 1
            reasons.append(f"Nom de fichier de prise « {base} »")

    if channels == 2 and duration_s and project_duration_s and project_duration_s > 30:
        if duration_s >= 0.8 * project_duration_s and not any(r in scores for r in VOCAL_ROLES):
            scores["beat"] = scores.get("beat", 0) + 2
            reasons.append("Fichier stéréo couvrant presque tout le morceau")
    if channels == 1 and scores.get("vocal"):
        scores["vocal"] += 1
        reasons.append("Fichier mono (typique d'une prise de voix)")

    if heard is not None and heard.kind != "unsure":
        return _as_heard(heard, scores, reasons, channels, duration_s, project_duration_s)
    if not scores:
        return RoleGuess(reasons=["Aucun indice exploitable dans les noms ou le fichier"])

    # Specific vocal roles win over the generic "vocal" bucket when present.
    specific = {r: s for r, s in scores.items() if r in VOCAL_ROLES and r != "vocal"}
    total_vocal = sum(s for r, s in scores.items() if r in VOCAL_ROLES)
    best_other = max((s for r, s in scores.items() if r not in VOCAL_ROLES), default=0)
    if total_vocal and total_vocal >= best_other:
        role = max(specific, key=specific.get) if specific else "vocal"
        top = total_vocal
        runner_up = best_other
    else:
        role = max((r for r in scores if r not in VOCAL_ROLES), key=scores.get)
        top = scores[role]
        runner_up = max([total_vocal] + [s for r, s in scores.items()
                                          if r not in VOCAL_ROLES and r != role])

    if top >= 6 and top - runner_up >= 3:
        confidence = "haute"
    elif top >= 3 and top > runner_up:
        confidence = "moyenne"
    else:
        confidence = "faible"
    return RoleGuess(role=role, confidence=confidence, reasons=reasons, scores=scores)


def _as_heard(heard: Heard, scores: dict[str, int], reasons: list[str], channels: int | None,
              duration_s: float | None, project_duration_s: float | None) -> RoleGuess:
    """The family the file sounds like (voice or instrument), the role within it its names give."""
    voice = heard.kind == "voice"
    family = {r: s for r, s in scores.items() if (r in VOCAL_ROLES) == voice}
    if voice:
        specific = {r: s for r, s in family.items() if r != "vocal"}
        role = max(specific, key=specific.get) if specific else "vocal"
    elif family:
        role = max(family, key=family.get)
    elif channels == 2 and duration_s and project_duration_s and duration_s >= 0.8 * project_duration_s:
        role = "beat"
    else:
        role = "bass" if heard.sub_share >= 0.4 else "music"
    reasons = [*reasons, heard.reason]
    if any((r in VOCAL_ROLES) != voice for r in scores):
        reasons.append("le son l'emporte sur le nom")
    return RoleGuess(role, "haute" if family else "moyenne", reasons, scores)

