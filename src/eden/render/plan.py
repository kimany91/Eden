"""Decide which renders Eden asks FL Studio for.

Each render is a *copy* of the project in which some inserts or channels are
muted. Three kinds of jobs:

* ``original``  – the project as it is (what the user hears in FL Studio);
* ``premaster`` – same, Master effects bypassed: reference of the null test;
* ``stem``      – one top-level group (an insert routed straight to the
  Master with everything feeding it, or a channel playing directly into the
  Master). Routes of the feeding inserts that bypass the group are cut, so
  their sum equals ``premaster``: each source is counted once, bus
  processing is kept, Master effects are left to Eden's finishing;
* ``vocal``     – one vocal channel alone, through its whole real chain
  (inserts, buses), for analysis and per-voice decisions. Not part of the sum;
* ``vocal_dry`` – the same voice without its FL reverbs and delays: its
  effect returns (inserts holding a reverb or delay that the voice does not
  need to reach the Master) are muted and the reverb or delay slots on its
  own way to the Master are bypassed. Only planned when every such effect
  can be removed. Auto-Tune and every other effect stay. ``vocal`` minus
  ``vocal_dry`` is what those effects add, so Eden can process the dry voice
  like a mix engineer does and put the user's effects back untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from eden.project.inspector import InspectionReport, SourceAnalysis
from eden.project.model import MASTER_INSERT, FlpProject

MAX_VOCAL_JOBS = 16
SPACE_CATEGORIES = {"reverb", "delay"}


@dataclass
class RenderJob:
    name: str
    kind: str  # original | premaster | stem | vocal | vocal_dry
    description: str
    mute_inserts: list[int] = field(default_factory=list)
    mute_channels: list[int] = field(default_factory=list)
    cut_routes: list[tuple[int, int]] = field(default_factory=list)  # (from insert, to insert)
    bypass_slots: list[tuple[int, int]] = field(default_factory=list)  # (insert, slot)
    bypass_master_effects: bool = False
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


def _dry_edits(project: FlpProject, s: SourceAnalysis) -> tuple[list[int], list[tuple[int, int]], bool]:
    """Effect returns to mute and slots to bypass to hear ``s`` without its reverbs and delays,
    and whether that removes all of them.

    A return is told by the mixer's topology, not by what it holds: an insert
    other than the voice's own, with a reverb or delay on it, that the voice
    does not need to reach the Master. Whatever else is on it (a limiter
    ducking the reverb, an EQ…) only shapes the effect, so the whole insert
    is muted. On the voice's own way to the Master, reverb and delay slots
    are bypassed one by one — when FL stored their state.
    """
    if s.insert in (None, MASTER_INSERT):
        return [], [], False
    active = [e for e in s.existing_effects if e.active and e.insert != MASTER_INSERT]
    holders = sorted({e.insert for e in active if e.category in SPACE_CATEGORIES})
    returns: set[int] = set()
    for idx in holders:
        if idx != s.insert and _reaches_master(project, s.insert, returns | {idx}):
            returns.add(idx)
    slots = []
    complete = True
    for e in active:
        if e.category in SPACE_CATEGORIES and e.insert not in returns:
            ins = project.insert(e.insert)
            slot = next((sl for sl in ins.slots if sl.index == e.slot), None) if ins else None
            if slot is not None and slot.enabled is not None:  # FL stored its state: it can be bypassed
                slots.append((e.insert, e.slot))
            else:
                complete = False
    return sorted(returns), slots, complete


def plan_renders(report: InspectionReport) -> RenderPlan:
    project = report.project
    sources = [s for s in report.sources if s.reaches_master]
    notes: list[str] = []
    for s in report.sources:
        if not s.reaches_master:
            notes.append(f"« {s.label} » n'atteint pas le Master : absent du mix, ignoré")

    source_channels = sorted(s.channel for s in sources)
    direct = [s for s in sources if s.insert in (None, MASTER_INSERT)]
    direct_channels = [s.channel for s in direct]
    all_inserts = [i.index for i in project.inserts if i.index != MASTER_INSERT]

    jobs = [
        RenderJob("original", "original", "Projet complet tel quel (référence d'écoute)",
                  channels=source_channels),
        RenderJob("premaster", "premaster", "Projet complet, effets du Master contournés",
                  bypass_master_effects=True, channels=source_channels),
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
        for u in sorted(keep - {idx}):  # feeders must only reach the Master through idx
            src = project.insert(u)
            cut.extend((u, r.target) for r in (src.routes if src else []) if r.target not in keep)
        ins = project.insert(idx)
        members = sorted({s.channel for s in top_level[idx]})
        jobs.append(RenderJob(
            name=f"stem-{idx:03d}-{_slug(ins.label if ins else str(idx))}",
            kind="stem",
            description=f"Groupe {ins.label if ins else idx} : "
                        + ", ".join(s.label for s in top_level[idx]),
            mute_inserts=[i for i in all_inserts if i not in keep],
            mute_channels=direct_channels,
            cut_routes=cut,
            bypass_master_effects=True,
            channels=members,
        ))

    for s in direct:
        jobs.append(RenderJob(
            name=f"stem-ch{s.channel:03d}-{_slug(s.label)}",
            kind="stem",
            description=f"{s.label} (joué directement dans le Master)",
            mute_inserts=all_inserts,
            mute_channels=[c for c in direct_channels if c != s.channel],
            bypass_master_effects=True,
            channels=[s.channel],
        ))

    vocals = [s for s in sources if s.role.is_vocal]
    if len(vocals) > MAX_VOCAL_JOBS:
        notes.append(f"{len(vocals)} voix détectées : rendu individuel limité aux "
                     f"{MAX_VOCAL_JOBS} premières")
        vocals = vocals[:MAX_VOCAL_JOBS]
    for s in vocals:
        others = [c for c in source_channels if c != s.channel]
        jobs.append(RenderJob(
            name=f"vocal-ch{s.channel:03d}-{_slug(s.label)}",
            kind="vocal",
            description=f"{s.label} seule ({s.role.label}), avec toute sa chaîne d'effets",
            mute_channels=others,
            bypass_master_effects=True,
            channels=[s.channel],
        ))
        returns, slots, complete = _dry_edits(project, s)
        if (returns or slots) and complete:  # a half-dry render would pass for dry
            jobs.append(RenderJob(
                name=f"dry-ch{s.channel:03d}-{_slug(s.label)}",
                kind="vocal_dry",
                description=f"{s.label} sans ses reverbs et delays FL (voix sèche)",
                mute_inserts=returns,
                mute_channels=others,
                bypass_slots=slots,
                bypass_master_effects=True,
                channels=[s.channel],
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
