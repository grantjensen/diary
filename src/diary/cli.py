"""Command-line entry point: `diary <command> ...`."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from . import ask as ask_mod
from . import color, completion
from . import logs, projects, prs, store
from .todos import Todo, TodoList


def open_in_editor(path, insert_at_line: int | None = None) -> None:
    """Open `path` in $VISUAL/$EDITOR. With `insert_at_line`, vim/nvim start in insert mode at the end of that line."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        editor = next((e for e in ("nvim", "vim", "vi", "nano") if shutil.which(e)), None)
    if not editor:
        sys.exit("no editor found; set $EDITOR")
    cmd = shlex.split(editor)
    if insert_at_line and Path(cmd[0]).name in {"vim", "nvim", "vi", "mvim", "gvim"}:
        cmd += [f"+{insert_at_line}", "+startinsert!"]
    subprocess.call([*cmd, str(path)])


def day_arg(text: str, future: bool = False) -> date:
    try:
        return store.parse_day(text, future=future)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def due_arg(text: str) -> date:
    return day_arg(text, future=True)


def priority_arg(text: str) -> int:
    value = text.lower().lstrip("p")
    if value not in {"1", "2", "3"}:
        raise argparse.ArgumentTypeError("priority must be 1, 2 or 3 (or p1..p3)")
    return int(value)


def format_todo(t: Todo, today: date, under: str | None = None) -> str:
    """One display line; `under` is the project heading it's listed beneath, so its tag is omitted."""
    box = (color.paint("[x]", "green") if t.is_done
           else color.paint("[-]", "dim") if t.is_deprecated else "[ ]")
    bits = [f"{box} {color.paint(f'#{t.id:<3}', 'dim')}"]
    bits.append(color.priority(t.priority))
    bits.append(color.paint(t.text, "dim") if t.is_done
                else color.paint(t.text, "dim", "9") if t.is_deprecated else t.text)  # 9 = strikethrough
    tags = [p for p in (t.project, *t.extra_projects) if p and p != under]
    if tags:
        bits.append(" ".join("+" + color.project(p) for p in tags))
    if t.due and t.is_open:
        if t.due < today:
            bits.append(color.paint(f"(due {t.due.isoformat()} OVERDUE)", "red", "bold"))
        elif t.due == today:
            bits.append(color.paint(f"(due {t.due.isoformat()} TODAY)", "yellow", "bold"))
        else:
            bits.append(color.paint(f"(due {t.due.isoformat()})", "dim"))
    if t.is_done and t.done != date.min:
        bits.append(color.paint(f"(done {t.done.isoformat()})", "dim"))
    if t.is_deprecated:
        when = f" {t.deprecated.isoformat()}" if t.deprecated != date.min else ""
        bits.append(color.paint(f"(deprecated{when})", "dim"))
    return " ".join(bits)


# --- todo ---------------------------------------------------------------

def warn_if_new_project(name: str | None, for_todo: bool = False) -> None:
    warning = projects.new_project_warning(name)
    if warning and not (for_todo and "is closed" in warning):  # an open todo reopens it anyway
        print(warning, file=sys.stderr)


def _readline(completions: list[str] | None = None):
    """Set up line editing for input(), with Tab completing from `completions` (if given)."""
    try:
        import readline
    except ImportError:
        return None
    if getattr(readline, "backend", "") == "editline" or "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(" ")
    options = completions or []
    readline.set_completer(lambda text, i: ([o for o in options if o.startswith(text)] + [None])[i])
    return readline


def ask(label: str, completions: list[str] | None = None) -> str | None:
    """One line of input; returns None on Enter (or end of piped input). Ctrl-C cancels."""
    _readline(completions)
    try:
        return input(f"{label}: ").strip() or None
    except EOFError:
        print()
        return None
    except KeyboardInterrupt:
        print()
        sys.exit("cancelled")


def prompt_text(label: str) -> str:
    """Read free text interactively, so shell characters like > | & # need no quoting."""
    text = ask(label)
    if not text:
        sys.exit("nothing entered")
    return text


