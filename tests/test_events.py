import struct

import pytest

from eden.flp.events import FlpFormatError, read_events
from flp_builder import ev


def _file(body: bytes, ppq: int = 96, data_size: int | None = None) -> bytes:
    size = len(body) if data_size is None else data_size
    return b"FLhd" + struct.pack("<IhHH", 6, 0, 1, ppq) + b"FLdt" + struct.pack("<I", size) + body


def test_event_sizes_and_varint():
    long_text = "x" * 200  # > 127 bytes once encoded: needs a 2-byte varint
    body = ev(9, 1) + ev(66, 300) + ev(156, 140000) + ev(194, long_text)
    header, events = read_events(_file(body))
    assert header.ppq == 96
    assert [e.id for e in events] == [9, 66, 156, 194]
    assert events[1].as_int() == 300
    assert events[2].as_int() == 140000
    assert events[3].data.decode("utf-16-le").rstrip("\0") == long_text


@pytest.mark.parametrize("data,msg", [
    (b"RIFF0000", "FLhd"),
    (b"FLhd" + struct.pack("<IhHH", 8, 0, 1, 96), "En-tête"),
    (b"FLhd" + struct.pack("<IhHH", 6, 0, 1, 96) + b"XXXX", "FLdt"),
])
def test_rejects_non_flp(data, msg):
    with pytest.raises(FlpFormatError, match=msg):
        read_events(data + b"\0" * 8)


def test_truncated_file_is_reported():
    body = ev(156, 140000)
    with pytest.raises(FlpFormatError, match="tronqué"):
        read_events(_file(body, data_size=len(body) + 50))


def test_event_overflowing_data_chunk():
    body = bytes([200]) + bytes([100]) + b"abc"  # announces 100 bytes, has 3
    with pytest.raises(FlpFormatError):
        read_events(_file(body))
