"""Shell completion: a zsh script, plus the hidden `diary _complete <kind>` it calls for dynamic values."""

from __future__ import annotations

from . import projects
from .todos import TodoList

ZSH = r"""
# zsh completion for diary. Load with:  eval "$(diary completion zsh)"  (after compinit)

_diary_projects() {
  local -a items  # optional last arg: all | closed (default: open projects)
  local kind=projects
  [[ ${@[-1]} == (all|closed) ]] && kind=projects-${@[-1]}
  items=(${(f)"$(diary _complete $kind 2>/dev/null)"})
  _describe -t projects 'project' items
}

_diary_project_actions() {
  local -a acts=('add:create a project' 'close:mark a project closed' 'reopen:reopen a closed project')
  _describe -t actions 'action' acts
}

_diary_todos() {
  local -a items
  items=(${(f)"$(diary _complete todos-${@[-1]} 2>/dev/null)"})  # zsh prepends -J/-X display args
  _describe -t todos 'todo' items -V todos
}

_diary_todo() {
  local curcontext="$curcontext" state line
  _arguments -C '1:subcommand:->sub' '*::arg:->args'
  case $state in
    sub)
      local -a subs=(
        'add:add a todo' 'ls:list todos' 'done:mark todos done'
        'undo:reopen a completed todo' 'edit:change a todo' 'rm:delete a todo'
        'open:edit todos.md in $EDITOR'
      )
      _describe -t commands 'todo command' subs ;;
    args)
      case $line[1] in
        add|a)
          _arguments \
            '(-p --project)'{-p,--project}'[project]:project:_diary_projects' \
            '--pri[priority]:priority:(1 2 3)' \
            '--due[due date]:date:(today tomorrow)' \
            '*:text: ' ;;
        ls|list)
          _arguments \
            '(-p --project)'{-p,--project}'[project]:project:_diary_projects' \
            '(--all)--done[only completed]' '(--done)--all[open and completed]' ;;
        done|d) _arguments '*:todo:_diary_todos open' ;;
        undo)   _arguments '1:todo:_diary_todos done' ;;
        rm)     _arguments '1:todo:_diary_todos all' ;;
        edit|e)
          _arguments \
            '1:todo:_diary_todos all' \
            '(-p --project)'{-p,--project}'[project]:project:_diary_projects' \
            '--pri[priority]:priority:(1 2 3 none)' \
            '(--no-due)--due[due date]:date:(today tomorrow)' \
            '(--due)--no-due[clear due date]' \
            '*:text: ' ;;
      esac ;;
  esac
}

_diary() {
  local curcontext="$curcontext" state line
  _arguments -C '(-h --help)'{-h,--help}'[show help]' '1:command:->command' '*::arg:->args'
  case $state in
    command)
      local -a cmds=(
        'todo:manage the todo list' 'log:append to or open a daily log'
        'show:print a day'"'"'s log' 'projects:summarise projects'
        'ask:ask Claude about your diary' 'path:print the data directory'
        'completion:print a shell completion script'
      )
      _describe -t commands 'diary command' cmds ;;
    args)
      case $line[1] in
        todo|t) _diary_todo ;;
        log|l)
          _arguments \
            '(-p --project)'{-p,--project}'[project]:project:_diary_projects' \
            '(-d --date)'{-d,--date}'[day]:date:(today yesterday)' \
            '*:message: ' ;;
        show) _arguments '--since[from date]:date: ' '1:date:(today yesterday)' ;;
        projects|p)
          if (( CURRENT == 2 )); then
            _alternative 'actions:action:_diary_project_actions' 'projects:project:_diary_projects all'
          else
            case $words[2] in
              close)  _diary_projects ;;
              reopen) _diary_projects closed ;;
            esac
          fi ;;
        ask)
          _arguments \
            '(-p --project)'{-p,--project}'[project]:project:_diary_projects' \
            '--since[from date]:date: ' '--model[model]:model: ' '*:question: ' ;;
        completion) _arguments '1:shell:(zsh)' ;;
      esac ;;
  esac
}

if (( $+functions[compdef] )); then
  compdef _diary diary
else
  print -u2 "diary: run 'autoload -Uz compinit && compinit' before loading completions"
fi
"""


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:")


def complete(kind: str) -> list[str]:
    """Lines in zsh `_describe` format ("value:description") for the given kind."""
    if kind in {"projects", "projects-all", "projects-closed"}:
        status = {"projects": "open", "projects-all": "all", "projects-closed": "closed"}[kind]
        return [_escape(name) for name in projects.known_names(status)]
    if kind in {"todos-open", "todos-done", "todos-all"}:
        which = kind.removeprefix("todos-")
        items = TodoList().query(include_open=which != "done", include_done=which != "open")
        return [f"{t.id}:{t.text}" + (f" +{t.project}" if t.project else "") for t in items]
    return []
