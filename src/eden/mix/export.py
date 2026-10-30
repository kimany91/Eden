"""Export of the final WAV: destination, name, sample rate and bit depth.

* the file is never written over an existing one unless asked; ".wav" is
  added to the name typed, whatever dots it holds ("Vol. 2", "prod.");
* sample-rate conversion, only when another rate is requested, uses a
  polyphase filter flat to 91 % of the lower Nyquist frequency (20 kHz at
  44.1 kHz) with 100 dB of rejection above it. A conversion can raise the
  true peak a little (the waveform is rebuilt between new points): if it
  does, a true-peak limiter brings it back to the peak the file had;
* 16-bit files get TPDF dither; 24-bit and 32-bit float are written as is;
* an integer file that would clip is refused (32-bit float keeps everything).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import firwin, kaiserord, resample_poly

from eden.mix.limiter import limit
from eden.mix.loudness import true_peak_db

BIT_DEPTHS = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}
SAMPLE_RATES = (44100, 48000, 88200, 96000)
SRC_PASSBAND = 0.91  # flat up to this fraction of the lower Nyquist frequency
SRC_STOPBAND_DB = 100.0


class ExportError(RuntimeError):
    pass


@dataclass
class ExportResult:
    path: str
    sample_rate: int
    bit_depth: int
    resampled: bool
    dithered: bool
    true_peak_dbtp: float


def _src_filter(up: int, down: int) -> np.ndarray:
    """Low-pass for ``resample_poly`` (at ``up`` × the input rate): stop band from the lower
    Nyquist frequency, so nothing folds back into the audio band."""
    edge = 1.0 / max(up, down)  # the lower Nyquist frequency, relative to the upsampled one
    numtaps, beta = kaiserord(SRC_STOPBAND_DB, (1 - SRC_PASSBAND) * edge)
    return firwin(numtaps | 1, (1 + SRC_PASSBAND) / 2 * edge, window=("kaiser", beta))


def _one_of(values) -> str:
    *first, last = (str(v) for v in values)
    return f"{', '.join(first)} ou {last}"


def check_format(sample_rate: int | None, bit_depth: int) -> None:
    """Refuse a sample rate or a bit depth Eden does not export to (``None`` keeps FL Studio's rate)."""
    if bit_depth not in BIT_DEPTHS:
        raise ExportError(f"Profondeur de bits non prise en charge : {bit_depth} ({_one_of(BIT_DEPTHS)})")
    if sample_rate is not None and sample_rate not in SAMPLE_RATES:
        raise ExportError(f"Fréquence d'échantillonnage non prise en charge : {sample_rate} Hz "
                          f"({_one_of(SAMPLE_RATES)} Hz)")


def export_wav(source: Path, destination: Path, sample_rate: int | None = None,
               bit_depth: int = 24, overwrite: bool = False) -> ExportResult:
    check_format(sample_rate, bit_depth)
    if destination.suffix.lower() != ".wav":  # added, never replacing: "Beat v1.2 - Eden" keeps its ".2 - Eden"
        destination = destination.with_name(destination.name + ".wav")
    if destination.exists() and not overwrite:
        raise ExportError(f"« {destination.name} » existe déjà dans ce dossier")
    if not destination.parent.is_dir():
        raise ExportError(f"Dossier introuvable : {destination.parent}")

    data, sr = sf.read(str(source), dtype="float64", always_2d=True)
    target_sr = sample_rate or sr
    resampled = target_sr != sr
    if resampled:
        peak = true_peak_db(data, sr)
        ratio = Fraction(target_sr, sr).limit_denominator(1000)
        data = resample_poly(data, ratio.numerator, ratio.denominator, axis=0,
                             window=_src_filter(ratio.numerator, ratio.denominator))
        if true_peak_db(data, target_sr) > peak + 0.01:
            data = limit(data, target_sr, peak).audio

    dithered = False
    if bit_depth == 16:
        lsb = 1 / 32768
        rng = np.random.default_rng()
        data = data + (rng.random(data.shape) - rng.random(data.shape)) * lsb
        dithered = True
    if bit_depth != 32 and np.max(np.abs(data)) >= 1.0:
        raise ExportError(
            "Le morceau dépasse 0 dBFS : en 16 ou 24 bits il serait écrêté. Exporte-le en 32 bits "
            "flottant, ou mixe-le avec une intensité au-dessus de 0 % pour qu'Eden le masterise.")

    tmp = destination.with_name(destination.stem + ".eden-tmp.wav")
    sf.write(str(tmp), data, target_sr, subtype=BIT_DEPTHS[bit_depth])
    tmp.replace(destination)
    return ExportResult(str(destination), target_sr, bit_depth, resampled, dithered,
                        true_peak_db(data, target_sr))
