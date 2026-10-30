"""Turn the raw FLP event stream into an :class:`FlpProject`.

The parser is strictly read-only: it receives bytes and returns a model.
Anything it cannot interpret is counted in ``unknown_event_ids`` instead of
being guessed.
"""

from __future__ import annotations

import struct
from collections import Counter
from datetime import datetime, timedelta

from eden.flp import ids
from eden.flp.events import Event, FlpHeader, read_events
from eden.project.model import (
    Arrangement,
    Channel,
    FlpProject,
    MixerInsert,
    MixerSlot,
    Pattern,
    PlaylistClip,
    PlaylistTrack,
    PluginInfo,
    Route,
    TimeMarker,
)

_DELPHI_EPOCH = datetime(1899, 12, 30)

# Event IDs that this parser understands; everything else is reported.
_KNOWN = {
    ids.PROJECT_FL_VERSION, ids.PROJECT_FL_BUILD, ids.PROJECT_TEMPO, ids.PROJECT_TEMPO_COARSE,
    ids.PROJECT_TEMPO_FINE, ids.PROJECT_TITLE, ids.PROJECT_COMMENTS, ids.PROJECT_URL,
    ids.PROJECT_DATA_PATH, ids.PROJECT_GENRE, ids.PROJECT_ARTISTS, ids.PROJECT_TIMESTAMP,
    ids.TIME_SIG_NUM, ids.TIME_SIG_BEAT, ids.CHANNEL_NEW, ids.CHANNEL_ENABLED, ids.CHANNEL_TYPE,
    ids.CHANNEL_ROUTED_TO, ids.CHANNEL_LOCKED, ids.CHANNEL_NAME_LEGACY, ids.CHANNEL_SAMPLE_PATH,
    ids.CHANNEL_LEVELS, ids.CHANNEL_AUTOMATION, ids.PLUGIN_INTERNAL_NAME, ids.PLUGIN_NAME,
    ids.PLUGIN_WRAPPER, ids.PLUGIN_DATA, ids.PATTERN_NEW, ids.PATTERN_NAME, ids.PATTERN_LENGTH,
    ids.PATTERN_NOTES, ids.ARRANGEMENT_NEW, ids.ARRANGEMENT_NAME, ids.ARRANGEMENT_PLAYLIST,
    ids.TRACK_DATA, ids.TRACK_NAME, ids.TIMEMARKER_POSITION, ids.TIMEMARKER_NAME,
    ids.MIXER_PARAMS, ids.INSERT_NAME, ids.INSERT_FLAGS, ids.INSERT_ROUTING, ids.INSERT_INPUT,
    ids.INSERT_OUTPUT, ids.SLOT_INDEX,
}

_MIXER_EVENTS = {
    ids.INSERT_NAME, ids.INSERT_FLAGS, ids.INSERT_ROUTING, ids.INSERT_INPUT,
    ids.INSERT_OUTPUT, ids.SLOT_INDEX,
}


def _version_tuple(version: str | None) -> tuple[int, ...]:
    if not version:
        return ()
    parts = []
    for p in version.split("."):
        if not p.isdigit():
            break
        parts.append(int(p))
    return tuple(parts)


