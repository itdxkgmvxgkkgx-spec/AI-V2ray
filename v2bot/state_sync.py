"""Persistence across GitHub Actions runs + self-relaunch.

Strategy
--------
* All runtime state lives in `data/` (SQLite db, memories, skills, subs).
* A dedicated orphan branch `state` holds **only** `data/` (so `main` stays clean).
* Every `state_push_interval` seconds we `wal_checkpoint`, copy `data/` into a worktree of `state`, commit & push.
* On boot, `restore()` clones `state` and copies `data/` back before the DB is opened.
* `relaunch()` fires a `workflow_dispatch` with GH_PAT so the next run starts right as this one ends.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

import aiohttp

from .config import DATA_DIR, ENV, ROOT

LOG = logging.getLogger("v2bot.state")
STATE_WT = ROOT.parent / "_state_worktree"


def _run(cmd: list[str], cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True, check=check)


def _remote() -> str:
    if ENV.gh_pat and ENV.gh_repo:
        return f"https://x-access-token:{ENV.gh_pat}@github.com/{ENV.gh_repo}.git"
    r = _run(["git", "remote", "get-url", "origin"])
    return r.stdout.strip()


def _git_identity(cwd: Path):
    _run(["git", "config", "user.name", "v2ray-config-bot"], cwd)
    _run(["git", "config", "user.email", "bot@users.noreply.github.com"], cwd)


def restore() -> bool:
    """Clone the state branch and copy data/ into place. Safe to call when branch does not exist yet."""
    remote = _remote()
    if not remote:
        LOG.warning("no git remote; running without persistence")
        return False
    if STATE_WT.exists():
        shutil.rmtree(STATE_WT, ignore_errors=True)
    r = _run(["git", "clone", "--depth", "1", "--branch", ENV.state_branch, remote, str(STATE_WT)])
    if r.returncode != 0:
        LOG.info("state branch missing -> creating orphan branch")
        STATE_WT.mkdir(parents=True, exist_ok=True)
        _run(["git", "init", "-q"], STATE_WT)
        _run(["git", "checkout", "-q", "--orphan", ENV.state_branch], STATE_WT)
        _run(["git", "remote", "add", "origin", remote], STATE_WT)
        _git_identity(STATE_WT)
        (STATE_WT / "README.md").write_text("# state branch\nAuto-managed runtime state of v2ray_config bot. Do not edit by hand.\n")
        _run(["git", "add", "-A"], STATE_WT)
        _run(["git", "commit", "-q", "-m", "init state"], STATE_WT)
        _run(["git", "push", "-q", "-u", "origin", ENV.state_branch], STATE_WT)
        return False
    _git_identity(STATE_WT)
    src = STATE_WT / "data"
    if src.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            dst = DATA_DIR / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
        LOG.info("state restored from branch %s", ENV.state_branch)
        return True
    return False


_last_push_ok: float | None = None
_push_lock = asyncio.Lock()


def last_push() -> float | None:
    return _last_push_ok


async def push(db, reason: str = "periodic") -> bool:
    """Checkpoint DB, copy data/ into the worktree, commit, push. Never raises."""
    global _last_push_ok
    if not STATE_WT.exists() or not (STATE_WT / ".git").exists():
        return False
    async with _push_lock:
        try:
            await db.checkpoint()
            dst = STATE_WT / "data"
            dst.mkdir(exist_ok=True)
            for item in DATA_DIR.iterdir():
                if item.name in ("tmp", "bot.log") or item.suffix in (".db-wal", ".db-shm"):
                    continue
                target = dst / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
            loop = asyncio.get_running_loop()

            def _commit_push():
                _run(["git", "add", "-A"], STATE_WT)
                if not _run(["git", "diff", "--cached", "--quiet"], STATE_WT).returncode:
                    return True  # nothing changed
                _run(["git", "commit", "-q", "-m", f"state: {reason} {time.strftime('%Y-%m-%d %H:%M:%S')} run={ENV.gh_run_id}"], STATE_WT)
                r = _run(["git", "push", "-q", "origin", ENV.state_branch], STATE_WT)
                if r.returncode != 0:
                    # someone else pushed (overlapping run) -> rebase ours on top and retry
                    _run(["git", "fetch", "-q", "origin", ENV.state_branch], STATE_WT)
                    _run(["git", "rebase", "-X", "theirs", f"origin/{ENV.state_branch}"], STATE_WT)
                    r = _run(["git", "push", "-q", "origin", ENV.state_branch], STATE_WT)
                    if r.returncode != 0:
                        _run(["git", "rebase", "--abort"], STATE_WT)
                        r = _run(["git", "push", "-q", "-f", "origin", ENV.state_branch], STATE_WT)
                return r.returncode == 0

            ok = await loop.run_in_executor(None, _commit_push)
            if ok:
                _last_push_ok = time.time()
            else:
                LOG.warning("state push failed")
            return ok
        except Exception as e:
            LOG.warning("state push error: %s", e)
            return False


async def periodic_pusher(db, interval_getter):
    while True:
        await asyncio.sleep(max(15, int(interval_getter())))
        await push(db, "periodic")


# ---------------------------------------------------------------- relaunch
async def relaunch(workflow_file: str = "bot.yml", chain: int = 0) -> bool:
    """Dispatch the next workflow run via GH_PAT. Returns True if GitHub accepted it."""
    if not (ENV.gh_pat and ENV.gh_repo):
        LOG.warning("GH_PAT / GITHUB_REPOSITORY missing -> cannot relaunch")
        return False
    url = f"https://api.github.com/repos/{ENV.gh_repo}/actions/workflows/{workflow_file}/dispatches"
    body = {"ref": ENV.gh_ref or "main", "inputs": {"chain": str(chain + 1)}}
    hdr = {"Authorization": f"Bearer {ENV.gh_pat}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    for attempt in range(5):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=body, headers=hdr, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status == 204:
                        LOG.info("relaunch dispatched (chain %s)", chain + 1)
                        return True
                    LOG.warning("relaunch attempt %s -> %s %s", attempt, r.status, (await r.text())[:200])
        except Exception as e:
            LOG.warning("relaunch error: %s", e)
        await asyncio.sleep(10 * (attempt + 1))
    return False


async def cancel_other_runs(workflow_file: str = "bot.yml"):
    """Avoid two bots polling the same token: cancel older in-progress runs of this workflow."""
    if not (ENV.gh_pat and ENV.gh_repo):
        return
    hdr = {"Authorization": f"Bearer {ENV.gh_pat}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{ENV.gh_repo}/actions/workflows/{workflow_file}/runs?status=in_progress&per_page=20"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=hdr, timeout=aiohttp.ClientTimeout(total=30)) as r:
                data = await r.json()
            for run in data.get("workflow_runs", []):
                if str(run["id"]) != str(ENV.gh_run_id):
                    await s.post(f"https://api.github.com/repos/{ENV.gh_repo}/actions/runs/{run['id']}/cancel", headers=hdr)
                    LOG.info("cancelled overlapping run %s", run["id"])
    except Exception as e:
        LOG.warning("cancel_other_runs: %s", e)
