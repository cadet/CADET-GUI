from __future__ import annotations

import re
from html import escape

__all__ = ["unit_html"]

_SYMBOLS = {"cdot": "·", "times": "×", ",": " ", " ": " "}
_TEXT_COMMANDS = ("mathrm", "text", "textrm")
_SCRIPT = re.compile(r"<(sup|sub)>.*?</\1>")


def _top_level(html: str) -> str:
    return _SCRIPT.sub("", html)


def unit_html(src: str) -> str:
    r"""Render a unit in the LaTeX subset CADET-Process uses (`\frac`, `^`, `_`) as HTML.

    Mirrors `elements/_unit_parser.js`, so units read the same in tables and fields.
    """
    pos = 0

    def arg() -> str:
        nonlocal pos
        while pos < len(src) and src[pos] == " ":
            pos += 1
        if pos >= len(src):
            return ""
        if src[pos] == "{":
            pos += 1
            return seq(until_brace=True)
        if src[pos] == "\\":
            return command()
        pos += 1
        return escape(src[pos - 1])

    def command() -> str:
        nonlocal pos
        pos += 1
        end = pos
        while end < len(src) and src[end].isalpha():
            end += 1
        name = src[pos:end] or src[pos : pos + 1]
        pos += len(name)
        if name in _TEXT_COMMANDS:
            return arg()
        if name == "frac":
            num, den = arg(), arg()
            num = f"({num})" if "/" in _top_level(num) else num
            den = f"({den})" if any(c in _top_level(den) for c in "·×/") else den
            return f"{num}/{den}"
        return _SYMBOLS.get(name, escape(f"\\{name}"))

    def seq(until_brace: bool = False) -> str:
        nonlocal pos
        out = []
        while pos < len(src):
            ch = src[pos]
            if ch == "}" and until_brace:
                pos += 1
                break
            if ch == "{":
                pos += 1
                out.append(seq(until_brace=True))
            elif ch == "\\":
                out.append(command())
            elif ch in "^_":
                pos += 1
                tag = "sup" if ch == "^" else "sub"
                out.append(f"<{tag}>{arg()}</{tag}>")
            else:
                out.append(escape(ch))
                pos += 1
        return "".join(out)

    return seq()
