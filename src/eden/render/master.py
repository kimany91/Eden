"""Play Eden's mix through the project's own Master chain in FL Studio.

The user's mastering lives on FL Studio's Master insert. To keep it, Eden's
final mix (pre-master) is *re-injected*: in a temporary copy of the project, every
original source is muted and a new audio channel plays Eden's mix straight
into the Master; FL Studio renders that copy, Master chain and Master
automations included.

The new channel's exact gain in FL is measured once per project (calibration)
by re-injecting the pre-master render itself; Eden then compensates it, so
that "Eden at 0 %" through the Master gives back the original song.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from eden.flp.edit import FlpEditor
from eden.project.inspector import InspectionReport
from eden.project.model import MASTER_INSERT
from eden.render.fl_studio import RenderError, Renderer
from eden.render.verify import load

MIX_CHANNEL_NAME = "Eden - mix"


@dataclass
class Calibration:
    gain: float  # linear gain FL applies to the re-injected channel
    residual_db: float  # what remains after removing that gain, relative to the signal
    threshold_db: float
    passed: bool
    message: str


def reinjection_copy(
    original: bytes,
    report: InspectionReport,
    repairs: dict[int, str],
    mix_wav: Path,
    bypass_master_effects: bool,
) -> bytes:
    """Copy of the project where only ``mix_wav`` plays, into the Master."""
    info = sf.info(str(mix_wav))
    project = report.project
    if not project.tempo_bpm:
        raise RenderError("Tempo du projet inconnu : impossible de placer le mix dans la playlist")
    ed = FlpEditor(original)
    for ch, path in repairs.items():
        ed.set_sample_path(ch, path)
    for s in report.sources:
        ed.set_channel_enabled(s.channel, False)
    if bypass_master_effects:
        ed.set_insert_effects_enabled(MASTER_INSERT, False)
    new = ed.add_audio_channel(str(mix_wav), MIX_CHANNEL_NAME)
    ticks = math.ceil(info.duration * project.tempo_bpm / 60 * project.ppq) + 4 * project.ppq
    ed.add_playlist_clip(new, 0, ticks)
    return ed.to_bytes()


def _aligned(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = max(a.shape[0], b.shape[0])
    return (np.pad(a, ((0, n - a.shape[0]), (0, 0))), np.pad(b, ((0, n - b.shape[0]), (0, 0))))


def measure_gain(reference: Path, rendered: Path, threshold_db: float = -60.0) -> Calibration:
    ref, sr1 = load(reference)
    out, sr2 = load(rendered)
    if sr1 != sr2 or ref.shape[1] != out.shape[1]:
        return Calibration(1.0, math.inf, threshold_db, False,
                           "Format du rendu de contrôle différent de la référence")
    ref, out = _aligned(ref, out)
    energy = float(np.sum(ref * ref))
    if energy == 0:
        return Calibration(1.0, math.inf, threshold_db, False, "Référence silencieuse")
    gain = float(np.sum(ref * out) / energy)
    residual = out - gain * ref
    res = float(np.sqrt(np.mean(residual ** 2)))
    sig = float(np.sqrt(np.mean((gain * ref) ** 2)))
    rel = 20 * math.log10(res / sig) if res > 0 and sig > 0 else -math.inf
    passed = gain > 0 and rel <= threshold_db
    msg = (f"Réinjection dans le Master fiable (gain mesuré {20 * math.log10(gain):+.2f} dB, "
           f"écart {rel:.1f} dB)" if passed else
           f"La réinjection dans le Master n'est pas fidèle (écart {rel:.1f} dB) : le canal "
           "dupliqué modifie peut-être le son (enveloppe, hauteur, étirement…)")
    return Calibration(gain, rel, threshold_db, passed, msg)


def prepare_mix_for_master(mix: Path, calibration: Calibration, out: Path) -> Path:
    """Compensate the measured channel gain; written as 32-bit float (no clipping)."""
    data, sr = load(mix)
    sf.write(str(out), data / calibration.gain, sr, subtype="FLOAT")
    return out


def master_pass(
    original: bytes,
    report: InspectionReport,
    repairs: dict[int, str],
    mix_wav: Path,
    calibration: Calibration,
    work_dir: Path,
    renderer: Renderer,
    timeout_s: float,
    name: str = "master-pass",
) -> Path:
    """Render ``mix_wav`` (Eden's pre-master mix) through the project's Master."""
    if not calibration.passed:
        raise RenderError(calibration.message)
    work_dir.mkdir(parents=True, exist_ok=True)
    feed = prepare_mix_for_master(mix_wav, calibration, work_dir / f"{name}-entree.wav")
    copy = work_dir / f"{name}.flp"
    try:
        copy.write_bytes(reinjection_copy(original, report, repairs, feed, bypass_master_effects=False))
        produced = renderer.render(copy, timeout_s)
    finally:  # temporary files: only the rendered audio is kept
        copy.unlink(missing_ok=True)
        feed.unlink(missing_ok=True)
    target = work_dir / f"{name}.wav"
    if produced != target:
        if target.exists():
            target.unlink()
        produced.replace(target)
    return target