def edit_text_in_editor(text: str) -> str:
    """Open `text` in $EDITOR and return the edited version (lines joined into one)."""
    with tempfile.NamedTemporaryFile("w+", suffix=".txt", prefix="diary-todo-", delete=False) as f:
        f.write(text + "\n")
    try:
        open_in_editor(f.name, insert_at_line=1)
        edited = " ".join(Path(f.name).read_text().split())
    finally:
        os.unlink(f.name)
    if not edited:
        sys.exit("empty text; todo left unchanged")
    return edited


_UNSET = object()  # "no current value": the field is being asked for a new todo
CLEAR = {"-", "none"}


def _label(name: str, hint: str, current) -> str:
    """'name (hint)' when adding; 'name [current] (hint)' when editing."""
    if current is _UNSET:
        return f"{name}{f' ({hint})' if hint else ''}"
    shown = current.isoformat() if isinstance(current, date) else current
    return f"{name} [{shown if shown not in (None, '') else 'none'}] ({hint + '; ' if hint else ''}Enter keeps, - clears)"


def ask_text(current: str) -> str:
    """Edit a todo's text: Enter keeps it, `e` opens it in $EDITOR, anything else replaces it."""
    value = ask(f"text [{current}] (Enter keeps, e edits in $EDITOR)")
    if not value:
        return current
    return edit_text_in_editor(current) if value == "e" else value


def ask_project(current=_UNSET) -> str | None:
    open_names = projects.known_names("open")
    label = _label("project", f"{', '.join(open_names)}; Tab completes" if open_names else "", current)
    while True:
        name = ask(label, completions=open_names)
        if not name:
            return None if current is _UNSET else current
        if name in CLEAR:
            return None
        name = name.lstrip("+").lower()
        if name == current:
            return name
        warning = projects.new_project_warning(name)
        if not warning:
            return name
        if "is closed" in warning:
            return name  # adding/moving an open todo here reopens it
        what = warning.removeprefix("note: ")  # "new project +x (did you mean +y?)"
        if (ask(f"create {what} [y/N]") or "").lower() in {"y", "yes"}:
            return name


def ask_priority(current=_UNSET) -> int | None:
    label = _label("priority", "1-3", f"p{current}" if current not in (_UNSET, None) else current)
    while True:
        value = ask(label)
        if not value:
            return None if current is _UNSET else current
        if value in CLEAR:
            return None
        try:
            return priority_arg(value)
        except argparse.ArgumentTypeError as e:
            print(f"  {e}", file=sys.stderr)


def ask_due(current=_UNSET) -> date | None:
    label = _label("due", "fri, 3d, YYYY-MM-DD", current)
    while True:
        value = ask(label)
        if not value:
            return None if current is _UNSET else current
        if value in CLEAR:
            return None
        try:
            return store.parse_day(value, future=True)
        except ValueError as e:
            print(f"  {e}", file=sys.stderr)


def save_todos(tl: TodoList) -> None:
    """Save the todo list; a closed project that now has an open todo is reopened."""
    tl.save()
    for name in projects.reopen_with_open_todos(tl):
        print(f"reopened +{color.project(name)} (it has open todos)", file=sys.stderr)


def cmd_todo_add(args) -> None:
    if args.text:
        cmd = "diary todo add"
        cmd += f" -p {args.project}" if args.project else ""
        cmd += f" --pri {args.priority}" if args.priority else ""
        cmd += f" --due {args.due.isoformat()}" if args.due else ""
        sys.exit(f"todo text goes at the prompt, not the command line: run `{cmd}` and type it there")
    warn_if_new_project(args.project, for_todo=True)
    # Ask for each field not already given as a flag; Enter skips it.
    text = prompt_text("todo")
    project = args.project or ask_project()
    priority = args.priority or ask_priority()
    due = args.due or ask_due()
    tl = TodoList()
    t = tl.add(text, project=project, priority=priority, due=due)
    save_todos(tl)
    print(f"added {format_todo(t, date.today())}")