class _Parser:
    def __init__(self, header: FlpHeader) -> None:
        self.p = FlpProject(format=header.format, ppq=header.ppq,
                            header_channel_count=header.channel_count)
        self.unicode = True  # FL >= 11.5; corrected when the version event is read
        self.mode: str | None = None
        self.channel: Channel | None = None
        self.pattern: Pattern | None = None
        self.arrangement: Arrangement | None = None
        self.insert: MixerInsert | None = None
        self.insert_count = 0
        self.slot_ordinal = 0
        self.plugin_events: list[Event] = []
        self.playlist_events: list[tuple[Arrangement, bytes]] = []
        self.mixer_params: bytes | None = None
        self.tempo_coarse: int | None = None
        self.tempo_fine: int | None = None
        self.ts_num: int | None = None
        self.ts_beat: int | None = None
        self.unknown: Counter[int] = Counter()

    # -- helpers ---------------------------------------------------------
    def text(self, e: Event) -> str:
        raw = e.data
        if self.unicode:
            s = raw.decode("utf-16-le", errors="replace")
        else:
            s = raw.decode("latin-1")
        return s.rstrip("\0")

    def _flush_channel_plugin(self) -> None:
        if self.channel is not None and self.plugin_events:
            plugin = _build_plugin(self.plugin_events, self.text)
            if plugin.internal_name:
                self.channel.plugin = plugin
            if self.channel.name is None and plugin.display_name:
                self.channel.name = plugin.display_name
        self.plugin_events = []

    def _current_insert(self) -> MixerInsert:
        if self.insert is None:
            self.insert = MixerInsert(index=self.insert_count)
            self.slot_ordinal = 0
        return self.insert

    # -- main loop -------------------------------------------------------
    def feed(self, e: Event) -> None:
        i = e.id
        if i not in _KNOWN:
            self.unknown[i] += 1
            return

        # Structural openers decide which object subsequent events belong to.
        if i == ids.CHANNEL_NEW:
            self._flush_channel_plugin()
            self.mode = "channel"
            self.channel = Channel(index=e.as_int())
            self.p.channels.append(self.channel)
            return
        if i == ids.PATTERN_NEW:
            self._flush_channel_plugin()
            self.mode = "pattern"
            idx = e.as_int()
            self.pattern = next((p for p in self.p.patterns if p.index == idx), None)
            if self.pattern is None:
                self.pattern = Pattern(index=idx)
                self.p.patterns.append(self.pattern)
            return
        if i == ids.ARRANGEMENT_NEW:
            self._flush_channel_plugin()
            self.mode = "arrangement"
            self.arrangement = Arrangement(index=e.as_int())
            self.p.arrangements.append(self.arrangement)
            return
        if i in _MIXER_EVENTS and self.mode != "mixer":
            self._flush_channel_plugin()
            self.mode = "mixer"

        handler = _HANDLERS.get(i)
        if handler is not None:
            handler(self, e)

    def finish(self) -> FlpProject:
        self._flush_channel_plugin()
        p = self.p
        _finalize_channel_kinds(p)
        if p.tempo_bpm is None and self.tempo_coarse is not None:
            p.tempo_bpm = self.tempo_coarse + (self.tempo_fine or 0) / 1000
        if self.ts_num and self.ts_beat:
            p.time_signature = (self.ts_num, self.ts_beat)
        if self.mixer_params is not None:
            _apply_mixer_params(p, self.mixer_params)
        max_track = 499 if _version_tuple(p.fl_version) >= (12, 9, 1) else 198
        for arr, data in self.playlist_events:
            arr.clips.extend(_parse_playlist(p, arr.index, data, max_track))
        for ch in p.channels:
            if ch.kind == "automation":
                p.automation_channels.append(ch.index)
        p.unknown_event_ids = dict(sorted(self.unknown.items()))
        return p


# -- event handlers ------------------------------------------------------------

def _h_version(ps: _Parser, e: Event) -> None:
    ps.p.fl_version = e.data.decode("ascii", errors="replace").rstrip("\0")
    ps.unicode = _version_tuple(ps.p.fl_version) >= (11, 5)


def _h_text_field(attr: str):
    def h(ps: _Parser, e: Event) -> None:
        setattr(ps.p, attr, ps.text(e) or None)
    return h


def _h_build(ps: _Parser, e: Event) -> None:
    ps.p.fl_build = e.as_int()


def _h_tempo(ps: _Parser, e: Event) -> None:
    ps.p.tempo_bpm = e.as_int() / 1000


def _h_tempo_coarse(ps: _Parser, e: Event) -> None:
    ps.tempo_coarse = e.as_int()


def _h_tempo_fine(ps: _Parser, e: Event) -> None:
    ps.tempo_fine = e.as_int()


def _h_ts_num(ps: _Parser, e: Event) -> None:
    ps.ts_num = e.as_int()


def _h_ts_beat(ps: _Parser, e: Event) -> None:
    ps.ts_beat = e.as_int()


def _h_timestamp(ps: _Parser, e: Event) -> None:
    if len(e.data) < 16:
        return
    created, spent = struct.unpack("<dd", e.data[:16])
    try:
        ps.p.created = (_DELPHI_EPOCH + timedelta(days=created)).isoformat(timespec="seconds")
    except (OverflowError, ValueError):
        ps.p.warnings.append("Date de création du projet illisible")
    ps.p.time_spent_hours = round(spent * 24, 2)


def _h_channel_byte(attr: str, convert=int):
    def h(ps: _Parser, e: Event) -> None:
        if ps.mode == "channel" and ps.channel is not None:
            setattr(ps.channel, attr, convert(e.as_int()))
    return h


def _h_channel_type(ps: _Parser, e: Event) -> None:
    if ps.mode == "channel" and ps.channel is not None:
        ps.channel.type_raw = e.as_int()


def _h_routed_to(ps: _Parser, e: Event) -> None:
    if ps.mode == "channel" and ps.channel is not None:
        value = e.as_int(signed=True)
        ps.channel.insert = value if value >= 0 else None


