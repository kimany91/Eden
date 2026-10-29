"""Data model for what Eden knows about an FL Studio project.

Every value read from the .flp is kept in its raw form next to any derived
value, so that a later reader can tell measured facts from interpretation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

MASTER_INSERT = 0


@dataclass
class PluginInfo:
    internal_name: str  # FL internal name, e.g. "Fruity Wrapper", "Fruity Limiter"
    display_name: str | None = None  # name shown in FL (user-renamable)
    format: str = "native"  # native | vst2 | vst3 | unknown-wrapper
    vst_name: str | None = None
    vendor: str | None = None
    path: str | None = None
    state_size: int = 0  # bytes of opaque plugin state stored in the project
    category: str = "unknown"  # filled by eden.project.plugins

    @property
    def label(self) -> str:
        return self.display_name or self.vst_name or self.internal_name or "?"


@dataclass
class Channel:
    index: int
    name: str | None = None
    kind: str = "unknown"  # sampler | instrument | layer | automation | unknown
    type_raw: int | None = None
    enabled: bool | None = None
    locked: bool | None = None
    sample_path: str | None = None
    insert: int | None = None  # FL mixer insert index (0 = Master), None = not stored
    volume_raw: int | None = None  # 0..12800, FL default 10000
    pan_raw: int | None = None  # 0..12800, 6400 = centre
    plugin: PluginInfo | None = None

    @property
    def label(self) -> str:
        return self.name or (self.plugin.label if self.plugin else None) or f"Canal {self.index}"


@dataclass
class MixerSlot:
    index: int
    plugin: PluginInfo
    enabled: bool | None = None
    mix_raw: int | None = None  # dry/wet, 12800 = 100 %


@dataclass
class Route:
    target: int
    level_raw: int | None = None  # None = not stored in the project (FL default)

    @property
    def audible(self) -> bool:
        return self.level_raw is None or self.level_raw > 0


@dataclass
class MixerInsert:
    index: int  # 0 = Master, 1.. = Insert N as numbered in FL
    name: str | None = None
    enabled: bool | None = None
    effects_enabled: bool | None = None
    polarity_inverted: bool | None = None
    swap_lr: bool | None = None
    locked: bool | None = None
    volume_raw: int | None = None  # 12800 = FL default fader position (0 dB)
    pan_raw: int | None = None  # -6400..6400
    stereo_separation_raw: int | None = None
    slots: list[MixerSlot] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.index == MASTER_INSERT:
            return self.name or "Master"
        return self.name or f"Insert {self.index}"

    @property
    def is_default(self) -> bool:
        """True for an untouched insert (no name, no effect, default fader)."""
        return (
            not self.name
            and not self.slots
            and self.volume_raw in (None, 12800)
            and self.pan_raw in (None, 0)
        )


@dataclass
class PlaylistClip:
    arrangement: int
    track: int  # playlist track number as shown in FL ("Track 1" = 1)
    position_ticks: int
    length_ticks: int
    source: str  # channel | pattern
    source_index: int
    start_offset: float | None = None  # raw, unit not yet confirmed for all clip types
    end_offset: float | None = None
    group: int = 0
    start_seconds: float | None = None
    length_seconds: float | None = None


@dataclass
class PlaylistTrack:
    number: int  # as shown in FL ("Track 1" = 1)
    name: str | None = None
    enabled: bool | None = None


@dataclass
class TimeMarker:
    position_ticks: int
    name: str | None
    kind_raw: int  # high byte of the stored position; 8 = time signature


@dataclass
class Arrangement:
    index: int
    name: str | None = None
    tracks: list[PlaylistTrack] = field(default_factory=list)
    clips: list[PlaylistClip] = field(default_factory=list)
    markers: list[TimeMarker] = field(default_factory=list)


@dataclass
class Pattern:
    index: int
    name: str | None = None
    length_ticks: int | None = None
    has_notes: bool = False
    channels: list[int] = field(default_factory=list)  # rack channels played by the notes


@dataclass
class FlpProject:
    fl_version: str | None = None
    fl_build: int | None = None
    format: int = 0
    ppq: int = 96
    header_channel_count: int = 0
    tempo_bpm: float | None = None
    time_signature: tuple[int, int] | None = None
    title: str | None = None
    artists: str | None = None
    genre: str | None = None
    comments: str | None = None
    created: str | None = None  # ISO date, from the project timestamp
    time_spent_hours: float | None = None
    channels: list[Channel] = field(default_factory=list)
    inserts: list[MixerInsert] = field(default_factory=list)
    arrangements: list[Arrangement] = field(default_factory=list)
    patterns: list[Pattern] = field(default_factory=list)
    automation_channels: list[int] = field(default_factory=list)
    unknown_event_ids: dict[int, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def channel(self, index: int) -> Channel | None:
        return next((c for c in self.channels if c.index == index), None)

    def insert(self, index: int) -> MixerInsert | None:
        return next((i for i in self.inserts if i.index == index), None)

    def ticks_to_seconds(self, ticks: int) -> float | None:
        """Constant-tempo conversion. Tempo automation is NOT taken into account."""
        if not self.tempo_bpm:
            return None
        return ticks / self.ppq * 60.0 / self.tempo_bpm


def to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj
