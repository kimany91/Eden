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
   loudness lands on the target while clipper and limiter together never
   reduce the song's recurring peaks by more than ``MAX_PEAK_REDUCTION_DB``
   (one isolated event may take ``SINGLE_PEAK_MARGIN_DB`` more): when that
   budget is spent, the master stays a little quieter rather than squashed,
   and says so;
5. checks: integrated / short-term loudness, loudness range, true peak (the
   higher of the continuous waveform's peak and libebur128's 4× reading:
   the ceiling holds for both), peak-to-loudness ratio, mono fold-down loss,
   and what each platform will do with the file (they turn loud masters
   down; nothing is gained above their reference, codec overshoot grows).

Targets (sources in docs/mixage.md): commercial rap charts sit around
−8 LUFS; Spotify asks for ≤ −2 dBTP when a master is louder than −14 LUFS;
a master denser than 8 dB peak-to-loudness gets −3 dBTP, because codec
overshoot at 96–128 kbit/s reaches 1.2–2.2 dB on such masters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.signal import find_peaks, get_window

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
MAX_PEAK_REDUCTION_DB = 9.0  # clipper + limiter on the recurring peaks; beyond this they do the drums' job
SINGLE_PEAK_MARGIN_DB = 4.0  # an isolated event (a hit at a drop) may take this much more over 30 ms
BUDGET_BLOCK_S = 0.05  # recurring peaks: reduction measured per 50 ms block...
BUDGET_PERCENTILE = 98.5  # ...this percentile of the reduced blocks...
BUDGET_RANK = 10  # ...but never above the 10th most reduced block: a few short events do not count
EVENT_BLOCK_S = 0.01  # isolated events: the reduction kept over three 10 ms blocks in a row
EVENT_BLOCKS = 3  # (30 ms: a click is shorter)
REAL_PASSES = 3  # full oversampled passes of the gain search (one more only if the last went over budget)
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
    """1/3-octave bands (100 Hz – 8 kHz) that lose more than 6 dB in a mono fold-down over at
    least ``min_s`` seconds while they carry a real part of the sound (1 % of the power of the
    whole band range over that time): something there cancels on a phone or a mono speaker.

    The powers are averaged over sliding ``min_s`` windows before the ratio is taken: a
    decorrelated (wide) element loses 3 dB on average, its frame-to-frame dips do not add up
    to a hole, while an element in opposite polarity on the two sides loses far more."""
    two_d = stereo.to_stereo(x)
    nper, hop = 4096, 2048
    if two_d.shape[0] < nper:
        return []
    freqs = np.fft.rfftfreq(nper, 1 / fs)
    centres = [400.0 * 2 ** (i / 3) for i in range(-6, 14)]  # from 400 Hz · 2^(−6/3) to · 2^(13/3)
    centres = [fc for fc in centres if 100 <= fc <= 8000]
    select = np.stack([(freqs >= fc / 2 ** (1 / 6)) & (freqs < fc * 2 ** (1 / 6)) for fc in centres],
                      axis=1).astype(np.float32)
    window = get_window("hann", nper).astype(np.float32)
    left = sliding_window_view(two_d[:, 0], nper)[::hop]
    right = sliding_window_view(two_d[:, 1], nper)[::hop]
    stereo_p = np.empty((left.shape[0], len(centres)))
    mono_p = np.empty_like(stereo_p)
    for start in range(0, left.shape[0], 256):  # a few MB at a time, in float32
        zl = np.fft.rfft(np.multiply(left[start:start + 256], window, dtype=np.float32), axis=1)
        zr = np.fft.rfft(np.multiply(right[start:start + 256], window, dtype=np.float32), axis=1)
        stereo_p[start:start + 256] = (np.abs(zl) ** 2 + np.abs(zr) ** 2) @ select
        mono_p[start:start + 256] = np.abs(zl + zr) ** 2 @ select
    size = max(1, int(round(min_s * fs / hop)))
    if stereo_p.shape[0] < size:
        return []

    def windows(power: np.ndarray) -> np.ndarray:  # sum over each run of ``size`` frames
        cumulative = np.concatenate([np.zeros((1,) + power.shape[1:]), np.cumsum(power, axis=0)])
        return cumulative[size:] - cumulative[:-size]

    stereo_w, mono_w = windows(stereo_p), windows(mono_p)
    total = stereo_w.sum(axis=1)
    sounding = total > total.max() * 1e-4
    out = []
    for b, fc in enumerate(centres):
        heard = sounding & (stereo_w[:, b] > 0.01 * total)
        with np.errstate(divide="ignore", invalid="ignore"):
            loss = 10 * np.log10(mono_w[:, b] / (2 * stereo_w[:, b]))
        if np.any(heard & (loss < -6.0)):
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