def _h_channel_name_legacy(ps: _Parser, e: Event) -> None:
    if ps.mode == "channel" and ps.channel is not None and ps.channel.name is None:
        ps.channel.name = ps.text(e) or None


def _h_sample_path(ps: _Parser, e: Event) -> None:
    if ps.mode == "channel" and ps.channel is not None:
        ps.channel.sample_path = ps.text(e) or None


def _h_levels(ps: _Parser, e: Event) -> None:
    if ps.mode == "channel" and ps.channel is not None and len(e.data) >= 8:
        pan, vol = struct.unpack("<iI", e.data[:8])
        ps.channel.pan_raw, ps.channel.volume_raw = pan, vol


def _h_plugin_event(ps: _Parser, e: Event) -> None:
    if ps.mode == "channel":
        if e.id == ids.PLUGIN_NAME and ps.channel is not None:
            ps.channel.name = ps.text(e) or None
        ps.plugin_events.append(e)
    elif ps.mode == "mixer":
        ps._current_insert()
        ps.plugin_events.append(e)


def _h_pattern_name(ps: _Parser, e: Event) -> None:
    if ps.mode == "pattern" and ps.pattern is not None:
        ps.pattern.name = ps.text(e) or None


def _h_pattern_length(ps: _Parser, e: Event) -> None:
    if ps.mode == "pattern" and ps.pattern is not None:
        ps.pattern.length_ticks = e.as_int()


def _h_pattern_notes(ps: _Parser, e: Event) -> None:
    if ps.mode == "pattern" and ps.pattern is not None and e.data:
        ps.pattern.has_notes = True
        # 24-byte note records; the rack channel is the u16 at offset 6.
        found = {
            struct.unpack("<H", e.data[off + 6:off + 8])[0]
            for off in range(0, len(e.data) - 23, 24)
        }
        ps.pattern.channels = sorted(found | set(ps.pattern.channels))


def _h_arr_name(ps: _Parser, e: Event) -> None:
    if ps.arrangement is not None:
        ps.arrangement.name = ps.text(e) or None


def _h_playlist(ps: _Parser, e: Event) -> None:
    if ps.arrangement is not None:
        ps.playlist_events.append((ps.arrangement, e.data))


def _h_track_data(ps: _Parser, e: Event) -> None:
    if ps.arrangement is None:
        return
    track = PlaylistTrack(number=len(ps.arrangement.tracks) + 1)
    if len(e.data) >= 13:
        track.enabled = bool(e.data[12])
    ps.arrangement.tracks.append(track)


def _h_track_name(ps: _Parser, e: Event) -> None:
    if ps.arrangement is not None and ps.arrangement.tracks:
        ps.arrangement.tracks[-1].name = ps.text(e) or None


def _h_marker_pos(ps: _Parser, e: Event) -> None:
    if ps.arrangement is not None:
        raw = e.as_int()
        ps.arrangement.markers.append(TimeMarker(raw & 0xFFFFFF, None, raw >> 24))


def _h_marker_name(ps: _Parser, e: Event) -> None:
    if ps.arrangement is not None and ps.arrangement.markers:
        ps.arrangement.markers[-1].name = ps.text(e) or None


def _h_mixer_params(ps: _Parser, e: Event) -> None:
    ps.mixer_params = e.data


def _h_insert_name(ps: _Parser, e: Event) -> None:
    ps._current_insert().name = ps.text(e) or None


def _h_insert_flags(ps: _Parser, e: Event) -> None:
    ins = ps._current_insert()
    if len(e.data) >= 8:
        flags = struct.unpack("<I", e.data[4:8])[0]
        ins.polarity_inverted = bool(flags & ids.INSERT_FLAG_POLARITY)
        ins.swap_lr = bool(flags & ids.INSERT_FLAG_SWAP_LR)
        ins.effects_enabled = bool(flags & ids.INSERT_FLAG_EFFECTS_ON)
        ins.enabled = bool(flags & ids.INSERT_FLAG_ENABLED)
        ins.locked = bool(flags & ids.INSERT_FLAG_LOCKED)


def _h_insert_routing(ps: _Parser, e: Event) -> None:
    ins = ps._current_insert()
    ins.routes = [Route(target=t) for t, b in enumerate(e.data) if b and t != ins.index]


def _h_slot_index(ps: _Parser, e: Event) -> None:
    ins = ps._current_insert()
    if ps.plugin_events:
        plugin = _build_plugin(ps.plugin_events, ps.text)
        if plugin.internal_name:
            ins.slots.append(MixerSlot(index=ps.slot_ordinal, plugin=plugin))
    ps.plugin_events = []
    ps.slot_ordinal += 1


