"""Natural-language Q&A over the diary, answered by Claude via the `claude` CLI in headless mode."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import date

from . import logs, store

DEFAULT_MODEL = "claude-opus-5-5"

INSTRUCTIONS = """\
You are answering questions about the user's personal developer diary.
Below are their todo list and daily log entries. In each daily log, a `## <name>` heading
is a project worked on that day; `## Notes` is general notes. Todo tokens: +project,
!p1 (high) .. !p3 (low) priority, due:/created:/done: dates.

Answer the question using only this diary. Cite dates (and todo ids like #12) for the
facts you use. If the diary doesn't contain the answer, say so plainly.
"""


def build_prompt(question: str, since: date | None = None, project: str | None = None,
                 today: date | None = None) -> str:
    today = today or date.today()
    parts = [INSTRUCTIONS, f"Today is {today.isoformat()} ({today.strftime('%A')}).\n"]

    todos_file = store.todos_path()
    if todos_file.exists():
        parts.append(f"<todos>\n{todos_file.read_text().strip()}\n</todos>\n")

    for day in logs.all_days(since=since):
        log = logs.DayLog(day)
        if project:
            sections = log.project_sections()
            if project.lower() not in sections:
                continue
            body = f"## {project.lower()}\n{sections[project.lower()]}"
        else:
            body = log.for_context().strip()
        parts.append(f'<log date="{day.isoformat()}">\n{body}\n</log>\n')

    parts.append(f"<question>\n{question}\n</question>\n")
    return "\n".join(parts)


def ask(question: str, since: date | None = None, project: str | None = None,
        model: str | None = None) -> int:
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("`claude` CLI not found on PATH; install Claude Code to use `diary ask`")
    model = model or os.environ.get("DIARY_MODEL", DEFAULT_MODEL)
    prompt = build_prompt(question, since=since, project=project)
    # No tools: the answer should come only from the diary text we pass in.
    return subprocess.run([claude, "-p", "--model", model, "--tools", ""], input=prompt, text=True).returncode
