"""Build small synthetic .flp files for tests.

Only the events Eden reads are written, in the order FL Studio 20 uses
(project info, patterns, channels, arrangements, mixer).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from eden.flp import ids
from eden.flp.events import TEXT


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def ev(event_id: int, value: int | bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-16-le") + b"\0\0"
    if event_id >= TEXT:
        assert isinstance(value, bytes)
        return bytes([event_id]) + _varint(len(value)) + value
    size = 1 if event_id < 64 else 2 if event_id < 128 else 4
    return bytes([event_id]) + int(value).to_bytes(size, "little", signed=int(value) < 0)


def vst_data(name: str, vendor: str, path: str, state: bytes = b"\x01\x02") -> bytes:
    out = bytearray(struct.pack("<I", 10))
    for rid, payload in ((ids.VST_FOURCC, b"abcd"), (ids.VST_NAME, name.encode()),
                         (ids.VST_PATH, path.encode()), (ids.VST_VENDOR, vendor.encode()),
                         (ids.VST_STATE, state)):
        out += struct.pack("<IQ", rid, len(payload)) + payload
    return bytes(out)


@dataclass
class Slot:
    internal: str
    name: str | None = None
    data: bytes = b""
    enabled: bool = True


@dataclass
class Insert:
    name: str | None = None
    routes: tuple[int, ...] = (0,)
    slots: dict[int, Slot] = field(default_factory=dict)
    volume: int = 12800
    pan: int = 0
    enabled: bool = True
    effects_enabled: bool = True


@dataclass
class Chan:
    name: str
    insert: int = 0
    sample_path: str | None = None
    plugin: str | None = None  # generator internal name; None = sampler
    type_raw: int = 4


@dataclass
class Clip:
    track: int  # FL track number (1-based)
    position: int
    length: int
    channel: int | None = None
    pattern: int | None = None


def build_flp(
    channels: list[Chan],
    inserts: list[Insert],
    clips: list[Clip] = (),
    track_names: dict[int, str] | None = None,
    tempo: float = 140.0,
    version: str = "20.8.4.2576",
    n_inserts: int = 127,
    patterns: dict[int, tuple[str, list[int]]] | None = None,
    legacy_items: bool = False,
    item_size: int | None = None,  # playlist items: 60 bytes (FL 21+) by default, 32 legacy, 80 FL 2024/25, 88 FL 26
) -> bytes:
    body = bytearray()
    body += ev(ids.PROJECT_FL_VERSION, version.encode("ascii") + b"\0")
    body += ev(ids.PROJECT_TEMPO, int(round(tempo * 1000)))
    body += ev(ids.PROJECT_TITLE, "Test")
    body += ev(ids.TIME_SIG_NUM, 4) + ev(ids.TIME_SIG_BEAT, 4)

    for idx, (pname, chans) in (patterns or {}).items():
        body += ev(ids.PATTERN_NEW, idx) + ev(ids.PATTERN_NAME, pname)
        notes = b"".join(struct.pack("<IHHIHHBBBBBBBB", 0, 16384, c, 96, 60, 0, 120, 0, 64, 0, 64, 100, 128, 128)
                         for c in chans)
        body += ev(ids.PATTERN_NOTES, notes)

    for i, ch in enumerate(channels):
        body += ev(ids.CHANNEL_NEW, i)
        body += ev(ids.CHANNEL_TYPE, 2 if ch.plugin else ch.type_raw)
        body += ev(ids.PLUGIN_INTERNAL_NAME, ch.plugin or "")
        body += ev(ids.PLUGIN_NAME, ch.name)
        body += ev(ids.CHANNEL_ENABLED, 1)
        body += ev(ids.CHANNEL_ROUTED_TO, ch.insert)
        body += ev(ids.CHANNEL_LEVELS, struct.pack("<iIiIII", 6400, 10000, 0, 256, 0, 0))
        if ch.sample_path:
            body += ev(ids.CHANNEL_SAMPLE_PATH, ch.sample_path)

    body += ev(ids.ARRANGEMENT_NEW, 0)
    body += ev(ids.ARRANGEMENT_NAME, "Arrangement")
    items = bytearray()
    for c in clips:
        item = c.channel if c.channel is not None else ids.PATTERN_BASE + c.pattern
        items += struct.pack("<IHHIHH2sH4sff", c.position, ids.PATTERN_BASE, item, c.length,
                             499 - (c.track - 1), 0, b"\x78\x00", 64, b"\x40\x64\x80\x80", -1.0, -1.0)
        items += b"\0" * ((item_size or (32 if legacy_items else 60)) - 32)  # what later FL versions added
    body += ev(ids.ARRANGEMENT_PLAYLIST, bytes(items))
    for t in range(1, 501):
        body += ev(ids.TRACK_DATA, struct.pack("<III", t, 0, 0) + b"\x01" + b"\0" * 53)
        if track_names and t in track_names:
            body += ev(ids.TRACK_NAME, track_names[t])

    params = bytearray()
    for idx in range(n_inserts):
        ins = inserts[idx] if idx < len(inserts) else Insert(routes=(0,) if idx else ())
        if ins.name:
            body += ev(ids.INSERT_NAME, ins.name)
        flags = (ids.INSERT_FLAG_ENABLED if ins.enabled else 0) | (
            ids.INSERT_FLAG_EFFECTS_ON if ins.effects_enabled else 0)
        body += ev(ids.INSERT_FLAGS, struct.pack("<III", 0, flags, 0))
        for s in range(10):
            slot = ins.slots.get(s)
            if slot:
                body += ev(ids.PLUGIN_INTERNAL_NAME, slot.internal)
                if slot.name:
                    body += ev(ids.PLUGIN_NAME, slot.name)
                body += ev(ids.PLUGIN_DATA, slot.data)
                params += struct.pack("<4sBBHi", b"\0" * 4, ids.MP_SLOT_ENABLED, 31,
                                      (idx << 6) | s, int(slot.enabled))
            body += ev(ids.SLOT_INDEX, s)
        routing = bytes(1 if (t in ins.routes and t != idx) else 0 for t in range(n_inserts))
        body += ev(ids.INSERT_ROUTING, routing)
        body += ev(ids.INSERT_INPUT, -1)
        body += ev(ids.INSERT_OUTPUT, -1)
        params += struct.pack("<4sBBHi", b"\0" * 4, ids.MP_VOLUME, 31, idx << 6, ins.volume)
        params += struct.pack("<4sBBHi", b"\0" * 4, ids.MP_PAN, 31, idx << 6, ins.pan)

    # FL writes the mixer parameters before the inserts; position does not matter to Eden.
    body = bytearray(ev(ids.MIXER_PARAMS, bytes(params))) + body

    header = b"FLhd" + struct.pack("<IhHH", 6, 0, len(channels), 96)
    return header + b"FLdt" + struct.pack("<I", len(body)) + bytes(body)
