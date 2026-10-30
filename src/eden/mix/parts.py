"""Split FL Studio's renders into the parts Eden mixes.

    voices    each voice alone (the vocal channels of one Mixer track with one
              role, together), with its whole FL chain; when FL
              also rendered it without its reverbs and delays, the voice
              carries that dry render and ``space`` (full minus dry) holds
              exactly what the user's FL effects add
    groups    each top-level mixer group that carries no voice (808, drums,
              beat...), as FL rendered it
    residual  everything else: buses shared with voices (what they add on top
              of the voices), and any source FL rendered with a voice; a voice
              with no render of its own (beyond the render plan's limit of
              vocal renders, or whose render failed) is left there too, and
              ``voices_in_residual`` says so

By construction ``sum(voices) + sum(groups) + residual`` equals the
pre-master render exactly, so Eden at intensity 0 gives back the song.

Voices and groups are kept in 32-bit float, the format FL renders them in
(24-bit integer renders fit in it exactly too): half the memory, nothing
lost. The pre-master mix and the residual stay in 64-bit.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from eden.mix.dsp import band_levels_db
from eden.project.inspector import InspectionReport
from eden.render.pipeline import RenderResult
from eden.render.plan import voice_title

DRY_LAG_SEARCH_S = 0.1  # how far FL's delay compensation may have moved the dry voice (choix d'Eden)


class PartsError(RuntimeError):
    pass


@dataclass
class Part:
    key: str  # "ch<index>" for a voice, the render job's name ("stem-…") for a group, "residual"
    label: str
    role: str  # a role from eden.project.classify, or "residual"
    audio: np.ndarray = field(repr=False)
    channels: list[int] = field(default_factory=list)
    dry: np.ndarray | None = field(default=None, repr=False)  # the voice without its FL reverbs/delays

    @property
    def space(self) -> np.ndarray | None:
        """What the FL reverbs and delays add to the voice (None when FL had none)."""
        return None if self.dry is None else self.audio - self.dry


@dataclass
class Parts:
    voices: list[Part]
    groups: list[Part]
    residual: Part
    sample_rate: int
    premaster: np.ndarray = field(repr=False)
    warnings: list[str] = field(default_factory=list)
    voices_in_residual: bool = False  # a vocal source that reaches the Master has no voice part

    def all(self) -> list[Part]:
        return [*self.voices, *self.groups, self.residual]


def _load(path: Path, dtype: str = "float32") -> tuple[np.ndarray, int]:
    return sf.read(str(path), dtype=dtype, always_2d=True)


def _fit(x: np.ndarray, length: int, channels: int) -> np.ndarray:
    if x.shape[1] != channels:
        x = np.repeat(x[:, :1], channels, axis=1)
    return np.pad(x, ((0, length - x.shape[0]), (0, 0))) if x.shape[0] < length else x


def _group_role(roles: list[str]) -> str:
    """Role of a group from its members' roles (the most frequent one)."""
    return Counter(roles).most_common(1)[0][0] if roles else "unknown"


def _lag_correlation(f: np.ndarray, d: np.ndarray, lag: int) -> np.ndarray:
    """``sum f[n + k] · d[n]`` for every k from −lag to +lag.

    Computed one block of ``d`` at a time with FFTs a few times ``2·lag`` long,
    so the memory it takes does not grow with the song.
    """
    nf = 1 << max(17, (8 * lag).bit_length())
    block = nf - 2 * lag
    out = np.zeros(2 * lag + 1)
    for start in range(0, d.size, block):
        db = d[start:start + block]
        lo = start - lag  # the stretch of f that this block meets: [lo, lo + block + 2·lag)
        fb = f[max(0, lo):max(0, lo + db.size + 2 * lag)]
        fb = np.concatenate([np.zeros(max(0, -lo)), fb])
        out += np.fft.irfft(np.fft.rfft(fb, nf) * np.conj(np.fft.rfft(db, nf)), nf)[:2 * lag + 1]
    return out


