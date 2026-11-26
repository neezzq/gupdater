"""Just enough of the protobuf wire format to read Battle.net's ``product.db``.

There is no schema here: messages are walked generically and anything that
does not parse cleanly is ignored, so a format change makes the data
disappear rather than crash the scan.
"""

from __future__ import annotations

from typing import Iterator

Field = tuple[int, int, object]  # (field number, wire type, int or bytes)


def _varint(data: bytes, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if i >= len(data) or shift > 63:
            raise ValueError("bad varint")
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7


def fields(data: bytes) -> list[Field] | None:
    """All fields of a message, or None if ``data`` is not a well-formed message."""
    out: list[Field] = []
    i, n = 0, len(data)
    try:
        while i < n:
            key, i = _varint(data, i)
            number, wire = key >> 3, key & 7
            if number == 0:
                return None
            if wire == 0:
                value, i = _varint(data, i)
            elif wire == 1:
                value, i = data[i:i + 8], i + 8
            elif wire == 2:
                length, i = _varint(data, i)
                if i + length > n:
                    return None
                value, i = data[i:i + length], i + length
            elif wire == 5:
                value, i = data[i:i + 4], i + 4
            else:
                return None
            out.append((number, wire, value))
    except ValueError:
        return None
    return out if i == n else None


def text(value: object) -> str | None:
    if not isinstance(value, bytes):
        return None
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return decoded if decoded.isprintable() else None


def strings(data: bytes, depth: int = 4) -> Iterator[str]:
    """Every readable string in a message and its nested messages."""
    parsed = fields(data)
    if not parsed:
        return
    for _, wire, value in parsed:
        if wire != 2:
            continue
        decoded = text(value)
        if decoded:
            yield decoded
        if depth > 0:
            yield from strings(value, depth - 1)
