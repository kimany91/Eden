"""Checks on rendered audio, including the null test.

The null test proves that the stems Eden will mix reproduce the project:
sum(stems) must equal the pre-master render, sample for sample, within a
threshold (default −60 dB of residual relative to the reference).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

SILENCE_DB = -90.0
TAIL_DB = -60.0  # level above which the very end of a render is considered still sounding
TAIL_S = 0.05


def _db(x: float) -> float:
    return float(20 * np.log10(x)) if x > 0 else float("-inf")


@dataclass
class AudioCheck:
    path: str
    sample_rate: int
    channels: int
    frames: int
    duration_s: float
    subtype: str
    peak_db: float
    rms_db: float
    silent: bool
    clipped_samples: int  # samples at or above full scale (integer formats clip there)
    ends_with_sound: bool  # still sounding at the last sample: an echo/reverb tail may be cut


def load(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    return data, sr


def check_audio(path: Path) -> AudioCheck:
    info = sf.info(str(path))
    data, sr = load(path)
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    rms = float(np.sqrt(np.mean(data ** 2))) if data.size else 0.0
    end = data[-max(1, int(TAIL_S * sr)):]
    end_peak = float(np.max(np.abs(end))) if end.size else 0.0
    return AudioCheck(
        path=str(path), sample_rate=sr, channels=data.shape[1], frames=data.shape[0],
        duration_s=data.shape[0] / sr if sr else 0.0, subtype=str(info.subtype),
        peak_db=_db(peak), rms_db=_db(rms), silent=_db(peak) < SILENCE_DB,
        clipped_samples=int(np.count_nonzero(np.abs(data) >= 0.99999)),
        ends_with_sound=_db(end_peak) > TAIL_DB,
    )


@dataclass
class NullTest:
    passed: bool
    residual_db: float  # residual RMS relative to reference RMS
    residual_peak_db: float  # residual peak relative to reference peak
    threshold_db: float
    length_difference_s: float
    message: str


def null_test(reference: Path, stems: list[Path], threshold_db: float = -60.0) -> NullTest:
    ref, sr = load(reference)
    total = np.zeros_like(ref)
    longest = ref.shape[0]
    for stem in stems:
        data, s_sr = load(stem)
        if s_sr != sr:
            return NullTest(False, float("inf"), float("inf"), threshold_db, 0.0,
                            f"{stem.name} : {s_sr} Hz au lieu de {sr} Hz")
        if data.shape[1] != ref.shape[1]:
            return NullTest(False, float("inf"), float("inf"), threshold_db, 0.0,
                            f"{stem.name} : {data.shape[1]} canaux au lieu de {ref.shape[1]}")
        longest = max(longest, data.shape[0])
        if data.shape[0] > total.shape[0]:
            total = np.pad(total, ((0, data.shape[0] - total.shape[0]), (0, 0)))
        total[: data.shape[0]] += data
    if total.shape[0] < longest:
        total = np.pad(total, ((0, longest - total.shape[0]), (0, 0)))
    ref_padded = np.pad(ref, ((0, longest - ref.shape[0]), (0, 0)))
    residual = ref_padded - total

    ref_rms = float(np.sqrt(np.mean(ref_padded ** 2)))
    if ref_rms == 0:
        return NullTest(False, float("inf"), float("inf"), threshold_db, 0.0,
                        "La référence est silencieuse : test impossible")
    res_rms = float(np.sqrt(np.mean(residual ** 2)))
    rel = _db(res_rms) - _db(ref_rms) if res_rms > 0 else float("-inf")
    rel_peak = (_db(float(np.max(np.abs(residual)))) - _db(float(np.max(np.abs(ref_padded))))
                if res_rms > 0 else float("-inf"))
    diff_s = (longest - ref.shape[0]) / sr
    passed = rel <= threshold_db
    msg = (f"Somme des pistes = mix d'origine (écart {rel:.1f} dB)" if passed else
           f"La somme des pistes diffère du mix d'origine (écart {rel:.1f} dB, seuil "
           f"{threshold_db:.0f} dB)")
    return NullTest(passed, rel, rel_peak, threshold_db, diff_s, msg)