def cmd_todo_ls(args) -> None:
    tl = TodoList()
    items = tl.query(project=args.project, include_open=not (args.done or args.deprecated),
                     include_done=args.done or args.all, include_deprecated=args.deprecated or args.all)
    today = date.today()
    if not items:
        print("no todos" + (f" for +{args.project}" if args.project else ""))
        return
    if args.project:
        for t in items:
            print(format_todo(t, today, under=args.project.lower()))
        return
    # Global view: grouped by project, most urgent (lowest median priority; none = 4) first, untagged last.
    groups: dict[str, list[Todo]] = {}
    for t in items:
        groups.setdefault(t.project or "", []).append(t)
    def median_priority(name: str) -> float:
        return statistics.median(t.priority or 4 for t in groups[name])

    for name in sorted(groups, key=lambda n: (n == "", median_priority(n), n)):
        print("+" + color.project(name, bold=True) if name else color.paint("(no project)", "bold"))
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
        t.done, t.deprecated = today, None
        log.append(f"done #{t.id}: {t.text}", project=t.project)
        print(f"done {format_todo(t, today)}")
    save_todos(tl)


def cmd_todo_deprecate(args) -> None:
    tl = TodoList()
    today = date.today()
    log = logs.DayLog(today)
    for todo_id in args.ids:
        try:
            t = tl.get(todo_id)
        except KeyError as e:
            print(e.args[0], file=sys.stderr)
            continue
        if not t.is_open:
            print(f"#{t.id} is already {'done' if t.is_done else 'deprecated'}")
            continue
        t.deprecated = today
        log.append(f"deprecated #{t.id}: {t.text}", project=t.project)
        print(f"deprecated {format_todo(t, today)}")
    save_todos(tl)


def cmd_todo_undo(args) -> None:
    tl = TodoList()
    t = tl.get(args.id)
    t.done = t.deprecated = None
    save_todos(tl)
    print(f"reopened {format_todo(t, date.today())}")


def cmd_todo_edit(args) -> None:
    no_flags = args.project is None and args.priority is None and not args.due and not args.clear_due
    if no_flags and not args.text:
        # Interactive: ask for each field, showing the current value (Enter keeps it).
        try:
            current = TodoList().get(args.id)
        except KeyError as e:
            sys.exit(e.args[0])
        print(f"editing {format_todo(current, date.today())}")
        changes = {"text": ask_text(current.text), "project": ask_project(current.project),
                   "priority": ask_priority(current.priority), "due": ask_due(current.due)}
        tl = TodoList()  # reload after prompting/editing, so changes made meanwhile aren't lost
        t = tl.get(args.id)
        for field, value in changes.items():
            setattr(t, field, value)
        save_todos(tl)
        print(f"updated {format_todo(t, date.today())}")
        return
    tl = TodoList()
    t = tl.get(args.id)
    if args.text:
        t.text = " ".join(args.text)
    if args.project is not None:
        if args.project not in {"", "-", "none"}:
            warn_if_new_project(args.project, for_todo=True)
        t.project = None if args.project in {"", "-", "none"} else args.project.lower()
    if args.priority is not None:
        t.priority = None if args.priority == 0 else args.priority
    if args.clear_due:
        t.due = None
    elif args.due:
        t.due = args.due
    save_todos(tl)
    print(f"updated {format_todo(t, date.today())}")


def cmd_todo_rm(args) -> None:
    tl = TodoList()
    t = tl.remove(args.id)
    save_todos(tl)
    print(f"removed #{t.id}: {t.text}")


def cmd_todo_open(args) -> None:
    tl = TodoList()
    save_todos(tl)  # make sure the file exists and ids are assigned
    lines = tl.path.read_text().splitlines()
    last_open = max((i for i, line in enumerate(lines, 1) if line.startswith("- [ ]")), default=None)
    open_in_editor(tl.path, insert_at_line=last_open or len(lines))
    save_todos(TodoList())  # normalise anything added by hand


# --- log ----------------------------------------------------------------

def sync_prs(since: date | None = None, force: bool = False) -> None:
    """Log merged PRs (once a day unless forced); a gh failure only warns, and is retried next time."""
    try:
        new = prs.sync(since=since, force=force)
    except (RuntimeError, OSError, ValueError) as e:
        print(f"note: couldn't sync merged PRs ({e}); will retry on the next `diary log`", file=sys.stderr)
        return
    if new is None:
        return
    for pr in new:
        print(f"logged merged PR {color.paint(pr.key.split('/', 1)[-1], 'green')} "
              f"to {pr.merged.date().isoformat()}: {pr.title}")
    if force and not new:
        print("no new merged PRs")


