# diary

A dev diary CLI. It keeps a running todo list, a daily log split by project, a history of what you worked on and when, and lets you ask Claude questions about all of it. Everything is plain markdown.

## Install

```sh
pipx install -e .        # or: uv tool install -e .
```

Requires Python 3.10+. `diary ask` also needs the [Claude Code](https://claude.com/claude-code) `claude` CLI, logged in.

## Tab completion (zsh)

Add this to `~/.zshrc`, after `compinit` (oh-my-zsh runs compinit for you):

```sh
eval "$(diary completion zsh)"
```

Then tab completes commands, project names after `-p`, and todo ids (with their text) after `todo done`, `edit`, `undo` and `rm`. Using a project name that doesn't exist yet prints a warning such as `note: new project +apo (did you mean +api?)`.

## Data

Stored in `data/` inside this repo, which is gitignored so your logs are never pushed (override with `$DIARY_DIR`; a non-editable install falls back to `~/diary`). It's safe to hand-edit. `diary path` prints the location.

```
data/
  todos.md               # the running todo list
  logs/2026-10-29.md     # one file per day
```

## Todos

```sh
diary todo add                 # asks for text, project, priority, due date; Enter skips one
diary todo ls                  # global list, grouped by project
diary todo ls -p api           # one project
diary todo ls --done | --all
diary todo done 3 4            # also appends "done #3: ..." to today's log under that project
diary todo edit 3 --pri none -p web --due 2026-11-05 [new text]
diary todo deprecate 3         # no longer relevant: hidden from the list, logged as "deprecated #3: ..."
diary todo ls --deprecated     # see them again (--all shows open, done and deprecated)
diary todo undo 3 | rm 3 | open
```

`--due` accepts `YYYY-MM-DD`, `today`, `tomorrow`, a weekday (`fri` or `friday` means the next one, never today), or an offset ahead like `3d`, `2w` or `1m`.

`diary todo add` asks for each field in turn: the text, then project (Tab completes open projects; a new name asks for confirmation, to catch typos), priority (1-3) and due date. Press Enter to skip any but the text; invalid answers are asked again. Typed answers never go through the shell, so `>`, `|`, `&`, `#` and `*` are all fine. Flags (`-p`, `--pri`, `--due`) still work as shortcuts that skip their question. `diary todo edit 3` with no text or flags asks the same questions, showing each current value: Enter keeps it, `-` clears it, and at the text question `e` opens the text in `$EDITOR` to fix it in place. Giving flags or text (`diary todo edit 3 --pri 1`) changes just those, without asking.

In `todos.md`, each todo is one line with inline tokens: `+project`, `!p1`..`!p3`, and `due:YYYY-MM-DD`. Lines you add by hand get an id on the next save.

## Daily log

```sh
diary log -p api "fixed the refresh race"   # timestamped bullet under ## api
diary log "general thought"                 # goes under ## Notes
diary log                                   # open today in $EDITOR
diary log -p api                            # open today, with an ## api section ready
diary log -d yesterday                      # open another day
diary show [date] | diary show --since 7d
```

Each `## <project>` heading in a day's file means you worked on that project that day, so one day can cover several projects. `## Notes` is for general notes. `## Open todos` is regenerated every time you open today's log and is ignored by reports.

## Merged PRs

The first `diary log` of each day pulls in your merged pull requests from `togethercomputer` repos (via the `gh` CLI) and adds each one to the `## PRs` section of the day it merged, catching up any days since the last sync:

```
## PRs

- 16:20 merged tiny-engine#345: k3_common.gemm: parse the knob-fix label tokens ab<N>, ec<N>, entrypftw
  https://github.com/togethercomputer/tiny-engine/pull/345
```

Each PR is logged once (tracked in `data/prs.json`), even if you delete its line. If `gh` fails, `diary log` still works and the sync is retried next time. `diary prs sync` syncs right away; add `--since 2w` to re-check further back. `## PRs` is not a project, so it doesn't count toward `diary projects`.

## Projects

```sh
diary projects             # each project: status, days worked, first/last date, open/done todos
diary projects api         # every day's entries for api, plus its open todos
diary projects --since 3m
diary projects add web     # create a project before using it
diary projects close api   # finished: no more auto headings, hidden from -p completion (needs no open todos)
diary projects reopen api
```

A project also gets created the first time you use it with `-p`. A closed project is reopened automatically when it gets an open todo (added, moved into it, or reopened with `undo`). Every project is open until you close it, and its history stays after closing. Open/closed status is kept in `data/projects.md`, which you can hand-edit; deleting a line there removes a project that has no logs or todos (such as a typo).

When `diary log` opens a day in your editor, it adds an empty `## <project>` heading for every open project, so you can start writing straight away. Headings left empty don't count as working on that project.

## Ask

```sh
diary ask "what did I get done on api last week?"
diary ask --since 30d -p api "why did I change the token refresh?"
```

This sends your todos and the selected logs to `claude -p --model claude-opus-5-5` with tools disabled. Set `$DIARY_MODEL` or pass `--model` to use a different model.

## Colour

Output is coloured when printing to a terminal and plain when piped. Project names are coral; p1 and overdue items are red, p2 and items due today yellow, and closed projects and done todos dimmed. Set `DIARY_COLOR=always` or `never` (or `NO_COLOR`) to override.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```
