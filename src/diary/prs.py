"""Merged GitHub pull requests, logged under `## PRs` on the day each one merged.

Synced on the first `diary log` of each day (and by `diary prs sync`). State lives in prs.json:
the last day a sync succeeded, and every PR already logged, so catch-up windows can overlap
and a PR is never logged twice.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from . import logs, store

OWNER = "togethercomputer"


@dataclass
class MergedPR:
    repo: str  # owner/name
    number: int
    title: str
    url: str
    merged: datetime  # local time

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}"

    def log_text(self) -> str:
        short = self.repo.split("/", 1)[-1]
        return f"merged {short}#{self.number}: {self.title}\n  {self.url}"


def fetch_merged(since: date) -> list[MergedPR]:
    """Your PRs in OWNER's repos merged on or after `since` (via the gh CLI)."""
    if not shutil.which("gh"):
        raise RuntimeError("`gh` CLI not found; install it and run `gh auth login`")
    # GitHub filters on UTC dates; start a day early so evening merges (local time) aren't missed.
    cmd = ["gh", "search", "prs", "--author=@me", f"--owner={OWNER}", "--merged",
           f"--merged-at=>={(since - timedelta(days=1)).isoformat()}", "--limit", "500",
           "--json", "repository,number,title,url,closedAt"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh timed out")
    if out.returncode != 0:
        message = (out.stderr or out.stdout).strip()
        raise RuntimeError(message.splitlines()[-1] if message else "gh failed")
    prs = []
    for item in json.loads(out.stdout or "[]"):
        merged = datetime.fromisoformat(item["closedAt"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        if merged.date() >= since:
            prs.append(MergedPR(item["repository"]["nameWithOwner"], item["number"], item["title"],
                                item["url"], merged))
    return sorted(prs, key=lambda p: p.merged)


def _load_state() -> dict:
    path = store.data_dir() / "prs.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"last_sync": None, "logged": []}


def _save_state(state: dict) -> None:
    store.write_atomic(store.data_dir() / "prs.json", json.dumps(state, indent=2) + "\n")


def sync(today: date | None = None, since: date | None = None, force: bool = False,
         fetch: Callable[[date], list[MergedPR]] = fetch_merged) -> list[MergedPR] | None:
    """Log merged PRs not logged yet. Returns the newly logged PRs, or None if already synced today.

    Without `since`, catches up from the last successful sync (or the first diary day).
    Raises RuntimeError if gh fails; the day is then not marked synced, so the next run retries.
    """
    today = today or date.today()
    state = _load_state()
    last = date.fromisoformat(state["last_sync"]) if state["last_sync"] else None
    if not force and last == today:
        return None
    if since is None:
        days = logs.all_days()
        since = last or (days[0] if days else today)
    logged = set(state["logged"])
    new = [pr for pr in fetch(since) if pr.key not in logged]
    for pr in new:
        logs.DayLog(pr.merged.date()).append(pr.log_text(), when=pr.merged, section=logs.PRS)
        logged.add(pr.key)
        state["logged"] = sorted(logged)
        _save_state(state)  # after each PR, so a crash midway never double-logs
    state["last_sync"] = today.isoformat()
    _save_state(state)
    return new