def dry_render_problem(full: np.ndarray, dry: np.ndarray, fs: float) -> str | None:
    """Why FL's dry render cannot be trusted as "the voice without its effects", or None.

    FL must have removed something (an effect it did not bypass, or one that
    was not heard, leaves the dry render equal to the full one). On the
    moments the voice sings, the dry render must line up with the full one
    to 2 samples (a plugin bypassed in the copy can change FL's delay
    compensation, by whole blocks of 32 samples and more): the lag is
    searched up to ``DRY_LAG_SEARCH_S`` either way. When the best lag is
    off by more than 2 samples and the dry voice is found there at less
    than half the level of the quieter of the two renders, it lies further
    away (within 2 samples, such a weak match means the effects lowered the
    voice, which the checks below name). What the effects add must
    neither be a copy of the voice (a return that let the dry send through,
    a plugin whose dry/wet knob also lowers the voice) nor louder than the
    voice itself.
    """
    f = full.mean(axis=1) if full.ndim == 2 else full
    d = dry.mean(axis=1) if dry.ndim == 2 else dry
    level, size = band_levels_db(d, fs)
    if level.size == 0:
        return None
    active = np.repeat(level > float(np.percentile(level, 95)) - 30.0, size)
    mask = np.pad(active, (0, max(0, d.size - active.size)))[:d.size]
    fm, dm = f * mask, d * mask
    e_full, e_dry = float(np.dot(fm, fm)), float(np.dot(dm, dm))
    if e_dry <= 0:
        return "elle est muette"
    window = int(round(DRY_LAG_SEARCH_S * fs))
    near = _lag_correlation(fm, dm, window + 1)  # one sample further: a lag beyond the window shows
    best = int(np.argmax(near)) - window - 1
    if abs(best) > 2:
        if abs(best) > window or near[best + window + 1] < 0.5 * np.sqrt(e_dry * min(e_dry, e_full)):
            return f"décalée de plus de {DRY_LAG_SEARCH_S * 1000:.0f} ms"
        return f"décalée de {abs(best) / fs * 1000:.1f} ms"
    space = fm - dm
    e_space = float(np.dot(space, space))
    if e_space <= 1e-6 * e_dry:
        return "FL Studio n'a rien retiré (effets coupés non respectés ou inaudibles)"
    corr = float(np.dot(space, dm)) / np.sqrt(e_dry * e_space)
    if abs(corr) > 0.5:
        return "la voix elle-même reste dans la part des effets (retour d'effet ou réglage dry/wet d'un plugin)"
    if e_space > e_dry:
        return "les effets y seraient plus forts que la voix"
    return None


def split(report: InspectionReport, renders: RenderResult) -> Parts:
    premaster_path = renders.wav("premaster")
    if premaster_path is None:
        raise PartsError("Le rendu de référence (pré-Master) est absent : relance la récupération du son")
    premaster, fs = _load(premaster_path, "float64")
    sources = {s.channel: s for s in report.sources}

    loaded: list[tuple[str, object, np.ndarray]] = []  # (kind, job, audio)
    for jr in renders.jobs:
        voiced = any(sources[c].role.is_vocal for c in jr.job.channels if c in sources)
        if jr.job.kind == "stem" and voiced:
            continue  # a group that carries a voice: the voice comes from its own render
        if jr.job.kind in ("vocal", "vocal_dry", "stem") and jr.wav_path:
            audio, sr = _load(Path(jr.wav_path))
            if sr != fs:
                raise PartsError(f"« {jr.job.description} » n'a pas la même fréquence d'échantillonnage")
            loaded.append((jr.job.kind, jr.job, audio))
    length = max([premaster.shape[0], *(a.shape[0] for _, _, a in loaded)])
    channels = premaster.shape[1]
    premaster = _fit(premaster, length, channels)

    voices: list[Part] = []
    groups: list[Part] = []
    warnings: list[str] = []
    dry = {job.channels[0]: _fit(audio, length, channels)
           for kind, job, audio in loaded if kind == "vocal_dry"}
    for kind, job, audio in loaded:
        audio = _fit(audio, length, channels)
        members = [sources[c] for c in job.channels if c in sources]
        if kind == "vocal":
            s = members[0] if members else None
            label = voice_title(report.project, members) if members else job.description
            voice_dry = dry.get(job.channels[0])
            problem = dry_render_problem(audio, voice_dry, fs) if voice_dry is not None else None
            if problem:
                warnings.append(f"« {label} » : la voix sèche rendue par FL Studio ne colle pas à la voix "
                                f"complète ({problem}) ; ses effets FL sont traités avec prudence")
                voice_dry = None
            voices.append(Part(f"ch{job.channels[0]}", label, s.role.role if s else "vocal", audio,
                               list(job.channels), dry=voice_dry))
        elif kind == "stem":
            label = job.description.split(" : ")[0].removeprefix("Groupe ")
            groups.append(Part(job.name, label, _group_role([m.role.role for m in members]), audio,
                               list(job.channels)))
    residual = premaster.copy()
    for part in voices + groups:
        residual -= part.audio  # float32 parts promoted to float64: the sum stays exact
    rendered = {c for v in voices for c in v.channels}
    left = any(s.reaches_master and s.role.is_vocal and s.channel not in rendered for s in report.sources)
    return Parts(voices, groups, Part("residual", "Reste du mix (bus partagés, autres sources)",
                                      "residual", residual), fs, premaster, warnings, left)
