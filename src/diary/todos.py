"""The running todo list, stored as a markdown checklist in todos.md.

Each todo is one line, todo.txt-style tokens are allowed anywhere in the text:

    - [ ] (#3) Fix token refresh +api !p1 due:2026-11-01 created:2026-10-29
    - [x] (#2) Write README +diary created:2026-10-28 done:2026-10-29
    - [-] (#1) Old approach +api created:2026-10-27 deprecated:2026-10-29

Lines added by hand without an id get one assigned on the next save.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import store

LINE_RE = re.compile(r"^\s*[-*]\s+\[(?P<mark>[ xX-])\]\s+(?:\(#(?P<id>\d+)\)\s*)?(?P<rest>.*)$")
PROJECT_RE = re.compile(r"(?<!\S)\+([\w.-]+)")
PRIORITY_RE = re.compile(r"(?<!\S)!p([1-3])(?!\S)")
KEYDATE_RE = re.compile(r"(?<!\S)(due|created|done|deprecated):(\d{4}-\d{2}-\d{2})(?!\S)")

HEADER = "# Todos\n\n<!-- Managed by `diary todo`, but safe to hand-edit. Tokens: +project !p1..!p3 due:YYYY-MM-DD -->\n\n"


@dataclass
class Todo:
    id: int
    text: str
    project: str | None = None
    priority: int | None = None
    due: date | None = None
    created: date | None = None
    done: date | None = None
    deprecated: date | None = None  # no longer relevant: closed without being done
    extra_projects: list[str] = field(default_factory=list)

    @property
    def is_done(self) -> bool:
        return self.done is not None

    @property
    def is_deprecated(self) -> bool:
        return self.deprecated is not None and not self.is_done

    @property
    def is_open(self) -> bool:
        return not self.is_done and not self.is_deprecated

    @classmethod
    def parse(cls, line: str) -> Todo | None:
        m = LINE_RE.match(line)
        if not m:
            return None
        rest = m.group("rest")
        projects = [p.lower() for p in PROJECT_RE.findall(rest)]
        pri = PRIORITY_RE.search(rest)
        dates = {k: date.fromisoformat(v) for k, v in KEYDATE_RE.findall(rest)}
        text = KEYDATE_RE.sub("", PRIORITY_RE.sub("", PROJECT_RE.sub("", rest)))
        done = dates.get("done")
        deprecated = dates.get("deprecated")
        if m.group("mark").lower() == "x" and done is None:
            done = date.min  # checked off by hand; date unknown
        if m.group("mark") == "-" and deprecated is None:
            deprecated = date.min
        return cls(
            id=int(m.group("id")) if m.group("id") else 0,
            text=" ".join(text.split()),
            project=projects[0] if projects else None,
            extra_projects=projects[1:],
            priority=int(pri.group(1)) if pri else None,
            due=dates.get("due"),
            created=dates.get("created"),
            done=done,
            deprecated=deprecated,
        )

    def render(self) -> str:
        mark = "x" if self.is_done else "-" if self.is_deprecated else " "
        parts = [f"- [{mark}] (#{self.id}) {self.text}"]
        parts += [f"+{p}" for p in ([self.project] if self.project else []) + self.extra_projects]
        if self.priority:
            parts.append(f"!p{self.priority}")
        if self.due:
            parts.append(f"due:{self.due.isoformat()}")
        if self.created:
            parts.append(f"created:{self.created.isoformat()}")
        if self.done and self.done != date.min:
            parts.append(f"done:{self.done.isoformat()}")
        if self.is_deprecated and self.deprecated != date.min:
            parts.append(f"deprecated:{self.deprecated.isoformat()}")
        return " ".join(parts)

    def sort_key(self):
        return (self.priority or 4, self.due or date.max, self.id)


class TodoList:
    def __init__(self, path: Path | None = None):
        self.path = path or store.todos_path()
        self.items: list[Todo] = []
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                todo = Todo.parse(line)
                if todo:
                    self.items.append(todo)
        next_id = max((t.id for t in self.items), default=0) + 1
        seen: set[int] = set()
        for t in self.items:
            if t.id == 0 or t.id in seen:
                t.id, next_id = next_id, next_id + 1
                t.created = t.created or date.today()  # added by hand
            seen.add(t.id)

    def save(self) -> None:
        open_items = sorted((t for t in self.items if t.is_open), key=Todo.sort_key)
        done_items = sorted((t for t in self.items if t.is_done), key=lambda t: (t.done, t.id), reverse=True)
        dep_items = sorted((t for t in self.items if t.is_deprecated), key=lambda t: (t.deprecated, t.id), reverse=True)
        body = HEADER + "## Open\n\n" + "".join(t.render() + "\n" for t in open_items)
        body += "\n## Done\n\n" + "".join(t.render() + "\n" for t in done_items)
        if dep_items:
            body += "\n## Deprecated\n\n" + "".join(t.render() + "\n" for t in dep_items)
        store.write_atomic(self.path, body)

    def get(self, todo_id: int) -> Todo:
        for t in self.items:
            if t.id == todo_id:
                return t
        raise KeyError(f"no todo #{todo_id}")

    def add(self, text: str, project: str | None = None, priority: int | None = None,
            due: date | None = None, today: date | None = None) -> Todo:
        parsed = Todo.parse(f"- [ ] {text}")
        assert parsed is not None
        parsed.id = max((t.id for t in self.items), default=0) + 1
        parsed.project = (project.lower() if project else None) or parsed.project
        parsed.priority = priority or parsed.priority
        parsed.due = due or parsed.due
        parsed.created = today or date.today()
        self.items.append(parsed)
        return parsed

    def remove(self, todo_id: int) -> Todo:
        todo = self.get(todo_id)
        self.items.remove(todo)
        return todo

    def query(self, project: str | None = None, include_open: bool = True,
              include_done: bool = False, include_deprecated: bool = False) -> list[Todo]:
        out = []
        for t in self.items:
            wanted = include_done if t.is_done else include_deprecated if t.is_deprecated else include_open
            if not wanted:
                continue
            if project and project.lower() not in [t.project, *t.extra_projects]:
                continue
            out.append(t)
        return sorted(out, key=Todo.sort_key)
