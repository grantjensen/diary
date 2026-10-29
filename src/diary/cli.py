"""Command-line entry point: `diary <command> ...`."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from datetime import date

from . import ask as ask_mod
from . import completion
from . import logs, projects, store
from .todos import Todo, TodoList


def open_in_editor(path) -> None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        editor = next((e for e in ("nvim", "vim", "vi", "nano") if shutil.which(e)), None)
    if not editor:
        sys.exit("no editor found; set $EDITOR")
    subprocess.call([*shlex.split(editor), str(path)])


def day_arg(text: str) -> date:
    try:
        return store.parse_day(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def priority_arg(text: str) -> int:
    value = text.lower().lstrip("p")
    if value not in {"1", "2", "3"}:
        raise argparse.ArgumentTypeError("priority must be 1, 2 or 3 (or p1..p3)")
    return int(value)


def format_todo(t: Todo, today: date, under: str | None = None) -> str:
    """One display line; `under` is the project heading it's listed beneath, so its tag is omitted."""
    box = "[x]" if t.is_done else "[ ]"
    bits = [f"{box} #{t.id:<3}"]
    bits.append(f"p{t.priority}" if t.priority else "  ")
    bits.append(t.text)
    tags = [p for p in (t.project, *t.extra_projects) if p and p != under]
    if tags:
        bits.append(" ".join(f"+{p}" for p in tags))
    if t.due and not t.is_done:
        flag = " OVERDUE" if t.due < today else " TODAY" if t.due == today else ""
        bits.append(f"(due {t.due.isoformat()}{flag})")
    if t.is_done and t.done != date.min:
        bits.append(f"(done {t.done.isoformat()})")
    return " ".join(bits)


# --- todo ---------------------------------------------------------------

def warn_if_new_project(name: str | None) -> None:
    warning = projects.new_project_warning(name)
    if warning:
        print(warning, file=sys.stderr)


def cmd_todo_add(args) -> None:
    warn_if_new_project(args.project)
    tl = TodoList()
    t = tl.add(" ".join(args.text), project=args.project, priority=args.priority, due=args.due)
    tl.save()
    print(f"added {format_todo(t, date.today())}")


def cmd_todo_ls(args) -> None:
    tl = TodoList()
    items = tl.query(project=args.project, include_open=not args.done, include_done=args.done or args.all)
    today = date.today()
    if not items:
        print("no todos" + (f" for +{args.project}" if args.project else ""))
        return
    if args.project:
        for t in items:
            print(format_todo(t, today, under=args.project.lower()))
        return
    # Global view: grouped by project, untagged last.
    groups: dict[str, list[Todo]] = {}
    for t in items:
        groups.setdefault(t.project or "", []).append(t)
    for name in sorted(groups, key=lambda n: (n == "", n)):
        print(f"{'+' + name if name else '(no project)'}")
        for t in groups[name]:
            print("  " + format_todo(t, today, under=name))


def cmd_todo_done(args) -> None:
    tl = TodoList()
    today = date.today()
    log = logs.DayLog(today)
    for todo_id in args.ids:
        try:
            t = tl.get(todo_id)
        except KeyError as e:
            print(e.args[0], file=sys.stderr)
            continue
        if t.is_done:
            print(f"#{t.id} already done")
            continue
        t.done = today
        log.append(f"done #{t.id}: {t.text}", project=t.project)
        print(f"done {format_todo(t, today)}")
    tl.save()


def cmd_todo_undo(args) -> None:
    tl = TodoList()
    t = tl.get(args.id)
    t.done = None
    tl.save()
    print(f"reopened {format_todo(t, date.today())}")


def cmd_todo_edit(args) -> None:
    tl = TodoList()
    t = tl.get(args.id)
    if args.text:
        t.text = " ".join(args.text)
    if args.project is not None:
        if args.project not in {"", "-", "none"}:
            warn_if_new_project(args.project)
        t.project = None if args.project in {"", "-", "none"} else args.project.lower()
    if args.priority is not None:
        t.priority = None if args.priority == 0 else args.priority
    if args.clear_due:
        t.due = None
    elif args.due:
        t.due = args.due
    tl.save()
    print(f"updated {format_todo(t, date.today())}")


def cmd_todo_rm(args) -> None:
    tl = TodoList()
    t = tl.remove(args.id)
    tl.save()
    print(f"removed #{t.id}: {t.text}")


def cmd_todo_open(args) -> None:
    tl = TodoList()
    tl.save()  # make sure the file exists and ids are assigned
    open_in_editor(tl.path)
    TodoList().save()  # normalise anything added by hand


# --- log ----------------------------------------------------------------

def cmd_log(args) -> None:
    warn_if_new_project(args.project)
    log = logs.DayLog(args.date)
    if args.message:
        log.append(" ".join(args.message), project=args.project)
        print(f"logged to {args.date.isoformat()} under {args.project or logs.NOTES}")
        return
    log.ensure()
    if args.date == date.today():
        log.refresh_open_todos(TodoList().query())
    if args.project:
        _ensure_section(log, args.project)
    open_in_editor(log.path)


def _ensure_section(log: logs.DayLog, project: str) -> None:
    preamble, sections = logs.split_sections(log.read())
    if not any(h.lower() == project.lower() for h, _ in sections):
        sections.append((project.lower(), ["", ""]))
        log.path.write_text(logs.join_sections(preamble, sections) + "\n")


def cmd_show(args) -> None:
    days = logs.all_days(since=args.since) if args.since else [args.date]
    shown = False
    for d in days:
        log = logs.DayLog(d)
        if log.exists:
            if shown:
                print()
            print(log.for_context().rstrip())
            shown = True
    if not shown:
        print("no log entries")


# --- projects -----------------------------------------------------------

