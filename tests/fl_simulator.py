"""Test double for FL Studio's command-line renderer (tests only).

Usage, like FL Studio:  python fl_simulator.py /R /Ewav <project.flp>
                    or  python fl_simulator.py /R /Ewav /F<folder>

It reads the project with Eden's parser and renders each channel (its audio
file when it has one, else a deterministic tone) through the mixer graph.
Channel volume is applied as raw/12800 (FL's default 10000 is not unity
gain). Insert enable/effects flags, slot bypass, routes, send levels and volumes are
honoured. A delay slot adds tempo-free echoes and a reverb slot a decaying tail (both
linear, dry signal kept, like a plugin with its own dry/wet mix); any other effect slot
applies a *non-linear* curve (like a compressor or saturation would), so a wrong stem
split fails the null test exactly as it would with real FL Studio.

Environment switches used by tests:
  EDEN_SIM_IGNORE_MUTE=1   behave as if FL ignored mute flags
  EDEN_SIM_NO_OUTPUT=1     exit without writing anything
  EDEN_SIM_ACCEPT=<flag>   only accept this syntax ("project" or "folder")
  EDEN_SIM_CUT_TAIL=1      stop exactly at the last clip (FL's "cut remainder"), instead
                           of leaving one second for echoes and reverbs to ring out
  EDEN_SIM_IGNORE_SLOTS=1  behave as if FL ignored the slot on/off records (a bypassed
                           effect still plays)
  EDEN_SIM_WET_REVERB=1    reverb slots give their tail only (100 % wet, as set on an
                           effect return)
  EDEN_SIM_RANDOM=1        reverb slots modulated at random, differently at each render (as some
                           plugins are, or a plugin in trial version): two renders of one project differ
  EDEN_SIM_PCM16=1         write 16-bit WAV files, which stop at full scale (FL's export set
                           to 16 bits), instead of 32-bit float
  EDEN_SIM_TRACE=<file>    each launch adds a line to <file>: when it started and ended
                           (JSON), and the projects it rendered
  EDEN_SIM_ALONE=<file>    behave like an FL Studio that will not start beside another one:
                           a launch while <file> exists (another one is rendering) renders
                           nothing and ends at once
"""

from __future__ import annotations

import json
import os
import sys
import time
from functools import cache
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eden.flp.parser import parse_bytes  # noqa: E402
from eden.project.plugins import categorize  # noqa: E402

SR = 22050


def channel_signal(index: int, frames: int) -> np.ndarray:
    t = np.arange(frames) / SR
    left = 0.2 * np.sin(2 * np.pi * (110 + 37 * index) * t)
    right = 0.2 * np.sin(2 * np.pi * (170 + 23 * index) * t + index)
    return np.stack([left, right], axis=1)


def shifted(x: np.ndarray, seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    return np.vstack([np.zeros((n, 2)), x[:-n]]) if n < x.shape[0] else np.zeros_like(x)


def effect(slot, x: np.ndarray) -> np.ndarray:
    category = categorize(slot.plugin)
    if category == "delay":
        return x + sum(0.5 ** k * shifted(x, 0.25 * k) for k in (1, 2, 3))
    if category == "reverb":
        tail = sum(0.3 * 0.7 ** k * shifted(x, 0.031 * k) for k in range(1, 12))
        if os.environ.get("EDEN_SIM_RANDOM") == "1":
            tail = tail * (1 + 0.6 * np.random.default_rng().standard_normal(x.shape[0]))[:, None]
        return tail if os.environ.get("EDEN_SIM_WET_REVERB") == "1" else x + tail
    return np.tanh(1.5 * x) / 1.5  # stands for any non-linear plugin


def render(project_path: Path) -> np.ndarray:
    p = parse_bytes(project_path.read_bytes())
    ignore_mute = os.environ.get("EDEN_SIM_IGNORE_MUTE") == "1"
    ignore_slots = os.environ.get("EDEN_SIM_IGNORE_SLOTS") == "1"
    end = max((c.position_ticks + c.length_ticks for a in p.arrangements for c in a.clips), default=0)
    remainder = 0.0 if os.environ.get("EDEN_SIM_CUT_TAIL") == "1" else 1.0
    frames = int(((p.ticks_to_seconds(end) or 2.0) + remainder) * SR)
    inserts = {i.index: i for i in p.inserts}

    def source(ch) -> np.ndarray:
        if ch.sample_path and Path(ch.sample_path).is_file():
            data, _ = sf.read(ch.sample_path, dtype="float64", always_2d=True)
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            data = data[:frames]
            return np.pad(data, ((0, frames - data.shape[0]), (0, 0)))
        return channel_signal(ch.index, frames)

    inputs: dict[int, np.ndarray] = {}
    for ch in p.channels:
        if ch.kind not in ("sampler", "instrument") or (ch.enabled is False and not ignore_mute):
            continue
        target = ch.insert or 0
        gain = (ch.volume_raw if ch.volume_raw is not None else 10000) / 12800
        inputs[target] = inputs.get(target, 0) + source(ch) * gain

    @cache
    def output(idx: int) -> np.ndarray:
        ins = inserts[idx]
        x = inputs.get(idx, np.zeros((frames, 2))).copy()
        for src in inserts.values():
            if src.index != idx and any(r.target == idx and r.audible for r in src.routes):
                level = next(r.level_raw for r in src.routes if r.target == idx)
                x = x + output(src.index) * (1.0 if level is None else level / 12800)
        if ins.enabled is False and not ignore_mute:
            return np.zeros((frames, 2))
        if ins.effects_enabled is not False:
            for slot in ins.slots:
                if slot.enabled is not False or ignore_slots:
                    x = effect(slot, x)
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
    alone = os.environ.get("EDEN_SIM_ALONE")
    if alone:
        try:
            os.close(os.open(alone, os.O_CREAT | os.O_EXCL))
        except FileExistsError:
            return 0
    start = time.time()
    try:
        for proj in projects:
            sf.write(proj.with_suffix(".wav"), render(proj), SR,
                     subtype="PCM_16" if os.environ.get("EDEN_SIM_PCM16") == "1" else "FLOAT")
        if alone:
            time.sleep(1.0)  # long enough for a launch beside this one to find it rendering
    finally:
        if alone:
            os.remove(alone)
    trace = os.environ.get("EDEN_SIM_TRACE")
    if trace:
        with open(trace, "a", encoding="utf-8") as f:
            f.write(json.dumps({"start": start, "end": time.time(), "projects": [p.stem for p in projects]}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
