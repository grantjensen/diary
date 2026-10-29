"""Daily log files: one markdown file per day, with a `## <project>` section per project.

    # 2026-10-29 (Thursday)

    ## Open todos
    <!-- auto-generated ... -->
    - (#3) Fix token refresh +api !p1

    ## Notes
    general thoughts, not tied to a project

    ## api
    - 10:14 fixed token refresh bug

Every `## heading` other than the reserved ones counts as "worked on that project that day".
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from . import store
from .todos import Todo

OPEN_TODOS = "Open todos"
NOTES = "Notes"
RESERVED = {OPEN_TODOS.lower(), NOTES.lower()}
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
OPEN_TODOS_NOTE = "<!-- auto-generated: refreshed each time you open today's log, ignored by reports -->"


def template(day: date) -> str:
    return f"# {day.isoformat()} ({day.strftime('%A')})\n\n## {NOTES}\n\n"


def split_sections(text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Return (preamble lines, [(heading, body lines), ...])."""
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            sections.append((m.group(1), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)
    return preamble, sections


def join_sections(preamble: list[str], sections: list[tuple[str, list[str]]]) -> str:
    out = list(preamble)
    for heading, body in sections:
        while out and out[-1].strip() == "":
            out.pop()
        if out:
            out.append("")
        out.append(f"## {heading}")
        out.extend(body)
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out) + "\n"


def _has_content(body: list[str]) -> bool:
    return COMMENT_RE.sub("", "\n".join(body)).strip() != ""


class DayLog:
    def __init__(self, day: date, path: Path | None = None):
        self.day = day
        self.path = path or store.log_path(day)

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> str:
        return self.path.read_text() if self.exists else ""

    def ensure(self) -> None:
        if not self.exists:
            self.path.write_text(template(self.day))

    def append(self, text: str, project: str | None = None, when: datetime | None = None) -> None:
        """Append a timestamped bullet under the project's section (or Notes)."""
        self.ensure()
        heading = project.lower() if project else NOTES
        stamp = (when or datetime.now()).strftime("%H:%M")
        preamble, sections = split_sections(self.read())
        for name, body in sections:
            if name.lower() == heading.lower():
                while body and body[-1].strip() == "":
                    body.pop()
                if not body or body[0].strip() != "":
                    body.insert(0, "")
                body.append(f"- {stamp} {text}")
                break
        else:
            sections.append((heading, ["", f"- {stamp} {text}"]))
        self.path.write_text(join_sections(preamble, sections))

    def refresh_open_todos(self, todos: list[Todo]) -> None:
        """Rewrite the 'Open todos' reference section (kept at the top)."""
        self.ensure()
        preamble, sections = split_sections(self.read())
        sections = [(h, b) for h, b in sections if h.lower() != OPEN_TODOS.lower()]
        body = ["", OPEN_TODOS_NOTE]
        body += [f"- {_todo_summary(t)}" for t in todos] or ["- (none)"]
        body.append("")
        sections.insert(0, (OPEN_TODOS, body))
        self.path.write_text(join_sections(preamble, sections))

    def project_sections(self) -> dict[str, str]:
        """Project name -> section text, for sections that have real content."""
        _, sections = split_sections(self.read())
        out: dict[str, str] = {}
        for heading, body in sections:
            key = heading.lower()
            if key in RESERVED or not _has_content(body):
                continue
            text = COMMENT_RE.sub("", "\n".join(body)).strip()
            out[key] = f"{out[key]}\n{text}" if key in out else text
        return out

    def for_context(self) -> str:
        """Log text with the auto-generated todo section stripped out."""
        preamble, sections = split_sections(self.read())
        sections = [(h, b) for h, b in sections if h.lower() != OPEN_TODOS.lower()]
        return join_sections(preamble, sections)


def _todo_summary(t: Todo) -> str:
    bits = [f"(#{t.id})", t.text]
    if t.project:
        bits.append(f"+{t.project}")
    if t.priority:
        bits.append(f"!p{t.priority}")
    if t.due:
        bits.append(f"due:{t.due.isoformat()}")
    return " ".join(bits)


def all_days(since: date | None = None, until: date | None = None) -> list[date]:
    days = []
    for p in (store.data_dir() / "logs").glob("*.md"):
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if (since is None or d >= since) and (until is None or d <= until):
            days.append(d)
    return sorted(days)
