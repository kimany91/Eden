"""Serialize an FLP event list back to bytes.

Used only to build Eden's *working copies* of a project (render copies with
some tracks muted, sample paths repaired...). The user's original .flp is
never passed to this module's output path.
"""

from __future__ import annotations

import struct

from eden.flp.events import DATA_MAGIC, HEADER_MAGIC, TEXT, Event, FlpHeader, payload_size


def encode_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def encode_event(event_id: int, data: bytes) -> bytes:
    size = payload_size(event_id)
    if size is None:
        return bytes([event_id]) + encode_varint(len(data)) + data
    if len(data) != size:
        raise ValueError(f"l'événement {event_id} attend {size} octet(s), reçu {len(data)}")
    return bytes([event_id]) + data


def encode_text(text: str, unicode: bool = True) -> bytes:
    if unicode:
        return text.encode("utf-16-le") + b"\0\0"
    return text.encode("latin-1", errors="replace") + b"\0"


def serialize(header: FlpHeader, events: list[Event], channel_count: int | None = None) -> bytes:
    body = b"".join(encode_event(e.id, e.data) for e in events)
    head = HEADER_MAGIC + struct.pack(
        "<IhHH", 6, header.format,
        header.channel_count if channel_count is None else channel_count, header.ppq,
    )
    return head + DATA_MAGIC + struct.pack("<I", len(body)) + body


def make_event(event_id: int, data: bytes) -> Event:
    if event_id < TEXT:
        encode_event(event_id, data)  # validates the size
    return Event(event_id, data, offset=-1)
