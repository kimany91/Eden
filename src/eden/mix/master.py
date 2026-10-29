"""Eden's mastering: a loud, clean rap master ready for the streaming platforms.

Chain (all offline, float64):

1. mono below 100 Hz when the sub is not already mono (club subs, phones
   and Bluetooth speakers are mono; stereo sub cancels and wastes headroom);
2. low-band control: a gentle compressor on the band below 100 Hz evens out
   808 notes (hearing is far less sensitive down there, so level differences
   sound bigger than they measure);
3. glue: slow bus compression, 1–2 dB, release on the felt beat;
4. loudness: gain, then an oversampled soft clipper that rounds the
   loudest peaks (what loud rap masters do to the drums), then a true-peak
   limiter at the ceiling. The gain is searched so the integrated
   loudness lands on the target while the limiter never reduces more than
   ``MAX_PEAK_REDUCTION_DB`` together with the clipper: when that budget is
   spent, the master stays a little quieter rather than squashed, and says so;
5. checks: integrated / short-term loudness, loudness range, true peak (the
   higher of the ideal 8× reading and a common 4× meter's: the ceiling holds
   for both), peak-to-loudness ratio, mono fold-down loss, and what each
   platform will do with the file (they turn loud masters down; nothing is
   gained above their reference, codec overshoot grows).

Targets (sources in docs/mixage.md): commercial rap charts sit around
−8 LUFS; Spotify asks for ≤ −2 dBTP when a master is louder than −14 LUFS;
a master denser than 8 dB peak-to-loudness gets −3 dBTP, because codec
overshoot at 96–128 kbit/s reaches 1.2–2.2 dB on such masters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import stft

from eden.mix import dsp, stereo
from eden.mix.limiter import gain_for, limit
from eden.mix.loudness import (integrated_loudness, loudness_range, sample_peak_db,
                               short_term_loudness, true_peak_db)
from eden.mix.riding import felt_quarter
from eden.mix.saturation import clip_curve, soft_clip
from eden.mix.treatments import Treatment, apply

TARGET_LUFS = -9.0  # "loud, like commercial rap": the user's choice
CEILING_DBTP = -2.0
DENSE_CEILING_DBTP = -3.0  # dense masters overshoot 1.2–2.2 dB through 96–128 kbit/s codecs
DENSE_PLR_DB = 8.0
MAX_PEAK_REDUCTION_DB = 9.0  # clipper + limiter; beyond this they are doing the drums' job
CLIP_DBFS = -1.0  # soft clipper knee region ends here (samples), before the limiter
LOW_HZ = 100.0
PLATFORMS = {  # reference loudness (LUFS) of the playback normalisation
    "Spotify": -14.0, "Apple Music": -16.0, "YouTube": -14.0, "Deezer": -15.0,
    "TIDAL": -14.0, "Amazon Music": -14.0, "SoundCloud": -14.0,
}


@dataclass
class PlatformPlayback:
    name: str
    reference_lufs: float
    gain_db: float  # what the platform applies (negative: turned down)
    heard_lufs: float


@dataclass
class MasterChecks:
    integrated_lufs: float
    short_term_max_lufs: float
    loudness_range_lu: float
    true_peak_dbtp: float
    sample_peak_dbfs: float
    plr_db: float  # true peak minus integrated loudness
    mono_loss_db: float
    low_correlation: float
    platforms: list[PlatformPlayback] = field(default_factory=list)
    mono_holes: list[str] = field(default_factory=list)  # bands that cancel when summed to mono


@dataclass
class MasterResult:
    audio: np.ndarray = field(repr=False)
    treatments: list[Treatment]
    gain_db: float
    clip_db: float  # how far the loudest sample was pushed into the clipper
    limiter_db: float  # maximum limiter reduction
    checks: MasterChecks
    warnings: list[str] = field(default_factory=list)


def mono_holes(x: np.ndarray, fs: float, min_s: float = 2.0) -> list[str]:
    """1/3-octave bands (100 Hz – 8 kHz) that lose more than 6 dB in a mono fold-down for at
    least ``min_s`` seconds while they carry a real part of the sound (1 % of the power of
    the whole band range at that moment): something there cancels on a phone or a mono speaker."""
    two_d = stereo.to_stereo(x)
    nper = 4096
    freqs, _, z = stft(two_d, fs=fs, nperseg=nper, noverlap=nper // 2, axis=0, boundary=None)
    left, right = np.abs(z[:, 0]) ** 2, np.abs(z[:, 1]) ** 2
    mono = np.abs(z[:, 0] + z[:, 1]) ** 2
    hop_s = nper / 2 / fs
    bands = []
    for i in range(-6, 14):  # 1/3-octave centres from 400 Hz · 2^(−6/3) to · 2^(13/3)
        fc = 400.0 * 2 ** (i / 3)
        if 100 <= fc <= 8000:
            sel = (freqs >= fc / 2 ** (1 / 6)) & (freqs < fc * 2 ** (1 / 6))
            bands.append((fc, (left[sel] + right[sel]).sum(axis=0), mono[sel].sum(axis=0)))
    total = sum(b[1] for b in bands)
    sounding = total > total.max() * 1e-4
    out = []
    for fc, stereo_p, mono_p in bands:
        heard = sounding & (stereo_p > 0.01 * total)
        with np.errstate(divide="ignore", invalid="ignore"):
            loss = 10 * np.log10(mono_p / (2 * stereo_p))
        if np.sum(heard & (loss < -6.0)) * hop_s >= min_s:
            out.append(f"{fc:.0f} Hz")
    return out


def checks(x: np.ndarray, fs: float) -> MasterChecks:
    integrated = integrated_loudness(x, fs)
    st = short_term_loudness(x, fs)
    st_max = float(np.max(st[np.isfinite(st)])) if st.size and np.isfinite(st).any() else -math.inf
    tp = true_peak_db(x, fs)
    m = stereo.measure(x, fs)
    platforms = []
    for name, ref in PLATFORMS.items():
        gain = min(0.0, ref - integrated) if math.isfinite(integrated) else 0.0
        if name == "Spotify" and math.isfinite(integrated) and integrated < ref:
            gain = max(0.0, min(ref - integrated, -1.0 - tp))  # raised, never above −1 dBTP, never lowered
        platforms.append(PlatformPlayback(name, ref, gain, integrated + gain))
    return MasterChecks(integrated, st_max, loudness_range(x, fs), tp, sample_peak_db(x),
                        tp - integrated if math.isfinite(integrated) else math.nan,
                        m.mono_loss_db, stereo.low_band_correlation(x, fs, LOW_HZ), platforms,
                        mono_holes(x, fs))


def _clip_dbfs(ceiling_dbtp: float) -> float:
    return CLIP_DBFS + (ceiling_dbtp - CEILING_DBTP)


def _loud_stage(x: np.ndarray, fs: float, gain_db: float, ceiling_dbtp: float
                ) -> tuple[np.ndarray, float, float]:
    """Gain → soft clip → limiter; returns (audio, clipper's peak reduction dB, limiter's dB)."""
    y = x * 10 ** (gain_db / 20)
    peak = sample_peak_db(y)
    clip_dbfs = _clip_dbfs(ceiling_dbtp)
    clipped = soft_clip(y, fs, 10 ** (clip_dbfs / 20)) if peak > clip_dbfs - 3.0 else y
    lim = limit(clipped, fs, ceiling_dbtp)
    return lim.audio, max(0.0, peak - sample_peak_db(clipped)), -lim.max_reduction_db


def _proxy_loudness(x: np.ndarray, fs: float, gain_db: float, ceiling_dbtp: float) -> float:
    """Loudness after gain → soft clip → the limiter's own gain law on the sample peaks, all at
    the base rate: a cheap stand-in for the real chain to aim the gain."""
    shaped = clip_curve(x * 10 ** (gain_db / 20), 10 ** (_clip_dbfs(ceiling_dbtp) / 20))
    peak = np.abs(shaped).max(axis=1) if shaped.ndim == 2 else np.abs(shaped)
    gain = gain_for(peak, fs, 10 ** (ceiling_dbtp / 20))
    return integrated_loudness(shaped * (gain[:, None] if shaped.ndim == 2 else gain), fs)


def _loudest(y: np.ndarray, fs: float, goal: float, ceiling_dbtp: float
             ) -> tuple[np.ndarray, float, float, float, bool]:
    """Gain landing on ``goal`` LUFS unless clipper + limiter would have to reduce more than
    ``MAX_PEAK_REDUCTION_DB``: (audio, gain, clip dB, limiter dB, stopped by that budget).

    The gain is aimed on the cheap proxy, then the real oversampled chain runs
    up to three times: each pass corrects the gain (secant step on the last two
    passes) and checks the budget on the reductions it really measured; a step
    stops at the edge of the budget (each dB of gain adds about a dB of peak
    reduction) rather than going over it and coming back."""
    gain = goal - integrated_loudness(y, fs)
    for _ in range(6):
        got = _proxy_loudness(y, fs, gain, ceiling_dbtp)
        if not math.isfinite(got) or abs(got - goal) < 0.05:
            break
        gain += goal - got
    capped = False
    tried: list[tuple[float, float]] = []
    for _ in range(3):
        out, clip_db, lim_db = _loud_stage(y, fs, gain, ceiling_dbtp)
        got = integrated_loudness(out, fs)
        over_budget = clip_db + lim_db - MAX_PEAK_REDUCTION_DB
        if over_budget > 0.1:
            gain -= over_budget  # each dB of gain adds about a dB of peak reduction
            capped = True
            continue
        if capped or not math.isfinite(got) or abs(got - goal) < 0.15:
            break
        tried.append((gain, got))
        slope = 1.0
        if len(tried) >= 2 and tried[-1][1] != tried[-2][1]:
            slope = (tried[-1][0] - tried[-2][0]) / (tried[-1][1] - tried[-2][1])
        step = (goal - got) * min(max(slope, 0.5), 3.0)
        room = -over_budget
        if step > room:
            capped = True
            if room < 0.05:
                break
            step = room
        gain += step
    else:
        out, clip_db, lim_db = _loud_stage(y, fs, gain, ceiling_dbtp)
    final = integrated_loudness(out, fs)
    return out, gain, clip_db, lim_db, capped and final < goal - 0.2


def _note_peaks_db(low: np.ndarray, fs: float) -> np.ndarray:
    """Peak level of each low-band note: 25 ms RMS envelope (no waveform ripple), one local
    maximum per 150 ms, within 30 dB of the loudest."""
    ms, size = dsp._frames(low, fs)
    if ms.size < 300:
        return np.zeros(0)
    env = 10 * np.log10(np.maximum(np.convolve(ms, np.ones(25) / 25, mode="same"), 1e-20))
    n = env.size // 150
    peaks = env[: n * 150].reshape(n, 150).max(axis=1)
    return peaks[peaks > peaks.max() - 30.0]


def master(x: np.ndarray, fs: float, k: float, tempo_bpm: float | None = None,
           target_lufs: float = TARGET_LUFS) -> MasterResult:
    """Master Eden's mix; at ``k`` = 0 the mix is returned unchanged (only measured)."""
    k = max(0.0, min(1.0, k))
    treatments: list[Treatment] = []
    warnings: list[str] = []
    if k <= 0:
        return MasterResult(x, [], 0.0, 0.0, 0.0, checks(x, fs), [])

    before = integrated_loudness(x, fs)
    if not math.isfinite(before):
        return MasterResult(x, [], 0.0, 0.0, 0.0, checks(x, fs), ["Mix silencieux : rien à masteriser"])
    goal = before + (target_lufs - before) * k  # from the mix as it came in: a tiny k changes little

    y = x
    corr = stereo.low_band_correlation(y, fs, LOW_HZ)
    if corr < 0.9:
        y = stereo.mono_below(y, fs, LOW_HZ)
        treatments.append(Treatment("mono_low", f"Graves en mono sous {LOW_HZ:.0f} Hz",
                                    f"Corrélation gauche/droite de {corr:+.2f} sous {LOW_HZ:.0f} Hz : le sub "
                                    "s'annulerait en partie sur une enceinte mono (club, téléphone, Bluetooth)"))

    # low-band control: even out uneven 808 notes (≤ 3 dB), transients kept (10 ms attack)
    low, high = dsp.split_band(y, fs, None, LOW_HZ)  # zero-phase: low + high == y exactly
    peaks = _note_peaks_db(low, fs)
    if peaks.size >= 4:
        spread = float(np.percentile(peaks, 90) - np.percentile(peaks, 10))
        if spread > 4.0:
            ratio = 1 + 1.0 * k
            slope = 1 - 1 / ratio
            t = Treatment("compressor", f"Tenue des graves {ratio:.1f}:1 sous {LOW_HZ:.0f} Hz",
                          f"Les notes graves varient de {spread:.0f} dB d'une note à l'autre (l'oreille y "
                          "entend chaque dB comme plus)",
                          {"threshold_db": float(np.percentile(peaks, 90)) - 1.5 * k / max(slope, 1e-6),
                           "ratio": ratio, "attack_ms": 10.0, "release_ms": 150.0, "max_reduction_db": 3.0 * k})
            low = apply(low, fs, [t])
            treatments.append(t)
            y = low + high

    # glue: slow, light bus compression with a release on the felt beat; the threshold sits 4 dB
    # under the loud passages and only the ratio follows the intensity (1.5 dB of reduction at 100 %)
    quarter = felt_quarter(tempo_bpm) if tempo_bpm else 0.5
    level, _ = dsp.band_levels_db(y, fs)
    loud = level[level > -80.0]
    if loud.size:
        ratio = 1 + 0.6 * k
        t = Treatment("compressor", f"Compression de bus {ratio:.2f}:1",
                      f"Cohésion : environ {4 * (1 - 1 / ratio):.1f} dB sur les passages forts, relâchement sur "
                      f"le temps ({quarter * 1000:.0f} ms)",
                      {"threshold_db": float(np.percentile(loud, 90)) - 4.0, "ratio": ratio,
                       "attack_ms": 30.0, "release_ms": quarter * 1000, "max_reduction_db": 3.0})
        y = apply(y, fs, [t])
        treatments.append(t)

    # loudness: at −9 LUFS a −2 dBTP ceiling leaves at most 7 dB of peak-to-loudness; under 8 dB,
    # Opus 96k / MP3 128k overshoot by 1.2–2.2 dB, so such a master gets −3 dBTP from the start
    ceiling = DENSE_CEILING_DBTP if CEILING_DBTP - goal < DENSE_PLR_DB else CEILING_DBTP
    out, gain, clip_db, lim_db, capped = _loudest(y, fs, goal, ceiling)
    if capped:
        warnings.append(f"Le morceau est masterisé à {integrated_loudness(out, fs):.1f} LUFS au lieu de "
                        f"{goal:.1f} : aller plus fort demanderait plus de {MAX_PEAK_REDUCTION_DB:.0f} dB "
                        "d'écrêtage et de limiteur, ce qui écraserait les percussions")
    reason = (f"Cible {goal:.1f} LUFS ; écrêtage doux : crêtes baissées de {clip_db:.1f} dB, puis limiteur "
              f"jusqu'à {lim_db:.1f} dB")
    if ceiling == DENSE_CEILING_DBTP:
        reason += (f" ; à ce volume, un plafond à {CEILING_DBTP:.0f} dBTP laisserait au plus "
                   f"{CEILING_DBTP - goal:.0f} dB entre crête et volume : sous 8 dB, l'encodage à bas débit "
                   f"dépasse de 1 à 2 dB, d'où {ceiling:.0f} dBTP")
    treatments.append(Treatment("loudness", f"Niveau final {gain:+.1f} dB, clip doux puis limiteur à {ceiling:.0f} dBTP",
                                reason, measured={"clip_db": clip_db, "limiter_db": lim_db, "ceiling_dbtp": ceiling}))
    c = checks(out, fs)
    if c.true_peak_dbtp > ceiling + 0.1:
        warnings.append(f"Crête réelle à {c.true_peak_dbtp:+.1f} dBTP au-dessus du plafond")
    if c.plr_db < 6.0:
        warnings.append(f"Rapport crête/volume de {c.plr_db:.1f} dB : master très dense, risque de distorsion "
                        "à l'encodage sur les débits bas")
    if c.mono_holes:
        warnings.append("Des éléments s'annulent en mono (téléphone, enceinte Bluetooth) vers "
                        + ", ".join(c.mono_holes) + " : un effet stéréo en opposition de phase dans l'instru ?")
    return MasterResult(out, treatments, gain, clip_db, lim_db, c, warnings)
