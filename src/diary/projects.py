"""Project history assembled from daily logs and the todo list."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import date

from . import logs
from .todos import TodoList


@dataclass
class ProjectHistory:
    name: str
    days: dict[date, str] = field(default_factory=dict)  # day -> that day's section text
    open_todos: int = 0
    done_todos: int = 0

    @property
    def first(self) -> date | None:
        return min(self.days) if self.days else None

    @property
    def last(self) -> date | None:
        return max(self.days) if self.days else None


def collect(since: date | None = None, until: date | None = None,
            todo_list: TodoList | None = None) -> dict[str, ProjectHistory]:
    projects: dict[str, ProjectHistory] = {}

    def get(name: str) -> ProjectHistory:
        return projects.setdefault(name, ProjectHistory(name))

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


def known_names() -> list[str]:
    return sorted(collect())


def new_project_warning(name: str | None) -> str | None:
    """A hint to print when `name` isn't an existing project, e.g. to catch typos."""
    if not name:
        return None
    known = known_names()
    name = name.lower()
    if name in known:
        return None
    close = difflib.get_close_matches(name, known, n=3, cutoff=0.6)
    hint = f" (did you mean {', '.join('+' + c for c in close)}?)" if close else ""
    return f"note: new project +{name}{hint}"
