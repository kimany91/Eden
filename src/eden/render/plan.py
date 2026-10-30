"""Decide which renders Eden asks FL Studio for.

Each render is a *copy* of the project in which some channels are muted, some
sends cut and some effects bypassed; a Mixer track is never switched off, which
FL Studio 2025/2026 cannot render (seen on a user's project: FL closed without
a file). Kinds of jobs:

* ``original``  – the project as it is (what the user hears in FL Studio);
* ``premaster`` – same, Master effects bypassed: reference of the null test;
* ``stem``      – one top-level group (an insert routed straight to the
  Master with everything feeding it, or a channel playing directly into the
  Master): every other channel is muted, and the sends of the group's
  inserts that bypass it are cut, so their sum equals ``premaster``: each
  source is counted once, bus processing is kept, Master effects are left to
  Eden's finishing;
* ``vocal``     – one voice alone, through its whole real chain (inserts,
  buses), for analysis and per-voice decisions. Not part of the sum. A voice
  is every vocal channel of one Mixer track (or played straight into the
  Master) with one role: the audio files of a track go through its effects
  together, as they do in the song, and cost one render, not one each;
* ``vocal_dry`` – the same voice without its FL reverbs and delays: its
  effect returns (inserts holding a reverb or delay that the voice does not
  need to reach the Master) have their outputs cut and the reverb or delay slots on its
  own way to the Master are bypassed. Only planned when every such effect
  can be removed; otherwise a note says why. Auto-Tune and every other
  effect stay. ``vocal`` minus ``vocal_dry`` is what those effects add, so
  Eden can process the dry voice like a mix engineer does and put the
  user's effects back untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from eden.project.inspector import SPACE_CATEGORIES, ExistingEffect, InspectionReport, SourceAnalysis
from eden.project.model import MASTER_INSERT, FlpProject

MAX_VOCAL_JOBS = 16
# Effects found on vocal buses and on effect returns alike: they tell neither from the other.
NEUTRAL_CATEGORIES = {"eq", "utility", "unknown"}


@dataclass
class RenderJob:
    name: str
    kind: str  # original | premaster | stem | vocal | vocal_dry
    description: str
    mute_channels: list[int] = field(default_factory=list)
    cut_routes: list[tuple[int, int]] = field(default_factory=list)  # (from insert, to insert)
    bypass_slots: list[tuple[int, int]] = field(default_factory=list)  # (insert, slot)
    # the Master's effects switch: only for an effect of it whose own on/off state FL did not record
    bypass_master_switch: bool = False
    channels: list[int] = field(default_factory=list)  # sources audible in this render


@dataclass
class RenderPlan:
    jobs: list[RenderJob]
    notes: list[str] = field(default_factory=list)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()[:40] or "piste"


def _upstream(project: FlpProject, target: int) -> set[int]:
    """Inserts whose audible routes reach ``target`` (directly or through buses)."""
    feeds: dict[int, set[int]] = {}
    for ins in project.inserts:
        for r in ins.routes:
            if r.audible:
                feeds.setdefault(r.target, set()).add(ins.index)
    found: set[int] = set()
    stack = [target]
    while stack:
        for src in feeds.get(stack.pop(), ()):
            if src not in found and src != target:
                found.add(src)
                stack.append(src)
    return found


def _reaches_master(project: FlpProject, start: int, excluded: set[int]) -> bool:
    seen: set[int] = set()
    stack = [start]
    while stack:
        idx = stack.pop()
        if idx == MASTER_INSERT:
            return True
        ins = project.insert(idx)
        if idx in seen or idx in excluded or ins is None or ins.enabled is False:
            continue
        seen.add(idx)
        stack.extend(r.target for r in ins.routes if r.audible)
    return False


def _return_like(space: list[ExistingEffect], effects: list[ExistingEffect], idx: int) -> bool:
    """Whether the first active effect of insert ``idx`` that tells a return from a bus is its
    reverb or delay. A vocal bus starts with its dynamics (compressor, de-esser, saturation…)."""
    for e in sorted((e for e in effects if e.insert == idx and e.active), key=lambda e: e.slot):
        if e in space:
            return True
        if e.category not in NEUTRAL_CATEGORIES:
            return False
    return False


def _dry_edits(project: FlpProject, s: SourceAnalysis) -> tuple[list[int], list[tuple[int, int]], str | None]:
    """Effect returns to silence and slots to bypass to hear ``s`` without its reverbs and delays,
    and why that would leave some of them in (None when it removes them all).

    A return is told by the mixer's topology, not by what it holds: an insert
    other than the voice's own, with a reverb or delay on it, that the voice
    does not need to reach the Master. Whatever else is on it (a limiter
    ducking the reverb, an EQ…) only shapes the effect, so the whole insert
    is muted. When the voice can do without each of these inserts but not
    without all of them (a vocal bus with an in-line delay next to a reverb
    return), the ones whose first effect is the reverb or delay are the
    returns and the others are the voice's way, whatever their numbers; when
    that does not settle it, nothing is planned. On the voice's own way to
    the Master, reverb and delay slots are bypassed one by one — when FL
    stored their state.
    """
    space = s.space_effects
    if not space:
        return [], [], None
    holders = {e.insert for e in space if e.insert != s.insert}
    returns = {h for h in holders if _reaches_master(project, s.insert, {h})}
    if not _reaches_master(project, s.insert, returns):  # they are alternative ways to the Master
        branches = returns
        returns = {h for h in branches if _return_like(space, s.existing_effects, h)}
        if not returns or not _reaches_master(project, s.insert, returns):
            names = ", ".join(f"« {project.insert(h).label} »" for h in sorted(branches))
            return [], [], (f"elle atteint le Master par plusieurs inserts avec reverb ou delay ({names}) "
                            "sans qu'Eden puisse dire lesquels sont des retours d'effet")
    slots = []
    left_in = None
    for e in space:
        if e.insert in returns:
            continue
        ins = project.insert(e.insert)
        slot = next((sl for sl in ins.slots if sl.index == e.slot), None) if ins else None
        if e.category not in SPACE_CATEGORIES:
            left_in = left_in or (f"« {e.plugin} » (insert « {e.insert_label} »), non identifié, "
                                  "est sur son chemin vers le Master")
        elif slot is not None and slot.enabled is not None:  # FL stored its state: it can be bypassed
            slots.append((e.insert, e.slot))
        else:
            left_in = left_in or (f"FL n'a pas enregistré l'état activé/désactivé de « {e.plugin} » "
                                  f"(insert « {e.insert_label} »)")
    return sorted(returns), slots, left_in


def _voices(project: FlpProject, vocal: list[SourceAnalysis]) -> list[tuple[list[SourceAnalysis], tuple]]:
    """Vocal channels rendered together, with how their reverbs and delays come off: those on one
    Mixer track (or played straight into the Master) with one role, Eden mixing them the same way,
    whose reverbs and delays come off the same way."""
    voices: dict[tuple, list[SourceAnalysis]] = {}
    for s in vocal:
        track = MASTER_INSERT if s.insert is None else s.insert
        returns, slots, left_in = _dry_edits(project, s)
        voices.setdefault((track, s.role.role, (tuple(returns), tuple(slots), left_in)), []).append(s)
    return [(members, dry) for (_, _, dry), members in voices.items()]


def voice_title(project: FlpProject, members: list[SourceAnalysis]) -> str:
    """How a voice is called: its channel, or its Mixer track (or role) and how many audio files it holds."""
    s = members[0]
    if len(members) == 1:
        return s.label
    ins = project.insert(s.insert) if s.insert not in (None, MASTER_INSERT) else None
    return f"{ins.label if ins else s.role.label.capitalize()} ({len(members)} fichiers)"


def _voice_name(members: list[SourceAnalysis]) -> str:
    s = members[0]
    if len(members) == 1:
        return f"ch{s.channel:03d}-{_slug(s.label)}"
    track = "master" if s.insert in (None, MASTER_INSERT) else f"ins{s.insert:03d}"
    return f"{track}-{_slug(s.role.role)}"


def plan_renders(report: InspectionReport) -> RenderPlan:
    project = report.project
    sources = [s for s in report.sources if s.reaches_master]
    notes: list[str] = []
    for s in report.sources:
        if not s.reaches_master:
            notes.append(f"« {s.label} » n'atteint pas le Master : absent du mix, ignoré")

    source_channels = sorted(s.channel for s in sources)
    voices = _voices(project, [s for s in sources if s.role.is_vocal])
    # played straight into the Master: each source a stem of its own, a voice of several files one stem
    direct = sorted([[s] for s in sources if s.insert in (None, MASTER_INSERT) and not s.role.is_vocal]
                    + [members for members, _ in voices if members[0].insert in (None, MASTER_INSERT)],
                    key=lambda members: members[0].channel)
    # every channel that can sound: a part is played alone by muting all the others (read as playing nowhere
    # included: if one plays after all, it stays out of the parts and is heard in the rest of the mix)
    sounding = sorted({s.channel for s in report.sources} | set(report.idle_channels))

    def all_but(kept: set[int]) -> list[int]:
        return [c for c in sounding if c not in kept]

    # the Master's effects, bypassed one by one where FL recorded their state (as a voice's reverb is)
    master = project.insert(MASTER_INSERT)
    master_fx = [sl for sl in (master.slots if master else []) if sl.enabled is not False]
    no_master = {"bypass_slots": [(MASTER_INSERT, sl.index) for sl in master_fx if sl.enabled is not None],
                 "bypass_master_switch": any(sl.enabled is None for sl in master_fx)}

    jobs = [
        RenderJob("original", "original", "Projet complet tel quel (référence d'écoute)",
                  channels=source_channels),
        RenderJob("premaster", "premaster", "Projet complet, effets du Master contournés",
                  channels=source_channels, **no_master),
    ]

    # Top-level groups: inserts routed straight to the Master that carry a source.
    top_level: dict[int, list[SourceAnalysis]] = {}
    for s in sources:
        if s.insert in (None, MASTER_INSERT):
            continue
        # signal_path ends with ..., <top-level insert>, 0
        path = [i for i in s.signal_path if i != MASTER_INSERT]
        for idx in path:
            ins = project.insert(idx)
            if ins and any(r.target == MASTER_INSERT and r.audible for r in ins.routes):
                top_level.setdefault(idx, []).append(s)

    for idx in sorted(top_level):
        keep = {idx} | _upstream(project, idx)
        cut = []
        for u in sorted(keep):  # the group reaches the Master through idx only
            src = project.insert(u)
            cut.extend((u, r.target) for r in (src.routes if src else [])
                       if r.target not in keep and (u != idx or r.target != MASTER_INSERT))
        ins = project.insert(idx)
        members = sorted({s.channel for s in top_level[idx]})
        # what plays: every source on an insert that feeds the group, sends included (an 808 sent to the vocal
        # bus is heard there; its own way to the Master is cut)
        feeding = {s.channel for s in sources if s.insert in keep}
        jobs.append(RenderJob(
            name=f"stem-{idx:03d}-{_slug(ins.label if ins else str(idx))}",
            kind="stem",
            description=f"Groupe {ins.label if ins else idx} : "
                        + ", ".join(s.label for s in top_level[idx]),
            mute_channels=all_but(feeding),
            cut_routes=cut,
            channels=members,
            **no_master,
        ))

    for members in direct:
        title = voice_title(project, members)
        jobs.append(RenderJob(
            name=f"stem-{_voice_name(members)}",
            kind="stem",
            description=f"{title} (joué{'s' if len(members) > 1 else ''} directement dans le Master)",
            mute_channels=all_but({s.channel for s in members}),
            channels=[s.channel for s in members],
            **no_master,
        ))

    if len(voices) > MAX_VOCAL_JOBS:
        notes.append(f"{len(voices)} voix détectées : rendu individuel limité aux "
                     f"{MAX_VOCAL_JOBS} premières")
        voices = voices[:MAX_VOCAL_JOBS]
    guessed: set[tuple[int, int]] = set()  # (insert, slot) of unidentified plugins taken for space effects
    for members, (returns, slots, left_in) in voices:
        s, title, name = members[0], voice_title(project, members), _voice_name(members)
        alone = len(members) == 1
        channels = [m.channel for m in members]
        others = all_but(set(channels))
        jobs.append(RenderJob(
            name=f"vocal-{name}",
            kind="vocal",
            description=(f"{title} seule ({s.role.label}), avec toute sa chaîne d'effets" if alone else
                         f"{title} ({s.role.label}) ensemble, avec toute leur chaîne d'effets"),
            mute_channels=others,
            channels=channels,
            **no_master,
        ))
        for e in s.space_effects:
            if e.category not in SPACE_CATEGORIES and (e.insert, e.slot) not in guessed:
                guessed.add((e.insert, e.slot))
                notes.append(f"« {e.plugin} » (insert « {e.insert_label} ») : plugin non identifié, "
                             "compté comme reverb ou delay d'après le nom de l'insert")
        if left_in:  # a half-dry render would pass for dry
            notes.append(f"« {title} » : pas de voix sèche, {left_in} ; ses reverbs et delays FL "
                         "seront traités avec prudence au mixage")
        elif returns or slots:
            silenced = [(r, route.target) for r in returns for route in project.insert(r).routes]
            jobs.append(RenderJob(
                name=f"dry-{name}",
                kind="vocal_dry",
                description=f"{title} sans {'ses' if alone else 'leurs'} reverbs et delays FL (voix sèche)",
                mute_channels=others,
                cut_routes=silenced,  # nothing of the returns reaches the Master
                bypass_slots=list(slots) + no_master["bypass_slots"],
                bypass_master_switch=no_master["bypass_master_switch"],
                channels=channels,
            ))

    overlap = {}
    for job in jobs:
        if job.kind == "stem":
            for c in job.channels:
                overlap.setdefault(c, []).append(job.name)
    for c, names in overlap.items():
        if len(names) > 1:
            ch = project.channel(c)
            notes.append(f"« {ch.label if ch else c} » est envoyé vers plusieurs groupes "
                         f"({', '.join(names)}) : chaque groupe garde sa part")
    return RenderPlan(jobs=jobs, notes=notes)
