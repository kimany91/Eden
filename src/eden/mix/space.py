"""Depth effects: reverb and tempo-synced delay, used as send/return effects.

Reverb: a stereo impulse response is synthesised from decorrelated noise,
split into octave bands that each decay at their own rate (darker tail),
with a pre-delay and a short build-up; the voice is then convolved with it
(FFT convolution: exact and fast offline). Noise-based tails are smooth and
avoid the metallic ringing of small feedback reverbs.

Delay: repeats on the project's tempo grid, each repeat filtered again
(high-pass and low-pass), optionally alternating left/right.

The sends are de-essed, the returns band-limited and ducked while the dry voice sounds,
so the effect fills the gaps without clouding the words.

The plan for a voice follows the "four sends" a mix engineer sets up for a
rap lead that must stay in front yet glued to the beat: a short ambience, a
plate of about a second, a tempo delay, and an echo "throw" on the last
word of a phrase. Nothing is added to a voice that already carries reverb
or delay from its FL Studio chain. The reverb of the whole mix (the user's
FL effects and Eden's) stays far under the −9 LU relative reverb loudness
that listeners judge too wet (De Man et al. 2017).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import butter, oaconvolve, resample_poly, sosfilt, sosfiltfilt

from eden.mix import dsp
from eden.mix.loudness import block_loudness, integrated_loudness
from eden.mix.riding import felt_quarter, phrases_of

OCTAVE_CENTERS = (63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
LOW_RATE_HZ = 14000.0  # returns are computed at the lowest rate that still holds their 6 kHz band


@dataclass
class ReverbDesign:
    decay_s: float  # RT60 at mid frequencies (500 Hz – 1 kHz)
    predelay_ms: float
    hf_ratio: float = 0.5  # RT60 at 8 kHz relative to mid (darker tails below 1)
    lf_ratio: float = 0.8  # RT60 at 125 Hz relative to mid
    buildup_ms: float = 15.0
    width: float = 1.0  # 0 = mono tail, 1 = fully decorrelated left/right


def _rt60_at(freq: float, d: ReverbDesign) -> float:
    if freq <= 125:
        return d.decay_s * d.lf_ratio
    if freq >= 8000:
        return d.decay_s * d.hf_ratio
    if freq < 750:
        t = (math.log2(freq) - math.log2(125)) / (math.log2(750) - math.log2(125))
        return d.decay_s * (d.lf_ratio + (1 - d.lf_ratio) * t)
    t = (math.log2(freq) - math.log2(750)) / (math.log2(8000) - math.log2(750))
    return d.decay_s * (1 + (d.hf_ratio - 1) * t)


def impulse_response(d: ReverbDesign, fs: float, seed: int = 7) -> np.ndarray:
    """Stereo impulse response (energy normalised to 1)."""
    rng = np.random.default_rng(seed)
    length = int((d.predelay_ms / 1000 + 1.5 * d.decay_s) * fs) + 1
    t = np.arange(length - int(d.predelay_ms / 1000 * fs)) / fs
    left_right = rng.normal(0, 1, (t.size, 2))
    common = rng.normal(0, 1, t.size)
    noise = d.width * left_right + (1 - d.width) * common[:, None]
    tail = np.zeros_like(noise)
    nyquist = fs / 2
    for fc in OCTAVE_CENTERS:
        lo, hi = fc / math.sqrt(2), min(fc * math.sqrt(2), nyquist * 0.95)
        if lo >= hi:
            continue
        sos = butter(3, [lo, hi], btype="bandpass", fs=fs, output="sos")
        envelope = np.exp(-6.9078 * t / _rt60_at(fc, d))  # −60 dB at RT60
        tail += sosfiltfilt(sos, noise, axis=0) * envelope[:, None]
    ramp = np.minimum(1.0, t / max(d.buildup_ms / 1000, 1e-6))
    tail *= ramp[:, None]
    ir = np.vstack([np.zeros((length - t.size, 2)), tail])
    return ir / math.sqrt(float(np.sum(ir ** 2)) / 2)


def reverb(x: np.ndarray, fs: float, d: ReverbDesign) -> np.ndarray:
    """100 % wet stereo reverb of ``x`` (mono or stereo input)."""
    src = x.mean(axis=1) if x.ndim == 2 else x
    ir = impulse_response(d, fs)
    wet = np.stack([oaconvolve(src, ir[:, c])[: src.size] for c in range(2)], axis=1)
    return wet


def tempo_delay(x: np.ndarray, fs: float, delay_s: float, feedback: float, repeats: int = 6,
                highpass_hz: float = 300.0, lowpass_hz: float = 5000.0, ping_pong: bool = True
                ) -> np.ndarray:
    """100 % wet delay: ``repeats`` echoes, each one feedback × quieter and filtered again."""
    src = x.mean(axis=1) if x.ndim == 2 else x
    n = src.size
    step = int(round(delay_s * fs))
    band = np.vstack([dsp.highpass_sos(fs, highpass_hz),
                      butter(2, lowpass_hz, btype="lowpass", fs=fs, output="sos")])
    out = np.zeros((n, 2))
    echo = src
    for k in range(1, repeats + 1):
        echo = sosfilt(band, echo) * feedback
        shift = k * step
        if shift >= n:
            break
        if ping_pong:
            out[shift:, (k + 1) % 2] += echo[: n - shift]
        else:
            out[shift:, :] += echo[: n - shift, None]
    return out


def duck(wet: np.ndarray, dry: np.ndarray, fs: float, depth_db: float, release_ms: float) -> np.ndarray:
    """Lower an effect return by ``depth_db`` while the dry voice sounds."""
    if depth_db <= 0:
        return wet
    level, size = dsp.band_levels_db(dry, fs)
    if level.size == 0:
        return wet
    threshold = float(np.percentile(level, 95)) - 30.0
    env, size = dsp.activity_envelope(dry, fs, threshold, attack_ms=5.0, release_ms=release_ms)
    gain = 10 ** (-depth_db * env / 20)
    centers = (np.arange(env.size) + 0.5) * size
    per_sample = np.interp(np.arange(wet.shape[0]), centers, gain)
    return wet * per_sample[:, None]


def band_limit(wet: np.ndarray, fs: float, highpass_hz: float, lowpass_hz: float) -> np.ndarray:
    sos = np.vstack([dsp.highpass_sos(fs, highpass_hz),
                     butter(2, lowpass_hz, btype="lowpass", fs=fs, output="sos")])
    return sosfilt(sos, wet, axis=0)


@dataclass
class Send:
    name: str  # ambience | plate | delay | throw
    label: str
    level_db: float  # return loudness target relative to the dry voice
    duck_db: float
    duck_release_ms: float
    highpass_hz: float
    lowpass_hz: float
    reverb: ReverbDesign | None = None
    delay_s: float | None = None
    feedback: float = 0.0
    throw_only: bool = False  # fed by the last word of each phrase only


@dataclass
class SpacePlan:
    sends: list[Send] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def design_space(tempo_bpm: float | None, role: str, k: float) -> SpacePlan:
    """The sends of one voice (levels in dB relative to the dry voice, before ducking)."""
    plan = SpacePlan()
    if k <= 0:
        return plan
    lead = role in ("lead_vocal", "vocal")
    quarter = felt_quarter(tempo_bpm) if tempo_bpm else 0.5
    # plate: 0.8–1.4 s, shorter at fast tempos (about two beats, never snapped to a note)
    decay = min(1.4, max(0.8, 2 * quarter))
    predelay = min(80.0, max(20.0, min((quarter / 16 * 1000, quarter / 8 * 1000), key=lambda v: abs(v - 45))))
    back = 0.0 if lead else 4.0  # secondary voices sit further back (lower direct-to-reverb ratio)
    plan.sends.append(Send("ambience", "Ambiance courte (80 ms, pré-delay 8 ms)", -23.0 + back, 0.0, 0.0,
                           400.0, 6000.0, reverb=ReverbDesign(0.08, 8.0, hf_ratio=0.6, buildup_ms=5.0)))
    plan.sends.append(Send("plate", f"Plate {decay:.1f} s, pré-delay {predelay:.0f} ms", -19.0 + back, 2.5, 120.0,
                           300.0, 6000.0, reverb=ReverbDesign(decay, predelay, hf_ratio=0.5)))
    eighth = quarter / 2
    # delay ducks recover within a quarter of the delay time, so the first echo after a phrase is heard whole
    plan.sends.append(Send("delay", f"Delay 1/8 ({eighth * 1000:.0f} ms, ping-pong)", -21.0 + back, 10.0,
                           eighth * 250, 400.0, 4000.0, delay_s=eighth, feedback=0.25))
    if lead:
        plan.sends.append(Send("throw", f"Jet d'écho 1/4 ({quarter * 1000:.0f} ms) sur les fins de phrase",
                               -12.0, 10.0, quarter * 250, 400.0, 4000.0, delay_s=quarter, feedback=0.35,
                               throw_only=True))
    plan.notes.append(f"Tempo ressenti : noire = {quarter * 1000:.0f} ms"
                      + (f" (projet à {tempo_bpm:g} BPM)" if tempo_bpm else " (tempo inconnu : 120 BPM supposé)"))
    return plan


def throw_envelope(dry: np.ndarray, fs: float, gap_s: float, last_s: float = 0.3) -> np.ndarray:
    """1 on the last ``last_s`` of each phrase that is followed by a gap of at least ``gap_s``."""
    level, size = dsp.band_levels_db(dry, fs)
    if level.size == 0:
        return np.zeros(dry.shape[0])
    active = level > float(np.percentile(level, 95)) - 30.0
    env = np.zeros(level.size)
    gap_frames = max(1, int(round(gap_s / dsp.FRAME_S)))
    for s, e in phrases_of(active, gap_frames // 2):
        gap = (e + gap_frames <= level.size and not active[e:e + gap_frames].any()) or e + gap_frames > level.size
        if gap and e - s > gap_frames // 2:
            env[max(s, e - int(last_s / dsp.FRAME_S)):e] = 1.0
    # short fades so the send does not click
    ramp = max(1, int(0.03 / dsp.FRAME_S))
    env = np.convolve(env, np.ones(ramp) / ramp, mode="same")
    centers = (np.arange(env.size) + 0.5) * size
    return np.interp(np.arange(dry.shape[0]), centers, env)


def _deess_send(dry: np.ndarray, fs: float) -> np.ndarray:
    """The send is de-essed harder than the voice: an echoed 's' is only noise."""
    high, rest = dsp.split_band(dry, fs, 5000.0, None)
    level, size = dsp.band_levels_db(high, fs)
    loud = level[level > -90.0]
    if loud.size == 0:
        return dry
    gr = dsp.deess_reduction_db(level, float(np.percentile(loud, 75)) - 3.0, 8.0)
    return rest + dsp._apply_gain(high, dsp._to_samples(gr, size, dry.shape[0]))


def render_space(dry: np.ndarray, fs: float, plan: SpacePlan, k: float) -> tuple[np.ndarray, list[str]]:
    """Sum of the returns of ``plan`` for the dry voice (stereo, scaled by ``k``) and its report.

    Every return is band-limited under 6 kHz, so the effects are computed at
    a third of the sample rate (or less) and the sum is brought back up once:
    same sound, a fraction of the work.
    """
    n = dry.shape[0]
    stereo = dry if dry.ndim == 2 else np.repeat(dry[:, None], 2, axis=1)
    report: list[str] = []
    if k <= 0 or not plan.sends:
        return np.zeros((n, 2)), report
    factor = max(1, int(fs // LOW_RATE_HZ))
    rate = fs / factor
    send_source = _deess_send(dry, fs)  # one de-esser on the send feeds every effect
    if factor > 1:
        send_source = resample_poly(send_source, 1, factor, axis=0)
        dry_low = resample_poly(dry, 1, factor, axis=0)
    else:
        dry_low = dry
    dry_lufs = integrated_loudness(stereo, fs)
    total = np.zeros((send_source.shape[0], 2))
    for send in plan.sends:
        source = send_source
        if send.throw_only:
            env = throw_envelope(dry_low, rate, send.delay_s or 0.5)
            source = send_source * (env[:, None] if send_source.ndim == 2 else env)
        if send.reverb is not None:
            wet = reverb(source, rate, send.reverb)
        else:
            wet = tempo_delay(source, rate, send.delay_s, send.feedback, highpass_hz=send.highpass_hz,
                              lowpass_hz=send.lowpass_hz)
        wet = band_limit(wet, rate, send.highpass_hz, send.lowpass_hz)
        wet_lufs = integrated_loudness(wet, rate)
        if not (math.isfinite(wet_lufs) and math.isfinite(dry_lufs)):
            continue
        wet = wet * 10 ** ((dry_lufs + send.level_db - wet_lufs) / 20)
        if send.duck_db > 0:
            wet = duck(wet, dry_low, rate, send.duck_db, send.duck_release_ms)
        total += wet * k
        level = send.level_db + 20 * math.log10(k)  # what the intensity really leaves of it
        report.append(f"{send.label} : {level:+.0f} dB sous la voix"
                      + (f", baissé de {send.duck_db:g} dB pendant qu'elle chante" if send.duck_db else ""))
    if factor > 1:
        total = resample_poly(total, factor, 1, axis=0)[:n]
        total = np.pad(total, ((0, n - total.shape[0]), (0, 0)))
    return total, report


def relative_reverb_loudness(wet_power: np.ndarray, dry_power: np.ndarray) -> float:
    """De Man, McNally & Reiss (2017) relative reverb loudness: the loudness of the reverb minus
    that of the dry mix, window by window (400 ms), averaged over the windows where the dry mix
    plays (within 20 LU of its loud parts). Inputs are K-weighted block powers."""
    with np.errstate(divide="ignore"):
        dry_db = 10 * np.log10(dry_power)
    finite = np.isfinite(dry_db)
    if not finite.any():
        return -math.inf
    gate = 10 ** ((-70.0 + 0.691) / 10)  # the absolute gate of BS.1770: a silent tail is not reverb
    playing = finite & (dry_db > float(np.percentile(dry_db[finite], 95)) - 20.0) & (wet_power > gate)
    if not playing.any():
        return -math.inf
    return float(np.mean(10 * np.log10(wet_power[playing] / dry_power[playing])))


def block_power(x: np.ndarray, fs: float) -> np.ndarray:
    """K-weighted power of the 400 ms blocks (100 ms apart) BS.1770 measures."""
    return 10 ** ((block_loudness(x, fs) + 0.691) / 10)


def returns_scale(fl_wet: np.ndarray, eden_wet: np.ndarray, dry: np.ndarray, fs: float, cap_lu: float
                  ) -> tuple[float, float]:
    """(scale for Eden's returns, resulting relative reverb loudness): the largest scale ≤ 1 that
    keeps the reverb of the whole mix — the user's FL effects plus Eden's — at or under ``cap_lu``."""
    p_fl, p_eden, p_dry = block_power(fl_wet, fs), block_power(eden_wet, fs), block_power(dry, fs)
    n = min(p_fl.size, p_eden.size, p_dry.size)
    p_fl, p_eden, p_dry = p_fl[:n], p_eden[:n], p_dry[:n]

    def rrl(scale: float) -> float:
        return relative_reverb_loudness(p_fl + scale ** 2 * p_eden, p_dry)  # uncorrelated tails add in power

    if rrl(1.0) <= cap_lu:
        return 1.0, rrl(1.0)
    if rrl(0.0) >= cap_lu:
        return 0.0, rrl(0.0)
    lo, hi = 0.0, 1.0
    for _ in range(20):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if rrl(mid) <= cap_lu else (lo, mid)
    return lo, rrl(lo)
