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


def todos_path() -> Path:
    return data_dir() / "todos.md"


def projects_path() -> Path:
    return data_dir() / "projects.md"


def log_path(day: date) -> Path:
    return data_dir() / "logs" / f"{day.isoformat()}.md"


def parse_day(text: str, today: date | None = None) -> date:
    """Parse 'today', 'yesterday', 'tomorrow', 'YYYY-MM-DD', or a relative offset like '3d' / '2w' (in the past)."""
    today = today or date.today()
    text = text.strip().lower()
    if text == "today":
        return today
    if text == "yesterday":
        return today - timedelta(days=1)
    if text == "tomorrow":
        return today + timedelta(days=1)
    m = re.fullmatch(r"(\d+)([dwm])", text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return today - timedelta(days=n * {"d": 1, "w": 7, "m": 30}[unit])
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"unrecognised date {text!r} (use YYYY-MM-DD, today, yesterday, 7d, 2w, 3m)")
