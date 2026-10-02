"""Central configuration: env/secrets + paths.

Everything that is a *secret* comes from environment variables (GitHub Actions secrets).
Everything that is a *setting* lives in the SQLite settings table (editable from Telegram).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("V2BOT_DATA_DIR", ROOT / "data"))
BIN_DIR = Path(os.environ.get("V2BOT_BIN_DIR", ROOT / "bin"))
DB_PATH = DATA_DIR / "state.db"
MEM_DIR = DATA_DIR / "memories"
SKILLS_DIR = DATA_DIR / "skills"
SUBS_DIR = DATA_DIR / "subs"
LOG_FILE = DATA_DIR / "bot.log"

for _d in (DATA_DIR, BIN_DIR, MEM_DIR, SKILLS_DIR, SUBS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Env:
    bot_token: str = os.environ.get("BOT_TOKEN", "")
    admin_id: int = _int("ADMIN_ID", 0)
    gh_pat: str = os.environ.get("GH_PAT", "")
    tavily_key: str = os.environ.get("TAVILY_API_KEY", "")
    # GitHub Actions runtime context
    gh_repo: str = os.environ.get("GITHUB_REPOSITORY", "")           # owner/repo
    gh_run_id: str = os.environ.get("GITHUB_RUN_ID", "")
    gh_workflow: str = os.environ.get("GITHUB_WORKFLOW", "")
    gh_ref: str = os.environ.get("GITHUB_REF_NAME", "main")
    gh_event: str = os.environ.get("GITHUB_EVENT_NAME", "")
    in_actions: bool = os.environ.get("GITHUB_ACTIONS", "") == "true"
    state_branch: str = os.environ.get("STATE_BRANCH", "state")
    # a run must end before GitHub's 6h hard limit; we relaunch a bit before that
    max_run_minutes: int = _int("MAX_RUN_MINUTES", 345)
    state_push_interval: int = _int("STATE_PUSH_INTERVAL", 60)      # seconds
    extra: dict = field(default_factory=dict)


ENV = Env()

# ---- default (editable) settings ----------------------------------------------------------
DEFAULT_SETTINGS: dict = {
    "public_mode": False,
    "interval_minutes": 30,              # how often the collector pipeline runs
    "fetch_concurrency": 24,
    "fetch_timeout": 20,
    "tcp_concurrency": 300,
    "tcp_timeout": 4.0,
    "speed_concurrency": 8,              # parallel xray/sing-box instances
    "speed_timeout": 25,
    "speed_download_bytes": 3_000_000,
    "speed_upload_bytes": 1_000_000,
    "max_speedtest": 150,                # best N by tcp ping go to speed test
    "max_tcp_test": 6000,                # cap per run
    "min_score_keep": 0.0,
    "retest_alive_hours": 6,             # re-test known-good configs after N hours
    "iran_filter": True,                 # apply Iran-friendliness heuristics
    "drop_ir_servers": True,             # drop servers located in Iran
    "auto_add_sources": False,           # AI-discovered sources need approval unless True
    "discover_interval_hours": 12,       # Tavily discovery frequency (0 = off)
    "ai_base_url": "",
    "ai_api_key": "",                    # encrypted at rest
    "ai_model": "",
    "ai_temperature": 0.3,
    "ai_max_iterations": 40,
    "ai_memory_notifications": "verbose",   # off | on | verbose
    "ai_approval_required": True,
    "memory_char_limit": 4000,
    "user_char_limit": 2000,
    "state_push_interval": 60,
    "max_run_minutes": 345,
    "default_lang": "en",
    "log_ring_size": 400,
    "top_list_size": 20,
}

PERMISSIONS = ["settings", "pipeline", "ai", "admins", "logs", "subs", "sources", "terminal"]
