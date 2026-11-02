"""Locations of diary data and small date helpers."""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def default_data_dir() -> Path:
    """`data/` inside the source checkout (gitignored) when running from one, else ~/diary."""
    if (REPO_ROOT / "pyproject.toml").exists():
        return REPO_ROOT / "data"
    return Path("~/diary").expanduser()


def data_dir() -> Path:
    """Root of the diary data. Override with $DIARY_DIR."""
    env = os.environ.get("DIARY_DIR")
    root = Path(env).expanduser() if env else default_data_dir()
    (root / "logs").mkdir(parents=True, exist_ok=True)
    return root


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file + rename, so a crash never leaves a truncated file."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def todos_path() -> Path:
    return data_dir() / "todos.md"


def projects_path() -> Path:
    return data_dir() / "projects.md"


def log_path(day: date) -> Path:
    return data_dir() / "logs" / f"{day.isoformat()}.md"


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_day(text: str, today: date | None = None, future: bool = False) -> date:
    """Parse a date: YYYY-MM-DD, today/yesterday/tomorrow, a weekday (mon, friday, ...),
    or an offset like 3d / 2w / 1m.

    `future` picks the direction for weekdays and unsigned offsets: due dates look ahead
    ("fri" = the next Friday after today, "3d" = in 3 days); --since / --date look back
    ("fri" = the most recent Friday, today included; "3d" = 3 days ago). "+3d" / "-3d"
    always mean ahead / back.
    """
    today = today or date.today()
    text = text.strip().lower()
    if text == "today":
        return today
    if text == "yesterday":
        return today - timedelta(days=1)
    if text == "tomorrow":
        return today + timedelta(days=1)
    m = re.fullmatch(r"([+-]?)(\d+)([dwm])", text)
    if m:
        sign, n, unit = m.groups()
        delta = timedelta(days=int(n) * {"d": 1, "w": 7, "m": 30}[unit])
        ahead = sign == "+" or (sign == "" and future)
        return today + delta if ahead else today - delta
    weekday = next((i for i, name in enumerate(WEEKDAYS) if len(text) >= 3 and name.startswith(text)), None)
    if weekday is not None:
        if future:
            return today + timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)
        return today - timedelta(days=(today.weekday() - weekday) % 7)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"unrecognised date {text!r} "
                         "(use YYYY-MM-DD, today, tomorrow, yesterday, a weekday like fri, or 3d / 2w / 1m)")
