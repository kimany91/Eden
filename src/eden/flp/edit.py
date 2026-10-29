"""Edit an in-memory copy of a project to prepare FL Studio renders.

Supported edits are the minimum Eden needs: isolate parts of the mix (mute
an insert or a channel, cut a route, bypass an insert's effects), repair a
sample path, and add an audio channel + playlist clip (to play Eden's mix
through the project's own Master chain). Every edit works on events located with the same rules as the
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
        self.channel_count = self.header.channel_count

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

    def audio_channel_templates(self) -> list[int]:
        """Channels that play an audio file, best template first (audio clips)."""
        ranges = self._channel_ranges()
        out = []
        for ch, (start, end) in ranges.items():
            evs = self.events[start:end]
            if not any(e.id == ids.CHANNEL_SAMPLE_PATH for e in evs):
                continue
            plugin = next((e.data for e in evs if e.id == ids.PLUGIN_INTERNAL_NAME), b"")
            if plugin.replace(b"\0", b""):
                continue  # a generator plugin, not a plain sampler
            ctype = next((e.data[0] for e in evs if e.id == ids.CHANNEL_TYPE), None)
            out.append((0 if ctype == 4 else 1, ch))
        return [ch for _, ch in sorted(out)]

    def add_audio_channel(self, sample_path: str, name: str, template: int | None = None) -> int:
        """Duplicate an existing audio channel so that it plays ``sample_path``
        straight into the Master at default level. Returns the new channel index."""
        ranges = self._channel_ranges()
        if template is None:
            candidates = self.audio_channel_templates()
            if not candidates:
                raise FlpEditError("Aucun canal audio à dupliquer dans ce projet")
            template = candidates[0]
        start, end = ranges[template]
        new_index = max(ranges) + 1
        last_end = max(e for _, e in ranges.values())
        clone: list[Event] = []
        has_name = False
        for e in self.events[start:end]:
            if e.id == ids.CHANNEL_NEW:
                e = make_event(e.id, new_index.to_bytes(2, "little"))
            elif e.id == ids.CHANNEL_SAMPLE_PATH:
                e = make_event(e.id, encode_text(sample_path, self.unicode))
            elif e.id == ids.PLUGIN_NAME:
                e, has_name = make_event(e.id, encode_text(name, self.unicode)), True
            elif e.id == ids.CHANNEL_ROUTED_TO:
                e = make_event(e.id, bytes([0]))
            elif e.id == ids.CHANNEL_ENABLED:
                e = make_event(e.id, bytes([1]))
            elif e.id == ids.CHANNEL_LEVELS and len(e.data) >= 8:
                e = make_event(e.id, struct.pack("<iI", 6400, 10000) + e.data[8:])
            clone.append(e)
        if not has_name:
            clone.insert(1, make_event(ids.PLUGIN_NAME, encode_text(name, self.unicode)))
        self.events[last_end:last_end] = clone
        self.channel_count += 1
        self.changes.append(f"canal {new_index} ajouté ({name}) d'après le canal {template}")
        return new_index

    def _arrangement_playlist(self) -> int:
        """Position of the playlist event of the current arrangement (created if absent)."""
        current = next((e.as_int() for e in self.events if e.id == ids.ARRANGEMENTS_CURRENT), 0)
        starts = [(e.as_int(), pos) for pos, e in enumerate(self.events) if e.id == ids.ARRANGEMENT_NEW]
        if not starts:
            raise FlpEditError("Le projet ne contient aucun arrangement")
        index, start = next(((i, p) for i, p in starts if i == current), starts[0])
        nxt = [p for _, p in starts if p > start]
        end = min(nxt) if nxt else len(self.events)
        for pos in range(start, end):
            if self.events[pos].id == ids.ARRANGEMENT_PLAYLIST:
                return pos
        self.events.insert(start + 1, make_event(ids.ARRANGEMENT_PLAYLIST, b""))
        return start + 1

    def add_playlist_clip(self, channel: int, position: int, length: int) -> int:
        """Place ``channel`` on the first empty playlist track from the bottom.
        Returns the FL track number used."""
        from eden.flp.parser import _playlist_item_size

        pos = self._arrangement_playlist()
        data = self.events[pos].data
        size = _playlist_item_size(data)
        if size is None:
            raise FlpEditError("Playlist illisible : impossible d'y ajouter un clip")
        version = next((e.data.decode("ascii", "replace").rstrip("\0") for e in self.events
                        if e.id == ids.PROJECT_FL_VERSION), None)
        max_track = 499 if _version_tuple(version) >= (12, 9, 1) else 198
        if not data:
            size = 60 if _version_tuple(version) >= (21,) else 32
        used = {max_track - struct.unpack("<H", data[o + 12:o + 14])[0]
                for o in range(0, len(data), size)}
        free = next((t for t in range(max_track, -1, -1) if t not in used), None)
        if free is None:
            raise FlpEditError("Aucune piste de playlist libre")
        template = next((data[o:o + size] for o in range(0, len(data), size)
                         if struct.unpack("<H", data[o + 6:o + 8])[0] < ids.PATTERN_BASE), None)
        if template is None:
            template = (struct.pack("<IHHIHH2sH4sff", 0, ids.PATTERN_BASE, 0, 0, 0, 0, b"\x78\x00",
                                    64, b"\x40\x64\x80\x80", -1.0, -1.0)
                        + b"\0" * (size - 32))
        item = bytearray(template)
        struct.pack_into("<IHHIHH", item, 0, position, ids.PATTERN_BASE, channel, length,
                         max_track - free, 0)
        self.events[pos] = make_event(ids.ARRANGEMENT_PLAYLIST, data + bytes(item))
        self.changes.append(f"clip du canal {channel} ajouté sur la piste {free + 1}")
        return free + 1

    # -- output ----------------------------------------------------------
    def to_bytes(self) -> bytes:
        data = serialize(self.header, self.events, channel_count=self.channel_count)
        header, events = read_events(data)  # the copy must stay readable
        parse_events(header, events)
        return data
