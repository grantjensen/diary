"""ANSI colours for terminal output.

On when stdout is a terminal; off when piped. Override with DIARY_COLOR=always|never
(NO_COLOR is also respected).
"""

from __future__ import annotations

import os
import re
import sys

_CODES = {
    "bold": "1", "dim": "2",
    "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36",
}
PROJECT_COLOR = "38;5;209"  # coral (256-colour); red/yellow stay reserved for p1/overdue and due today


def enabled() -> bool:
    setting = os.environ.get("DIARY_COLOR", "").lower()
    if setting in {"always", "1", "yes"}:
        return True
    if setting in {"never", "0", "no"} or "NO_COLOR" in os.environ:
        return False
    return sys.stdout.isatty()


def paint(text: str, *styles: str) -> str:
    if not text or not styles or not enabled():
        return text
    codes = ";".join(_CODES.get(s, s) for s in styles)
    return f"\033[{codes}m{text}\033[0m"


def project(name: str, bold: bool = False) -> str:
    return paint(name, *(["bold"] if bold else []), PROJECT_COLOR)


def priority(p: int | None) -> str:
    if not p:
        return "  "
    return paint(f"p{p}", {1: "red", 2: "yellow", 3: "blue"}[p], *(["bold"] if p == 1 else []))


_HEADING_RE = re.compile(r"^(#{1,2})\s+(.*)$")
_BULLET_TIME_RE = re.compile(r"^(\s*[-*]\s+)(\d{1,2}:\d{2})(\s+)(done #\d+:|merged [\w.-]+#\d+:)?")


def log_text(text: str, reserved: set[str]) -> str:
    """Colour a daily log: date title, project headings in their colours, timestamps, completed todos."""
    if not enabled():
        return text
    out = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m and m.group(1) == "#":
            line = paint(line, "bold")
        elif m:
            name = m.group(2).strip()
            line = paint("## ", "dim") + (paint(name, "bold") if name.lower() in reserved
                                          else project(name.lower(), bold=True))
        else:
            b = _BULLET_TIME_RE.match(line)
            if b:
                done = paint(b.group(4), "green") if b.group(4) else ""
                line = b.group(1) + paint(b.group(2), "dim") + b.group(3) + done + line[b.end():]
        out.append(line)
    return "\n".join(out)
