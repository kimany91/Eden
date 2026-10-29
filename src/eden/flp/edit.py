"""Edit an in-memory copy of a project to prepare FL Studio renders.

Supported edits are the minimum Eden needs to have FL Studio render one part
of the song at a time: mute an insert or a channel, cut a route, bypass an
insert's effects or a single effect slot, and repair a sample path. Every edit works on events located with the same rules as the
parser, and the result is checked by re-parsing it.
"""

from __future__ import annotations

import struct

from eden.flp import ids
from eden.flp.events import Event, FlpHeader, read_events
from eden.flp.parser import _version_tuple, parse_events
from eden.flp.writer import encode_text, make_event, serialize


class FlpEditError(RuntimeError):
    pass


class FlpEditor:
    def __init__(self, data: bytes) -> None:
        self.header: FlpHeader
        self.header, events = read_events(data)
        self.events: list[Event] = list(events)
        version = next(
            (e.data.decode("ascii", "replace").rstrip("\0") for e in self.events
             if e.id == ids.PROJECT_FL_VERSION), None,
        )
        self.unicode = _version_tuple(version) >= (11, 5) if version else True
        self.changes: list[str] = []

    # -- locating events -------------------------------------------------
    def _channel_ranges(self) -> dict[int, tuple[int, int]]:
        """Channel index -> [start, end) range of its events in the stream."""
        ranges: dict[int, tuple[int, int]] = {}
        current: int | None = None
        start = 0
        for pos, e in enumerate(self.events):
            opener = e.id in (ids.CHANNEL_NEW, ids.PATTERN_NEW, ids.ARRANGEMENT_NEW,
                              ids.INSERT_NAME, ids.INSERT_FLAGS, ids.MIXER_PARAMS)
            if opener and current is not None:
                ranges.setdefault(current, (start, pos))
                current = None
            if e.id == ids.CHANNEL_NEW:
                current, start = e.as_int(), pos
        if current is not None:
            ranges.setdefault(current, (start, len(self.events)))
        return ranges

    def _insert_event_positions(self, event_id: int) -> list[int | None]:
        """Position of ``event_id`` within each insert (index 0 = Master)."""
        positions: list[int | None] = []
        pending: int | None = None
        for pos, e in enumerate(self.events):
            if e.id == event_id:
                pending = pos
            elif e.id == ids.INSERT_OUTPUT:
                positions.append(pending)
                pending = None
        return positions

    def _insert_flag_positions(self) -> list[int]:
        """Position of the INSERT_FLAGS event of each insert (index 0 = Master)."""
        positions: list[int] = []
        pending: int | None = None
        for pos, e in enumerate(self.events):
            if e.id == ids.INSERT_FLAGS:
                pending = pos
            elif e.id == ids.INSERT_OUTPUT:
                if pending is None:
                    raise FlpEditError(f"Insert {len(positions)} sans drapeaux : copie impossible")
                positions.append(pending)
                pending = None
        return positions

    # -- edits ---------------------------------------------------------------
    def _set_insert_flag(self, insert: int, bit: int, on: bool, label: str) -> None:
        positions = self._insert_flag_positions()
        if not 0 <= insert < len(positions):
            raise FlpEditError(f"Insert {insert} inexistant")
        pos = positions[insert]
        data = bytearray(self.events[pos].data)
        if len(data) < 8:
            raise FlpEditError(f"Drapeaux de l'insert {insert} illisibles")
        flags = struct.unpack("<I", data[4:8])[0]
        new = flags | bit if on else flags & ~bit
        if new != flags:
            data[4:8] = struct.pack("<I", new)
            self.events[pos] = make_event(ids.INSERT_FLAGS, bytes(data))
            self.changes.append(f"{label} insert {insert} : {'oui' if on else 'non'}")

    def set_insert_enabled(self, insert: int, enabled: bool) -> None:
        self._set_insert_flag(insert, ids.INSERT_FLAG_ENABLED, enabled, "activé")

    def set_insert_effects_enabled(self, insert: int, enabled: bool) -> None:
        self._set_insert_flag(insert, ids.INSERT_FLAG_EFFECTS_ON, enabled, "effets actifs")

    def set_route(self, insert: int, target: int, enabled: bool) -> None:
        """Enable or cut the route from ``insert`` to ``target`` (0 = Master)."""
        positions = self._insert_event_positions(ids.INSERT_ROUTING)
        if not 0 <= insert < len(positions) or positions[insert] is None:
            raise FlpEditError(f"Routage de l'insert {insert} introuvable")
        pos = positions[insert]
        data = bytearray(self.events[pos].data)
        if not 0 <= target < len(data):
            raise FlpEditError(f"Destination {target} hors limites pour l'insert {insert}")
        value = 1 if enabled else 0
        if data[target] != value:
            data[target] = value
            self.events[pos] = make_event(ids.INSERT_ROUTING, bytes(data))
            self.changes.append(f"route {insert} → {target} : {'oui' if enabled else 'coupée'}")

    def set_slot_enabled(self, insert: int, slot: int, enabled: bool) -> None:
        """Enable or bypass one effect slot of an insert (its state record in MIXER_PARAMS)."""
        pos = next((i for i, e in enumerate(self.events) if e.id == ids.MIXER_PARAMS), None)
        if pos is None:
            raise FlpEditError("Paramètres du mixeur introuvables")
        data = bytearray(self.events[pos].data)
        for off in range(0, len(data) - 11, 12):
            channel_data = struct.unpack("<H", data[off + 6:off + 8])[0]
            if data[off + 4] == ids.MP_SLOT_ENABLED and (channel_data >> 6) & 0x7F == insert \
                    and channel_data & 0x3F == slot:
                value = 1 if enabled else 0
                if struct.unpack("<i", data[off + 8:off + 12])[0] != value:
                    data[off + 8:off + 12] = struct.pack("<i", value)
                    self.events[pos] = make_event(ids.MIXER_PARAMS, bytes(data))
                    self.changes.append(f"slot {slot} de l'insert {insert} : "
                                        f"{'actif' if enabled else 'contourné'}")
                return
        raise FlpEditError(f"État du slot {slot} de l'insert {insert} introuvable")

    def set_channel_enabled(self, channel: int, enabled: bool) -> None:
        ranges = self._channel_ranges()
        if channel not in ranges:
            raise FlpEditError(f"Canal {channel} inexistant")
        start, end = ranges[channel]
        new = make_event(ids.CHANNEL_ENABLED, bytes([1 if enabled else 0]))
        for pos in range(start, end):
            if self.events[pos].id == ids.CHANNEL_ENABLED:
                if self.events[pos].data != new.data:
                    self.events[pos] = new
                    self.changes.append(f"canal {channel} activé : {'oui' if enabled else 'non'}")
                return
        self.events.insert(start + 1, new)
        self.changes.append(f"canal {channel} activé : {'oui' if enabled else 'non'}")

    def set_sample_path(self, channel: int, path: str) -> None:
        ranges = self._channel_ranges()
        if channel not in ranges:
            raise FlpEditError(f"Canal {channel} inexistant")
        start, end = ranges[channel]
        for pos in range(start, end):
            if self.events[pos].id == ids.CHANNEL_SAMPLE_PATH:
                self.events[pos] = make_event(ids.CHANNEL_SAMPLE_PATH, encode_text(path, self.unicode))
                self.changes.append(f"chemin du canal {channel} → {path}")
                return
        raise FlpEditError(f"Le canal {channel} n'a pas de fichier audio")

    # -- output ----------------------------------------------------------
    def to_bytes(self) -> bytes:
        data = serialize(self.header, self.events)
        header, events = read_events(data)  # the copy must stay readable
        parse_events(header, events)
        return data