def _dense(level_lufs: float) -> bool:
    """At this loudness, a −2 dBTP ceiling would leave less than 8 dB between peak and loudness."""
    return CEILING_DBTP - level_lufs < DENSE_PLR_DB


@dataclass
class PeakReduction:
    """How hard clipper and limiter worked in one pass of the loudness stage."""
    clip_db: float  # how far the loudest sample was pushed into the clipper
    limiter_db: float  # the limiter's largest reduction
    recurring_db: float  # both together on the song's recurring peaks (the budget)
    single_db: float  # both together on the most reduced 30 ms, all of it
    single_at_s: float  # where those 30 ms start

    @property
    def over_db(self) -> float:
        """How far the budget is exceeded (negative: the room left)."""
        return max(self.recurring_db - MAX_PEAK_REDUCTION_DB,
                   self.single_db - MAX_PEAK_REDUCTION_DB - SINGLE_PEAK_MARGIN_DB)

    @property
    def isolated(self) -> bool:
        """An isolated event, not the recurring peaks, is what is nearest its limit."""
        return self.single_db - SINGLE_PEAK_MARGIN_DB > self.recurring_db


def _block_peaks(x: np.ndarray, size: int) -> np.ndarray:
    """Largest |sample| of each block of ``size`` samples, all channels."""
    mag = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    count = -(-mag.size // size)
    return np.pad(mag, (0, count * size - mag.size)).reshape(count, size).max(axis=1)


def _peak_reduction(before: np.ndarray, after: np.ndarray, clip_db: float, limiter_db: float
                    ) -> PeakReduction:
    """How much lower the peaks come out, from the peaks of each ``EVENT_BLOCK_S`` block
    ``before`` and ``after`` clipper + limiter.

    Recurring peaks: per 50 ms block, the 98.5th percentile of the blocks reduced by more than
    0.5 dB, but never more than the 10th most reduced one (none with fewer than 10), so a click,
    a plosive or one impact at a drop cannot set the loudness of the whole song. Isolated events
    have their own, wider limit on the reduction they keep over 30 ms: shorter than that, a
    click clipped stays a click, and the most reduced sample (``clip_db``) is shown, never
    budgeted."""
    def reduction(top_before: np.ndarray, top_after: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            db = 20 * np.log10(top_before / top_after)
        db[~np.isfinite(db)] = 0.0
        return db

    def grouped(peaks: np.ndarray) -> np.ndarray:  # 10 ms blocks → 50 ms blocks
        size = int(round(BUDGET_BLOCK_S / EVENT_BLOCK_S))
        return np.pad(peaks, (0, -peaks.size % size)).reshape(-1, size).max(axis=1)

    if before.size == 0:
        return PeakReduction(clip_db, limiter_db, 0.0, 0.0, 0.0)
    per_block = reduction(grouped(before), grouped(after))
    reduced = np.sort(per_block[per_block > 0.5])[::-1]
    recurring = 0.0
    if reduced.size:
        rank = float(reduced[BUDGET_RANK - 1]) if reduced.size >= BUDGET_RANK else 0.0
        recurring = min(float(np.percentile(reduced, BUDGET_PERCENTILE)), rank)
    kept = sliding_window_view(reduction(before, after), min(EVENT_BLOCKS, before.size)).min(axis=1)
    worst = int(kept.argmax())
    return PeakReduction(clip_db, limiter_db, recurring, float(kept[worst]), worst * EVENT_BLOCK_S)


def _loud_stage(x: np.ndarray, fs: float, gain_db: float, ceiling_dbtp: float
                ) -> tuple[np.ndarray, PeakReduction]:
    """Gain → soft clip → limiter; returns the audio and how hard clipper and limiter worked."""
    size = max(1, int(round(EVENT_BLOCK_S * fs)))
    y = x * 10 ** (gain_db / 20)
    before = _block_peaks(y, size)
    peak = 20 * math.log10(before.max()) if before.size and before.max() > 0 else -math.inf
    clip_dbfs = _clip_dbfs(ceiling_dbtp)
    clipped = soft_clip(y, fs, 10 ** (clip_dbfs / 20)) if peak > clip_dbfs - 3.0 else y
    del y  # memory: only one full-length copy at a time
    clip_db = max(0.0, peak - sample_peak_db(clipped))
    lim = limit(clipped, fs, ceiling_dbtp)
    del clipped
    return lim.audio, _peak_reduction(before, _block_peaks(lim.audio, size), clip_db, -lim.max_reduction_db)


def _proxy_loudness(x: np.ndarray, fs: float, gain_db: float, ceiling_dbtp: float) -> float:
    """Loudness after gain → soft clip → the limiter's own gain law on the sample peaks, all at
    the base rate: a cheap stand-in for the real chain to aim the gain."""
    shaped = clip_curve(x * 10 ** (gain_db / 20), 10 ** (_clip_dbfs(ceiling_dbtp) / 20))
    peak = np.abs(shaped).max(axis=1) if shaped.ndim == 2 else np.abs(shaped)
    gain = gain_for(peak, fs, 10 ** (ceiling_dbtp / 20))
    return integrated_loudness(shaped * (gain[:, None] if shaped.ndim == 2 else gain), fs)


def _slope(points: list[tuple[float, float]]) -> float:
    """dB of gain per dB of loudness from the last two (gain, loudness) points (secant), kept
    between 0.5 and 3; 1 until there are two."""
    if len(points) < 2 or points[-1][1] == points[-2][1]:
        return 1.0
    (g0, l0), (g1, l1) = points[-2:]
    return min(max((g1 - g0) / (l1 - l0), 0.5), 3.0)


def _aim(y: np.ndarray, fs: float, target: float, ceiling_dbtp: float,
         tried: list[tuple[float, float]]) -> float:
    """Gain at which the proxy reads ``target`` LUFS (within 0.05), by secant steps from the
    (gain, proxy reading) pairs in ``tried``: the last one is the start, each reading is added."""
    for _ in range(6):
        gain, got = tried[-1]
        if not math.isfinite(got) or abs(got - target) < 0.05:
            break
        gain += (target - got) * _slope(tried)
        tried.append((gain, _proxy_loudness(y, fs, gain, ceiling_dbtp)))
    return tried[-1][0]


def _loudest(y: np.ndarray, fs: float, goal: float, ceiling_dbtp: float
             ) -> tuple[np.ndarray, float, PeakReduction, float, bool]:
    """Gain landing on ``goal`` LUFS unless clipper + limiter would go over their budget
    (``PeakReduction.over_db``): (audio, gain, reductions, loudness reached, stopped by the
    budget).

    The gain is aimed on the cheap proxy, then the real oversampled chain runs at most
    ``REAL_PASSES`` times, twice on most songs: the first pass measures how far the proxy is
    from the real chain, and the gain is aimed again on the proxy plus that offset; a third
    pass corrects with a secant step on the real passes. Each pass checks the budget on the
    reductions it really measured. Over it, the gain comes down by the excess (each dB of gain
    adds about a dB of peak reduction); a step up stops at its edge, and after a correction
    one step back up is taken only with at least 0.3 dB of room. A pass over the budget is
    never kept: if the last one is, one more pass runs at the lowered gain."""
    start = goal - integrated_loudness(y, fs)
    tried = [(start, _proxy_loudness(y, fs, start, ceiling_dbtp))]
    gain = _aim(y, fs, goal, ceiling_dbtp, tried)
    passes: list[tuple[float, float]] = []
    capped = False
    for n in range(REAL_PASSES):
        out = None  # the previous pass's audio is let go before the next one runs
        out, red = _loud_stage(y, fs, gain, ceiling_dbtp)
        got = integrated_loudness(out, fs)
        passes.append((gain, got))
        if red.over_db > 0.1:
            gain -= red.over_db
            capped = True
            continue
        if not math.isfinite(got) or abs(got - goal) < 0.15 or n == REAL_PASSES - 1:
            break
        if len(passes) == 1:  # aim again on the proxy, shifted by what this pass measured
            step = _aim(y, fs, goal - (got - tried[-1][1]), ceiling_dbtp, tried) - gain
        else:
            step = (goal - got) * _slope(passes)
        room = -red.over_db
        if capped and step > 0 and room < 0.3:  # back at the budget's edge
            break
        if step > room:
            capped = True
            if room < 0.05:
                break
            step = room
        gain += step
    else:  # the last pass went over the budget
        out = None
        out, red = _loud_stage(y, fs, gain, ceiling_dbtp)
        got = integrated_loudness(out, fs)
    return out, gain, red, got, capped and got < goal - 0.2


def _note_peaks_db(low: np.ndarray, fs: float) -> np.ndarray:
    """Peak level of each low-band note: on the 25 ms RMS envelope (no waveform ripple), the
    peaks that stand at least 6 dB above the envelope around them, at least 120 ms apart,
    within 30 dB of the loudest. A note's own decay is not a difference between notes."""
    ms, _ = dsp._frames(low, fs)
    if ms.size < 300:
        return np.zeros(0)
    env = 10 * np.log10(np.maximum(np.convolve(ms, np.ones(25) / 25, mode="same"), 1e-20))
    at, _ = find_peaks(env, prominence=6.0, distance=120)
    peaks = env[at]
    return peaks[peaks > peaks.max() - 30.0] if peaks.size else peaks


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
                          f"Les crêtes des {peaks.size} notes graves varient de {spread:.1f} dB d'une note à "
                          "l'autre (du 10e au 90e centile ; l'oreille y entend chaque dB comme plus)",
                          {"threshold_db": float(np.percentile(peaks, 90)) - 1.5 * k / max(slope, 1e-6),
                           "ratio": ratio, "attack_ms": 10.0, "release_ms": 150.0, "max_reduction_db": 3.0 * k})
            low = apply(low, fs, [t])
            if t.applied:
                treatments.append(t)
                y = low + high
    del low, high

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
        if t.applied:
            treatments.append(t)

    # loudness: at −9 LUFS a −2 dBTP ceiling leaves at most 7 dB of peak-to-loudness; under 8 dB,
    # Opus 96k / MP3 128k overshoot by 1.2–2.2 dB, so such a master gets −3 dBTP from the start
    ceiling = DENSE_CEILING_DBTP if _dense(goal) else CEILING_DBTP
    out, gain, red, reached, capped = _loudest(y, fs, goal, ceiling)
    del y
    budget = MAX_PEAK_REDUCTION_DB + SINGLE_PEAK_MARGIN_DB
    reason = (f"Cible {goal:.1f} LUFS ; écrêtage doux : crête la plus forte baissée de {red.clip_db:.1f} dB, "
              f"puis limiteur jusqu'à {red.limiter_db:.1f} dB ; les deux ensemble baissent de "
              f"{red.recurring_db:.1f} dB les crêtes qui reviennent dans le morceau ({MAX_PEAK_REDUCTION_DB:.0f} dB "
              f"au plus), et de {red.single_db:.1f} dB les 30 ms les plus réduites ({budget:.0f} dB au plus "
              "pour un événement isolé)")
    if capped:
        # the ceiling is chosen again on the loudness reached; every stage scales with the ceiling,
        # so the same master with −2 dBTP is exactly this one 1 dB higher, same reductions
        shift = CEILING_DBTP - ceiling
        if shift > 0 and not _dense(reached + shift):
            out = out * 10 ** (shift / 20)
            gain, reached, ceiling = gain + shift, reached + shift, CEILING_DBTP
            reason += (f" ; le budget arrête le master à {reached:.1f} LUFS, où un plafond à {ceiling:.0f} dBTP "
                       f"laisse {CEILING_DBTP - reached:.1f} dB entre crête et volume : pas assez dense pour "
                       f"demander {DENSE_CEILING_DBTP:.0f} dBTP")
        elif shift > 0:
            reason += (f" ; avec un plafond à {CEILING_DBTP:.0f} dBTP, ce master monterait à "
                       f"{reached + shift:.1f} LUFS et laisserait au plus {CEILING_DBTP - reached - shift:.1f} dB "
                       f"entre crête et volume : sous {DENSE_PLR_DB:.0f} dB, l'encodage à bas débit dépasse de 1 à "
                       f"2 dB, d'où {ceiling:.0f} dBTP")
        if red.isolated:
            minutes, seconds = divmod(int(red.single_at_s), 60)
            warnings.append(f"Le morceau est masterisé à {reached:.1f} LUFS au lieu de {goal:.1f} : pour aller "
                            f"plus fort, une crête isolée vers {minutes}:{seconds:02d} demanderait plus de "
                            f"{budget:.0f} dB d'écrêtage et de limiteur (un clic, un impact ? à vérifier dans "
                            "le projet)")
        else:
            warnings.append(f"Le morceau est masterisé à {reached:.1f} LUFS au lieu de {goal:.1f} : aller plus "
                            f"fort demanderait plus de {MAX_PEAK_REDUCTION_DB:.0f} dB d'écrêtage et de limiteur "
                            "sur les crêtes qui reviennent dans le morceau, ce qui écraserait les percussions")
    elif ceiling == DENSE_CEILING_DBTP:
        reason += (f" ; à ce volume, un plafond à {CEILING_DBTP:.0f} dBTP laisserait au plus "
                   f"{CEILING_DBTP - goal:.1f} dB entre crête et volume : sous {DENSE_PLR_DB:.0f} dB, l'encodage à "
                   f"bas débit dépasse de 1 à 2 dB, d'où {ceiling:.0f} dBTP")
    treatments.append(Treatment("loudness", f"Niveau final {gain:+.1f} dB, clip doux puis limiteur à {ceiling:.0f} dBTP",
                                reason, measured={"clip_db": red.clip_db, "limiter_db": red.limiter_db,
                                                  "peak_reduction_db": red.recurring_db,
                                                  "single_peak_reduction_db": red.single_db,
                                                  "ceiling_dbtp": ceiling}))
    c = checks(out, fs)
    if c.true_peak_dbtp > ceiling + 0.1:
        warnings.append(f"Crête réelle à {c.true_peak_dbtp:+.1f} dBTP au-dessus du plafond")
    # warned 0.5 dB denser than planned (ceiling minus loudness: 6 dB at −9 LUFS and −3 dBTP); a
    # calm master with more room only under 7.5 dB, where it turns dense by Eden's own rule
    dense_limit = min(DENSE_PLR_DB, ceiling - (reached if capped else goal)) - 0.5
    if c.plr_db < dense_limit:
        warnings.append(f"Rapport crête/volume de {c.plr_db:.1f} dB, sous {dense_limit:.1f} dB : master très dense, "
                        "risque de distorsion à l'encodage sur les débits bas")
    if c.mono_holes:
        warnings.append("Des éléments s'annulent en mono (téléphone, enceinte Bluetooth) vers "
                        + ", ".join(c.mono_holes) + " : un effet stéréo en opposition de phase dans l'instru ?")
    return MasterResult(out, treatments, gain, red.clip_db, red.limiter_db, c, warnings)
