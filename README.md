# diary

A dev diary CLI. It keeps a running todo list, a daily log split by project, a history of what you worked on and when, and lets you ask Claude questions about all of it. Everything is plain markdown.

## Install

```sh
pipx install -e .        # or: uv tool install -e .
```

Requires Python 3.10+. `diary ask` also needs the [Claude Code](https://claude.com/claude-code) `claude` CLI, logged in.

## Data

Stored in `~/diary` (override with `$DIARY_DIR`). It's safe to hand-edit and works well as its own git repo.

```
~/diary/
  todos.md               # the running todo list
  logs/2026-10-29.md     # one file per day
```

## Todos

```sh
diary todo add Fix token refresh -p api --pri 1 --due tomorrow
diary todo ls                  # global list, grouped by project
diary todo ls -p api           # one project
diary todo ls --done | --all
diary todo done 3 4            # also appends "done #3: ..." to today's log under that project
diary todo edit 3 --pri none -p web --due 2026-11-05 [new text]
diary todo undo 3 | rm 3 | open
```

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

## Projects

```sh
diary projects             # each project: days worked, first/last date, open/done todos
diary projects api         # every day's entries for api, plus its open todos
diary projects --since 3m
```

## Ask

```sh
diary ask "what did I get done on api last week?"
diary ask --since 30d -p api "why did I change the token refresh?"
```

This sends your todos and the selected logs to `claude -p --model claude-opus-5-5` with tools disabled. Set `$DIARY_MODEL` or pass `--model` to use a different model.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```
