"""Test double for FL Studio's command-line renderer (tests only).

Usage, like FL Studio:  python fl_simulator.py /R /Ewav <project.flp>
                    or  python fl_simulator.py /R /Ewav /F<folder>

It reads the project with Eden's parser and renders a deterministic signal
per channel through the mixer graph: insert enable/effects flags, routes,
send levels and volumes are honoured, and any insert with effects applies a
*non-linear* curve (like a compressor or saturation would), so a wrong
stem split fails the null test exactly as it would with real FL Studio.

Environment switches used by tests:
  EDEN_SIM_IGNORE_MUTE=1   behave as if FL ignored mute flags
  EDEN_SIM_NO_OUTPUT=1     exit without writing anything
  EDEN_SIM_ACCEPT=<flag>   only accept this syntax ("project" or "folder")
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eden.flp.parser import parse_bytes  # noqa: E402

SR = 22050


def channel_signal(index: int, frames: int) -> np.ndarray:
    t = np.arange(frames) / SR
    left = 0.2 * np.sin(2 * np.pi * (110 + 37 * index) * t)
    right = 0.2 * np.sin(2 * np.pi * (170 + 23 * index) * t + index)
    return np.stack([left, right], axis=1)


def render(project_path: Path) -> np.ndarray:
    p = parse_bytes(project_path.read_bytes())
    ignore_mute = os.environ.get("EDEN_SIM_IGNORE_MUTE") == "1"
    end = max((c.position_ticks + c.length_ticks for a in p.arrangements for c in a.clips), default=0)
    frames = int((p.ticks_to_seconds(end) or 2.0) * SR) or SR
    inserts = {i.index: i for i in p.inserts}

    inputs: dict[int, np.ndarray] = {}
    for ch in p.channels:
        if ch.kind not in ("sampler", "instrument") or (ch.enabled is False and not ignore_mute):
            continue
        target = ch.insert or 0
        inputs[target] = inputs.get(target, 0) + channel_signal(ch.index, frames)

    @lru_cache(maxsize=None)
    def output(idx: int) -> np.ndarray:
        ins = inserts[idx]
        x = inputs.get(idx, np.zeros((frames, 2))).copy()
        for src in inserts.values():
            if src.index != idx and any(r.target == idx and r.audible for r in src.routes):
                level = next(r.level_raw for r in src.routes if r.target == idx)
                x = x + output(src.index) * (1.0 if level is None else level / 12800)
        if ins.enabled is False and not ignore_mute:
            return np.zeros((frames, 2))
        if ins.slots and ins.effects_enabled is not False:
            x = np.tanh(1.5 * x) / 1.5  # stands for any non-linear plugin
        return x * ((ins.volume_raw if ins.volume_raw is not None else 12800) / 12800)

    return output(0)


def main(argv: list[str]) -> int:
    if os.environ.get("EDEN_SIM_NO_OUTPUT") == "1":
        return 3
    accept = os.environ.get("EDEN_SIM_ACCEPT")
    projects: list[Path] = []
    for a in argv:
        if a.startswith("/F"):
            if accept == "project":
                return 4
            projects.extend(sorted(Path(a[2:]).glob("*.flp")))
        elif a.lower().endswith(".flp"):
            if accept == "folder":
                return 4
            projects.append(Path(a))
    if "/R" not in argv or not projects:
        return 2
    for proj in projects:
        sf.write(proj.with_suffix(".wav"), render(proj), SR, subtype="FLOAT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
