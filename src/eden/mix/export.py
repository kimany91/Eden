"""Export of the final WAV: destination, name, sample rate and bit depth.

* the file is never written over an existing one unless asked;
* sample-rate conversion uses a high-quality polyphase filter, and only
  when another rate is requested (no needless conversion);
* 16-bit files get TPDF dither; 24-bit and 32-bit float are written as is;
* an integer file that would clip is refused (32-bit float keeps everything).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

BIT_DEPTHS = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}
SAMPLE_RATES = (44100, 48000, 88200, 96000)


class ExportError(RuntimeError):
    pass


@dataclass
class ExportResult:
    path: str
    sample_rate: int
    bit_depth: int
    resampled: bool
    dithered: bool


def export_wav(source: Path, destination: Path, sample_rate: int | None = None,
               bit_depth: int = 24, overwrite: bool = False) -> ExportResult:
    if bit_depth not in BIT_DEPTHS:
        raise ExportError(f"Profondeur de bits non prise en charge : {bit_depth}")
    destination = destination.with_suffix(".wav")
    if destination.exists() and not overwrite:
        raise ExportError(f"« {destination.name} » existe déjà dans ce dossier")
    if not destination.parent.is_dir():
        raise ExportError(f"Dossier introuvable : {destination.parent}")

    data, sr = sf.read(str(source), dtype="float64", always_2d=True)
    target_sr = sample_rate or sr
    resampled = target_sr != sr
    if resampled:
        ratio = Fraction(target_sr, sr).limit_denominator(1000)
        data = resample_poly(data, ratio.numerator, ratio.denominator, axis=0)

    dithered = False
    if bit_depth == 16:
        lsb = 1 / 32768
        rng = np.random.default_rng()
        data = data + (rng.random(data.shape) - rng.random(data.shape)) * lsb
        dithered = True
    if bit_depth != 32 and np.max(np.abs(data)) >= 1.0:
        raise ExportError(
            "Le morceau dépasse 0 dBFS : en 16 ou 24 bits il serait écrêté. Exportez en 32 bits "
            "flottant, ou baissez la sortie de ton Master dans FL Studio.")

    tmp = destination.with_name(destination.stem + ".eden-tmp.wav")
    sf.write(str(tmp), data, target_sr, subtype=BIT_DEPTHS[bit_depth])
    tmp.replace(destination)
    return ExportResult(str(destination), target_sr, bit_depth, resampled, dithered)