def cmd_prs_sync(args) -> None:
    sync_prs(since=args.since, force=True)


def cmd_log(args) -> None:
    sync_prs()  # first `diary log` of the day pulls in merged PRs, catching up missed days
    warn_if_new_project(args.project)
    log = logs.DayLog(args.date)
    if args.message:
        log.append(" ".join(args.message), project=args.project)
        where = color.project(args.project.lower(), bold=True) if args.project else color.paint(logs.NOTES, "bold")
        print(f"logged to {color.paint(args.date.isoformat(), 'bold')} under {where}")
        return
    log.ensure()
    if args.date == date.today():
        log.refresh_open_todos(TodoList().query())
    log.ensure_sections(projects.known_names("open") + ([args.project] if args.project else []))
    open_in_editor(log.path)


def cmd_show(args) -> None:
    days = logs.all_days(since=args.since) if args.since else [args.date]
    shown = False
    for d in days:
        log = logs.DayLog(d)
        if log.exists:
            if shown:
                print()
            print(color.log_text(log.for_context().rstrip(), logs.RESERVED))
            shown = True
    if not shown:
        print("no log entries")


# --- projects -----------------------------------------------------------

PROJECT_ACTIONS = ("add", "close", "reopen")


def cmd_projects(args) -> None:
    if args.args and args.args[0] in PROJECT_ACTIONS:
        if len(args.args) != 2:
            sys.exit(f"usage: diary projects {args.args[0]} <name>")
        _project_action(args.args[0], args.args[1].lower())
        return
    if len(args.args) > 1:
        sys.exit("usage: diary projects [name | add|close|reopen <name>]")
    history = projects.collect(since=args.since)
    if args.args:
        p = history.get(args.args[0].lower())
        if not p:
            sys.exit(f"no project named {args.args[0]!r}")
        _print_project(p)
        return
    if not history:
        print("no projects yet: `diary projects add <name>`, or use -p <name> on a todo or log")
        return
    rows = sorted(history.values(), key=lambda p: (not p.is_open, -(p.last or date.min).toordinal(), p.name))
    headers = ("project", "status", "days", "first", "last", "open", "done")
    table = [headers] + [
        (p.name, "open" if p.is_open else "closed", str(len(p.days)), _d(p.first), _d(p.last),
         str(p.open_todos), str(p.done_todos))
        for p in rows
    ]
    widths = [max(len(r[i]) for r in table) for i in range(len(headers))]
    for i, r in enumerate(table):
        cells = [c.ljust(w) if j < 2 else c.rjust(w) for j, (c, w) in enumerate(zip(r, widths))]
        if i == 0:
            print(color.paint("  ".join(cells), "bold"))
            print(color.paint("  ".join("-" * w for w in widths), "dim"))
            continue
        p = rows[i - 1]
        if p.is_open:
            cells[0] = color.project(p.name, bold=True) + cells[0][len(p.name):]
            cells[1] = color.paint(cells[1], "green")
            if p.open_todos:
                cells[5] = color.paint(cells[5], "yellow")
            print("  ".join(cells))
        else:
            print(color.paint("  ".join(cells), "dim"))


def _project_action(action: str, name: str) -> None:
    history = projects.collect()
    p = history.get(name)
    if action == "add":
        if p:
            sys.exit(f"+{name} already exists ({'open' if p.is_open else 'closed'})")
        warning = projects.new_project_warning(name)
        if warning and "did you mean" in warning:
            print(warning, file=sys.stderr)
        projects.set_status(name, None)
        print(f"added +{name}")
        return
    if not p:
        sys.exit(f"no project named {name!r}")
    if action == "close":
        if not p.is_open:
            sys.exit(f"+{name} is already closed")
        if p.open_todos:
            sys.exit(f"+{name} still has {p.open_todos} open todo(s); finish or deprecate them first "
                     f"(see `diary todo ls -p {name}`)")
        projects.set_status(name, date.today())
        print(f"closed +{name}")
    else:
        if p.is_open:
            sys.exit(f"+{name} is already open")
        projects.set_status(name, None)
        print(f"reopened +{name}")


def _d(d: date | None) -> str:
    return d.isoformat() if d else "-"


