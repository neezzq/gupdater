"""Parser for Valve's text KeyValues format (``*.vdf``, ``*.acf``).

Keys are lower-cased so lookups do not depend on Steam's inconsistent casing
(``StateFlags`` vs ``stateflags``); values keep their case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


class VdfError(ValueError):
    pass


def _tokens(text: str) -> Iterator[tuple[str, str]]:
    """Yield ("str", value), ("{", "{") or ("}", "}")."""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end + 1
        elif ch in "{}":
            yield ch, ch
            i += 1
        elif ch == '"':
            i += 1
            out = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    out.append(_ESCAPES.get(nxt, "\\" + nxt))
                    i += 2
                else:
                    out.append(text[i])
                    i += 1
            i += 1  # closing quote
            yield "str", "".join(out)
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in '{}"':
                i += 1
            word = text[start:i]
            # Platform conditionals like [$WIN32] are not keys or values.
            if not (word.startswith("[") and word.endswith("]")):
                yield "str", word


def loads(text: str) -> dict:
    tokens = _tokens(text.lstrip("﻿"))

    def parse_object(top: bool) -> dict:
        obj: dict = {}
        while True:
            tok = next(tokens, None)
            if tok is None:
                if top:
                    return obj
                raise VdfError("unexpected end of file")
            kind, key = tok
            if kind == "}":
                if top:
                    raise VdfError("unexpected '}'")
                return obj
            if kind == "{":
                raise VdfError("unexpected '{'")
            value = next(tokens, None)
            if value is None:
                raise VdfError(f"key {key!r} has no value")
            if value[0] == "{":
                obj[key.lower()] = parse_object(top=False)
            elif value[0] == "str":
                obj[key.lower()] = value[1]
            else:
                raise VdfError(f"unexpected '}}' after key {key!r}")

    return parse_object(top=True)


def load(path: Path) -> dict:
    return loads(path.read_text(encoding="utf-8", errors="replace"))