def cmd_projects(args) -> None:
    history = projects.collect(since=args.since)
    if args.name:
        p = history.get(args.name.lower())
        if not p:
            sys.exit(f"no project named {args.name!r}")
        _print_project(p)
        return
    if not history:
        print("no projects yet: add `## <project>` sections to a log or `+project` to a todo")
        return
    rows = sorted(history.values(), key=lambda p: (-(p.last or date.min).toordinal(), p.name))
    headers = ("project", "days", "first", "last", "open", "done")
    table = [headers] + [
        (p.name, str(len(p.days)), _d(p.first), _d(p.last), str(p.open_todos), str(p.done_todos))
        for p in rows
    ]
    widths = [max(len(r[i]) for r in table) for i in range(len(headers))]
    for i, r in enumerate(table):
        print("  ".join(c.ljust(w) if j == 0 else c.rjust(w) for j, (c, w) in enumerate(zip(r, widths))))
        if i == 0:
            print("  ".join("-" * w for w in widths))


def _d(d: date | None) -> str:
    return d.isoformat() if d else "-"


def _print_project(p: projects.ProjectHistory) -> None:
    print(f"+{p.name}: {len(p.days)} day(s) logged, {_d(p.first)} .. {_d(p.last)}; "
          f"{p.open_todos} open / {p.done_todos} done todo(s)")
    for d in sorted(p.days):
        print(f"\n{d.isoformat()} ({d.strftime('%a')})")
        for line in p.days[d].splitlines():
            print(f"  {line}")
    open_items = TodoList().query(project=p.name)
    if open_items:
        print("\nopen todos")
        today = date.today()
        for t in open_items:
            print("  " + format_todo(t, today, under=p.name))


# --- ask ----------------------------------------------------------------

def cmd_ask(args) -> None:
    question = " ".join(args.question)
    try:
        code = ask_mod.ask(question, since=args.since, project=args.project, model=args.model)
    except RuntimeError as e:
        sys.exit(str(e))
    sys.exit(code)


# --- parser -------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="diary", description="Dev diary: todos, daily logs, projects, and Q&A.")
    sub = parser.add_subparsers(dest="command", required=True)

    todo = sub.add_parser("todo", aliases=["t"], help="manage the todo list")
    tsub = todo.add_subparsers(dest="todo_command", required=True)

    p = tsub.add_parser("add", aliases=["a"], help="add a todo")
    p.add_argument("text", nargs="+")
    p.add_argument("-p", "--project")
    p.add_argument("--pri", dest="priority", type=priority_arg, help="1 (high) .. 3 (low)")
    p.add_argument("--due", type=day_arg, help="YYYY-MM-DD, today, tomorrow")
    p.set_defaults(func=cmd_todo_add)

    p = tsub.add_parser("ls", aliases=["list"], help="list todos (global by default)")
    p.add_argument("-p", "--project")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--done", action="store_true", help="only completed todos")
    g.add_argument("--all", action="store_true", help="open and completed todos")
    p.set_defaults(func=cmd_todo_ls)

    p = tsub.add_parser("done", aliases=["d"], help="mark todos done (also logs them to today)")
    p.add_argument("ids", type=int, nargs="+")
    p.set_defaults(func=cmd_todo_done)

    p = tsub.add_parser("undo", help="reopen a completed todo")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_todo_undo)

    p = tsub.add_parser("edit", aliases=["e"], help="change a todo's text, project, priority or due date")
    p.add_argument("id", type=int)
    p.add_argument("text", nargs="*", help="new text (optional)")
    p.add_argument("-p", "--project", help="new project ('none' to clear)")
    p.add_argument("--pri", dest="priority", type=lambda s: 0 if s == "none" else priority_arg(s),
                   help="1..3, or 'none' to clear")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--due", type=day_arg)
    g.add_argument("--no-due", dest="clear_due", action="store_true")
    p.set_defaults(func=cmd_todo_edit)

    p = tsub.add_parser("rm", help="delete a todo entirely")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_todo_rm)

    p = tsub.add_parser("open", help="edit todos.md in $EDITOR")
    p.set_defaults(func=cmd_todo_open)

    p = sub.add_parser("log", aliases=["l"], help="append to or open a daily log")
    p.add_argument("message", nargs="*", help="quick entry; omit to open the day in $EDITOR")
    p.add_argument("-p", "--project", help="project section to log under")
    p.add_argument("-d", "--date", type=day_arg, default=date.today(), help="which day (default today)")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("show", help="print a day's log, or a range with --since")
    p.add_argument("date", nargs="?", type=day_arg, default=date.today())
    p.add_argument("--since", type=day_arg, help="show every day from this date (e.g. 7d)")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("projects", aliases=["p"], help="summarise projects and the days you worked on them")
    p.add_argument("name", nargs="?", help="show one project's full history")
    p.add_argument("--since", type=day_arg)
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("ask", help="ask Claude a question about your diary")
    p.add_argument("question", nargs="+")
    p.add_argument("--since", type=day_arg, help="only include logs from this date (e.g. 30d)")
    p.add_argument("-p", "--project", help="only include this project's log sections")
    p.add_argument("--model", help=f"override model (default: $DIARY_MODEL or {ask_mod.DEFAULT_MODEL})")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("completion", help="print a shell completion script (eval it in ~/.zshrc)")
    p.add_argument("shell", choices=["zsh"])
    p.set_defaults(func=lambda args: print(completion.ZSH.strip()))

    p = sub.add_parser("path", help="print the data directory")
    p.set_defaults(func=lambda args: print(store.data_dir()))

    return parser


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_complete"]:  # hidden helper used by the completion script
        print("\n".join(completion.complete(argv[1] if len(argv) > 1 else "")))
        return
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
