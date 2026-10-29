"""Low-level reader for the FL Studio project (.flp) container.

An .flp file is a RIFF-like container:

    "FLhd" | u32 header size (=6) | u16 format | u16 channel count | u16 PPQ
    "FLdt" | u32 data size        | event stream

Each event starts with a one-byte ID whose range gives the payload size:

    0..63    -> 1 byte
    64..127  -> 2 bytes
    128..191 -> 4 bytes
    192..255 -> variable length, prefixed by a 7-bit varint (LEB128)

This module only splits the stream into events. It never writes anything
and never interprets plugin states.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

WORD = 64
DWORD = 128
TEXT = 192
DATA = 208

HEADER_MAGIC = b"FLhd"
DATA_MAGIC = b"FLdt"


class FlpFormatError(ValueError):
    """The file is not a readable FL Studio project."""


@dataclass(frozen=True)
class FlpHeader:
    format: int
    channel_count: int
    ppq: int
    data_size: int


@dataclass(frozen=True)
class Event:
    id: int
    data: bytes
    offset: int  # byte offset of the event ID in the file, for diagnostics

    def as_int(self, signed: bool = False) -> int:
        if self.id >= TEXT:
            raise TypeError(f"event {self.id} has a variable-length payload")
        return int.from_bytes(self.data, "little", signed=signed)


def payload_size(event_id: int) -> int | None:
    """Fixed payload size for an event ID, or None if variable-length."""
    if event_id < WORD:
        return 1
    if event_id < DWORD:
        return 2
    if event_id < TEXT:
        return 4
    return None


def _read_exact(stream: BinaryIO, size: int, what: str) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise FlpFormatError(f"Fichier tronqué : {what} incomplet")
    return data


def _read_varint(stream: BinaryIO) -> int:
    value = 0
    shift = 0
    while True:
        byte = stream.read(1)
        if not byte:
            raise FlpFormatError("Fichier tronqué : taille d'événement incomplète")
        b = byte[0]
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value
        shift += 7
        if shift > 35:
            raise FlpFormatError("Taille d'événement invalide (varint trop long)")


def read_header(stream: BinaryIO) -> FlpHeader:
    if _read_exact(stream, 4, "en-tête") != HEADER_MAGIC:
        raise FlpFormatError("Ce fichier n'est pas un projet FL Studio (signature FLhd absente)")
    header_size = struct.unpack("<I", _read_exact(stream, 4, "en-tête"))[0]
    if header_size != 6:
        raise FlpFormatError(f"En-tête FLP inattendu (taille {header_size}, attendu 6)")
    fmt, channel_count, ppq = struct.unpack("<hHH", _read_exact(stream, 6, "en-tête"))
    if _read_exact(stream, 4, "bloc de données") != DATA_MAGIC:
        raise FlpFormatError("Bloc de données FLdt absent")
    data_size = struct.unpack("<I", _read_exact(stream, 4, "bloc de données"))[0]
    if ppq == 0:
        raise FlpFormatError("PPQ invalide (0)")
    return FlpHeader(format=fmt, channel_count=channel_count, ppq=ppq, data_size=data_size)


def iter_events(stream: BinaryIO, header: FlpHeader) -> Iterator[Event]:
    """Yield events from a stream positioned right after the FLdt size field."""
    start = stream.tell()
    end = start + header.data_size
    while stream.tell() < end:
        offset = stream.tell()
        event_id = _read_exact(stream, 1, "identifiant d'événement")[0]
        size = payload_size(event_id)
        if size is None:
            size = _read_varint(stream)
        if stream.tell() + size > end:
            raise FlpFormatError(f"Événement {event_id} à l'octet {offset} dépasse la fin des données")
        yield Event(event_id, _read_exact(stream, size, f"événement {event_id}"), offset)


def read_events(data: bytes) -> tuple[FlpHeader, list[Event]]:
    """Parse a complete .flp file held in memory."""
    import io

    stream = io.BytesIO(data)
    header = read_header(stream)
    if 22 + header.data_size > len(data):
        raise FlpFormatError(
            f"Fichier tronqué : {len(data)} octets, {22 + header.data_size} annoncés"
        )
    return header, list(iter_events(stream, header))