def _h_insert_output(ps: _Parser, e: Event) -> None:
    ins = ps._current_insert()
    ps.plugin_events = []
    ps.p.inserts.append(ins)
    ps.insert = None
    ps.insert_count += 1


_HANDLERS = {
    ids.PROJECT_FL_VERSION: _h_version,
    ids.PROJECT_FL_BUILD: _h_build,
    ids.PROJECT_TEMPO: _h_tempo,
    ids.PROJECT_TEMPO_COARSE: _h_tempo_coarse,
    ids.PROJECT_TEMPO_FINE: _h_tempo_fine,
    ids.PROJECT_TITLE: _h_text_field("title"),
    ids.PROJECT_COMMENTS: _h_text_field("comments"),
    ids.PROJECT_GENRE: _h_text_field("genre"),
    ids.PROJECT_ARTISTS: _h_text_field("artists"),
    ids.PROJECT_TIMESTAMP: _h_timestamp,
    ids.TIME_SIG_NUM: _h_ts_num,
    ids.TIME_SIG_BEAT: _h_ts_beat,
    ids.CHANNEL_ENABLED: _h_channel_byte("enabled", bool),
    ids.CHANNEL_LOCKED: _h_channel_byte("locked", bool),
    ids.CHANNEL_TYPE: _h_channel_type,
    ids.CHANNEL_ROUTED_TO: _h_routed_to,
    ids.CHANNEL_NAME_LEGACY: _h_channel_name_legacy,
    ids.CHANNEL_SAMPLE_PATH: _h_sample_path,
    ids.CHANNEL_LEVELS: _h_levels,
    ids.PLUGIN_INTERNAL_NAME: _h_plugin_event,
    ids.PLUGIN_NAME: _h_plugin_event,
    ids.PLUGIN_WRAPPER: _h_plugin_event,
    ids.PLUGIN_DATA: _h_plugin_event,
    ids.PATTERN_NAME: _h_pattern_name,
    ids.PATTERN_LENGTH: _h_pattern_length,
    ids.PATTERN_NOTES: _h_pattern_notes,
    ids.ARRANGEMENT_NAME: _h_arr_name,
    ids.ARRANGEMENT_PLAYLIST: _h_playlist,
    ids.TRACK_DATA: _h_track_data,
    ids.TRACK_NAME: _h_track_name,
    ids.TIMEMARKER_POSITION: _h_marker_pos,
    ids.TIMEMARKER_NAME: _h_marker_name,
    ids.MIXER_PARAMS: _h_mixer_params,
    ids.INSERT_NAME: _h_insert_name,
    ids.INSERT_FLAGS: _h_insert_flags,
    ids.INSERT_ROUTING: _h_insert_routing,
    ids.SLOT_INDEX: _h_slot_index,
    ids.INSERT_OUTPUT: _h_insert_output,
}


# -- structured payloads -----------------------------------------------------

def _build_plugin(events: list[Event], text) -> PluginInfo:
    internal = ""
    display = None
    data = b""
    for e in events:
        if e.id == ids.PLUGIN_INTERNAL_NAME:
            internal = text(e)
        elif e.id == ids.PLUGIN_NAME:
            display = text(e) or None
        elif e.id == ids.PLUGIN_DATA:
            data = e.data
    plugin = PluginInfo(internal_name=internal, display_name=display, state_size=len(data))
    if internal == "Fruity Wrapper":
        _decode_wrapper(plugin, data)
    return plugin


def _decode_wrapper(plugin: PluginInfo, data: bytes) -> None:
    """Read the identity of a VST/VST3 plugin hosted by Fruity Wrapper.

    The plugin's own state (record 53) is opaque: its parameters are only
    readable by loading the plugin, i.e. inside FL Studio.
    """
    plugin.format = "unknown-wrapper"
    if len(data) < 4:
        return
    pos = 4
    records: dict[int, bytes] = {}
    while pos + 12 <= len(data):
        rid, size = struct.unpack("<IQ", data[pos:pos + 12])
        pos += 12
        if pos + size > len(data):
            break
        records[rid] = data[pos:pos + size]
        pos += size

    def s(rid: int) -> str | None:
        v = records.get(rid)
        return v.decode("utf-8", errors="replace").rstrip("\0") or None if v else None

    plugin.vst_name = s(ids.VST_NAME)
    plugin.vendor = s(ids.VST_VENDOR)
    plugin.path = s(ids.VST_PATH)
    plugin.state_size = len(records.get(ids.VST_STATE, b""))
    if ids.VST_GUID in records or (plugin.path or "").lower().endswith(".vst3"):
        plugin.format = "vst3"
    elif ids.VST_FOURCC in records or (plugin.path or "").lower().endswith(".dll"):
        plugin.format = "vst2"


