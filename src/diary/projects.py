"""Projects: an open/closed registry (projects.md) plus history assembled from daily logs and todos.

Any project name used in a log heading or a todo counts as a project; it is open unless
it has been closed with `diary projects close`. projects.md looks like:

    ## Open
    - api

    ## Closed
    - old-thing (closed 2026-10-30)
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import logs, store
from .todos import TodoList

ENTRY_RE = re.compile(r"^\s*[-*]\s+([\w.-]+)(?:\s+\(closed (\d{4}-\d{2}-\d{2})\))?\s*$")
HEADER = "# Projects\n\n<!-- Managed by `diary projects add/close/reopen`, but safe to hand-edit. -->\n\n"


class Registry:
    """Explicitly added or closed projects. Maps name -> closed date (None = open)."""

    def __init__(self, path: Path | None = None):
        self.path = path or store.projects_path()
        self.entries: dict[str, date | None] = {}
        if not self.path.exists():
            return
        section = "open"
        for line in self.path.read_text().splitlines():
            heading = logs.HEADING_RE.match(line)
            if heading:
                section = heading.group(1).strip().lower()
                continue
            m = ENTRY_RE.match(line)
            if m:
                closed = date.fromisoformat(m.group(2)) if m.group(2) else (date.min if section == "closed" else None)
                self.entries[m.group(1).lower()] = closed

    def save(self) -> None:
        open_names = sorted(n for n, c in self.entries.items() if c is None)
        closed = sorted((n, c) for n, c in self.entries.items() if c is not None)
        body = HEADER + "## Open\n\n" + "".join(f"- {n}\n" for n in open_names)
        body += "\n## Closed\n\n" + "".join(
            f"- {n}" + (f" (closed {c.isoformat()})" if c != date.min else "") + "\n" for n, c in closed)
        self.path.write_text(body)

    def closed(self, name: str) -> date | None:
        return self.entries.get(name.lower())


@dataclass
class ProjectHistory:
    name: str
    days: dict[date, str] = field(default_factory=dict)  # day -> that day's section text
    open_todos: int = 0
    done_todos: int = 0
    closed: date | None = None

    @property
    def is_open(self) -> bool:
        return self.closed is None

    @property
    def first(self) -> date | None:
        return min(self.days) if self.days else None

    @property
    def last(self) -> date | None:
        return max(self.days) if self.days else None


def collect(since: date | None = None, until: date | None = None,
            todo_list: TodoList | None = None) -> dict[str, ProjectHistory]:
    registry = Registry()
    projects: dict[str, ProjectHistory] = {}

    def get(name: str) -> ProjectHistory:
        return projects.setdefault(name, ProjectHistory(name, closed=registry.closed(name)))

    for name in registry.entries:
        get(name)

    for day in logs.all_days(since, until):
        for name, text in logs.DayLog(day).project_sections().items():
            get(name).days[day] = text

    for t in (todo_list or TodoList()).items:
        for name in filter(None, [t.project, *t.extra_projects]):
            if t.is_done:
                get(name).done_todos += 1
            else:
                get(name).open_todos += 1
    return projects


def known_names(status: str = "all") -> list[str]:
    """Project names; status is 'all', 'open' or 'closed'."""
    return sorted(name for name, p in collect().items()
                  if status == "all" or p.is_open == (status == "open"))


def set_status(name: str, closed: date | None) -> None:
    registry = Registry()
    registry.entries[name.lower()] = closed
    registry.save()


def new_project_warning(name: str | None) -> str | None:
    """A hint to print when `name` isn't an open project, e.g. to catch typos."""
    if not name:
        return None
    name = name.lower()
    history = collect()
    if name in history:
        if history[name].is_open:
            return None
        return f"note: +{name} is closed (reopen with `diary projects reopen {name}`)"
    close = difflib.get_close_matches(name, list(history), n=3, cutoff=0.6)
    hint = f" (did you mean {', '.join('+' + c for c in close)}?)" if close else ""
    return f"note: new project +{name}{hint}"
