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
  (inserts, buses), for analysis and per-voice decisions. Not part of the sum.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from eden.project.inspector import InspectionReport, SourceAnalysis
from eden.project.model import MASTER_INSERT, FlpProject

MAX_VOCAL_JOBS = 16


@dataclass
class RenderJob:
    name: str
    kind: str  # original | premaster | stem | vocal
    description: str
    mute_inserts: list[int] = field(default_factory=list)
    mute_channels: list[int] = field(default_factory=list)
    cut_routes: list[tuple[int, int]] = field(default_factory=list)  # (from insert, to insert)
    bypass_master_effects: bool = False
    channels: list[int] = field(default_factory=list)  # sources audible in this render


@dataclass
class RenderPlan:
    jobs: list[RenderJob]
    notes: list[str] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[RenderJob]:
        return [j for j in self.jobs if j.kind == kind]


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
        jobs.append(RenderJob(
            name=f"vocal-ch{s.channel:03d}-{_slug(s.label)}",
            kind="vocal",
            description=f"{s.label} seule ({s.role.label}), avec toute sa chaîne d'effets",
            mute_channels=[c for c in source_channels if c != s.channel],
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