def _print_project(p: projects.ProjectHistory) -> None:
    status = "" if p.is_open else color.paint(
        f" [closed{' ' + _d(p.closed) if p.closed != date.min else ''}]", "dim")
    print(f"+{color.project(p.name, bold=True)}{status}: {len(p.days)} day(s) logged, "
          f"{_d(p.first)} .. {_d(p.last)}; {p.open_todos} open / {p.done_todos} done todo(s)")
    for d in sorted(p.days):
        print("\n" + color.paint(f"{d.isoformat()} ({d.strftime('%a')})", "bold"))
        print(color.log_text("\n".join(f"  {line}" for line in p.days[d].splitlines()), logs.RESERVED))
    open_items = TodoList().query(project=p.name)
    if open_items:
        print("\n" + color.paint("open todos", "bold"))
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

    p = tsub.add_parser("add", aliases=["a"], help="add a todo: prompts for text, project, priority and due date (Enter skips)")
    p.add_argument("text", nargs="*", help=argparse.SUPPRESS)  # rejected: text is always typed at the prompt
    p.add_argument("-p", "--project")
    p.add_argument("--pri", dest="priority", type=priority_arg, help="1 (high) .. 3 (low)")
    p.add_argument("--due", type=due_arg, help="YYYY-MM-DD, today, tomorrow, fri, 3d, 2w")
    p.set_defaults(func=cmd_todo_add)

    p = tsub.add_parser("ls", aliases=["list"], help="list todos (global by default)")
    p.add_argument("-p", "--project")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--done", action="store_true", help="only completed todos")
    g.add_argument("--deprecated", action="store_true", help="only deprecated todos")
    g.add_argument("--all", action="store_true", help="open, completed and deprecated todos")
    p.set_defaults(func=cmd_todo_ls)

    p = tsub.add_parser("done", aliases=["d"], help="mark todos done (also logs them to today)")
    p.add_argument("ids", type=int, nargs="+")
    p.set_defaults(func=cmd_todo_done)

    p = tsub.add_parser("deprecate", aliases=["dep"],
                        help="mark todos no longer relevant (hidden from the list, logged to today)")
    p.add_argument("ids", type=int, nargs="+")
    p.set_defaults(func=cmd_todo_deprecate)

    p = tsub.add_parser("undo", help="reopen a completed or deprecated todo")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_todo_undo)

    p = tsub.add_parser("edit", aliases=["e"], help="change a todo's text, project, priority or due date")
    p.add_argument("id", type=int)
    p.add_argument("text", nargs="*", help="new text; with no text or flags, asks for each field (Enter keeps the current value)")
    p.add_argument("-p", "--project", help="new project ('none' to clear)")
    p.add_argument("--pri", dest="priority", type=lambda s: 0 if s == "none" else priority_arg(s),
                   help="1..3, or 'none' to clear")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--due", type=due_arg, help="YYYY-MM-DD, today, tomorrow, fri, 3d, 2w")
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

    p = sub.add_parser("prs", help="merged GitHub PRs in the log (synced on the first `diary log` of a day)")
    psub = p.add_subparsers(dest="prs_command", required=True)
    p = psub.add_parser("sync", help="log merged PRs now, catching up any days not yet synced")
    p.add_argument("--since", type=day_arg, help="also re-check PRs merged since this date (e.g. 2w)")
    p.set_defaults(func=cmd_prs_sync)

    p = sub.add_parser("show", help="print a day's log, or a range with --since")
    p.add_argument("date", nargs="?", type=day_arg, default=date.today())
    p.add_argument("--since", type=day_arg, help="show every day from this date (e.g. 7d)")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("projects", aliases=["p"], help="summarise projects, show one, or add/close/reopen one",
                       usage="diary projects [--since DATE] [name | add|close|reopen <name>]")
    p.add_argument("args", nargs="*", metavar="name",
                   help="a project to show its full history, or add|close|reopen <name>")
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
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if extra:
        if args.func is not cmd_todo_add:
            parser.error(f"unrecognized arguments: {' '.join(extra)}")
        args.text += extra  # rejected by cmd_todo_add with a pointer to the prompt
    args.func(args)


if __name__ == "__main__":
    main()