def _apply_mixer_params(p: FlpProject, data: bytes) -> None:
    inserts = {ins.index: ins for ins in p.inserts}
    for off in range(0, len(data) - 11, 12):
        pid = data[off + 4]
        channel_data = struct.unpack("<H", data[off + 6:off + 8])[0]
        msg = struct.unpack("<i", data[off + 8:off + 12])[0]
        ins = inserts.get((channel_data >> 6) & 0x7F)
        if ins is None:
            continue
        slot_idx = channel_data & 0x3F
        if pid in (ids.MP_SLOT_ENABLED, ids.MP_SLOT_MIX):
            slot = next((s for s in ins.slots if s.index == slot_idx), None)
            if slot is not None:
                if pid == ids.MP_SLOT_ENABLED:
                    slot.enabled = bool(msg)
                else:
                    slot.mix_raw = msg
        elif pid == ids.MP_VOLUME:
            ins.volume_raw = msg
        elif pid == ids.MP_PAN:
            ins.pan_raw = msg
        elif pid == ids.MP_STEREO_SEP:
            ins.stereo_separation_raw = msg
        elif ids.MP_ROUTE_LEVEL_FIRST <= pid <= ids.MP_ROUTE_LEVEL_LAST:
            target = pid - ids.MP_ROUTE_LEVEL_FIRST
            route = next((r for r in ins.routes if r.target == target), None)
            if route is not None:
                route.level_raw = msg


# Playlist items: the same first 32 bytes since FL 12.9, then FL 21 added 28 bytes, FL 2024 (24) another 20,
# FL 26 another 8 (as read by the PyFLP fork Meowrium/PyFLP and by flpkit). (version, size), newest first
PLAYLIST_ITEM_SIZES = ((26,), 88), ((24,), 80), ((21,), 60), ((), 32)


def _playlist_item_size(data: bytes, version: tuple[int, ...] = ()) -> int | None:
    """The item size the project's FL version writes, tried first; a length can be a multiple of
    several sizes, so the constant "pattern base" field (offset 4) of every item decides."""
    if not data:
        return 32
    expected = next(size for since, size in PLAYLIST_ITEM_SIZES if version >= since)
    for size in sorted({size for _, size in PLAYLIST_ITEM_SIZES}, key=lambda s: (s != expected, -s)):
        if len(data) % size == 0 and all(
            struct.unpack("<H", data[off + 4:off + 6])[0] == ids.PATTERN_BASE
            for off in range(0, len(data), size)
        ):
            return size
    return None


def _parse_playlist(p: FlpProject, arr_index: int, data: bytes, max_track: int) -> list[PlaylistClip]:
    size = _playlist_item_size(data, _version_tuple(p.fl_version))
    if size is None:
        p.warnings.append(
            f"Playlist de l'arrangement {arr_index} : format de clips non reconnu "
            f"({len(data)} octets), clips ignorés"
        )
        return []
    clips = []
    for off in range(0, len(data) - size + 1, size):
        (pos, base, item, length, track_rv, group, _u1, _flags, _u2, so, eo) = struct.unpack(
            "<IHHIHH2sH4sff", data[off:off + 32]
        )
        if item > base:
            source, src_idx = "pattern", item - base
        else:
            source, src_idx = "channel", item
        clip = PlaylistClip(
            arrangement=arr_index,
            track=max_track - track_rv + 1,
            position_ticks=pos,
            length_ticks=length,
            source=source,
            source_index=src_idx,
            start_offset=None if so != so else so,  # NaN -> None
            end_offset=None if eo != eo else eo,
            group=group,
            start_seconds=p.ticks_to_seconds(pos),
            length_seconds=p.ticks_to_seconds(length),
        )
        clips.append(clip)
    return clips


def _finalize_channel_kinds(p: FlpProject) -> None:
    for ch in p.channels:
        if ch.type_raw == 5:
            ch.kind = "automation"
        elif ch.type_raw == 3:
            ch.kind = "layer"
        elif ch.plugin is not None and ch.plugin.internal_name:
            ch.kind = "instrument"
        elif ch.type_raw in (0, 2, 4) or ch.sample_path:
            ch.kind = "sampler"


def parse_events(header: FlpHeader, events: list[Event]) -> FlpProject:
    ps = _Parser(header)
    for e in events:
        ps.feed(e)
    return ps.finish()


def parse_bytes(data: bytes) -> FlpProject:
    header, events = read_events(data)
    return parse_events(header, events)
