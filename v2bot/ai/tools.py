"""All kill_pv2 tools. Each registers itself; the agent only ever sees the registry."""
from __future__ import annotations

import asyncio
import base64
import difflib
import json
import os
import re
import subprocess
import time
from pathlib import Path

import aiohttp

from ..config import DATA_DIR, ENV, PERMISSIONS, ROOT, SUBS_DIR, DEFAULT_SETTINGS
from ..parser import extract_links
from ..sources import DISCOVERY_QUERIES
from .registry import DANGEROUS, SAFE, SENSITIVE, registry

OBJ = lambda props, req=None: {"type": "object", "properties": props, "required": req or []}  # noqa: E731
S = lambda d: {"type": "string", "description": d}  # noqa: E731
I = lambda d: {"type": "integer", "description": d}  # noqa: E731
B = lambda d: {"type": "boolean", "description": d}  # noqa: E731

CODE_DIRS = ("v2bot", ".github", "main.py", "requirements.txt", "README.md")


def _safe_path(p: str) -> Path:
    path = (ROOT / p).resolve() if not os.path.isabs(p) else Path(p).resolve()
    if ROOT not in path.parents and path != ROOT and DATA_DIR not in path.parents:
        raise ValueError(f"path outside project: {p}")
    return path


# ===================================================================== project knowledge
PROJECT_MAP = """
PROJECT MAP — v2ray_config bot  (root = repository root)
main.py                      entrypoint: restore state -> open DB -> start pipeline + bot + pusher + relaunch timer
.github/workflows/bot.yml    the GitHub Actions workflow; relaunch targets this file (workflow_dispatch input `chain`)
requirements.txt             python deps (aiogram, aiohttp, aiosqlite, cryptography, pyyaml)
v2bot/config.py              ENV (secrets from env) + DEFAULT_SETTINGS (editable settings, stored in DB) + paths
v2bot/db.py                  SQLite schema + all queries (settings/users/admins/sources/configs/tests/runs/logs/subs/ai_*)
v2bot/i18n.py                10-language UI strings; t(lang,key,**kw)
v2bot/sources.py             BUILTIN_SOURCES list + DISCOVERY_QUERIES for Tavily
v2bot/parser.py              share-link parsing (vmess/vless/trojan/ss/ssr/hy2/tuic/wg) + dedup hash
v2bot/collector.py           stage1 collect (concurrent fetch) + stage2 dedup/upsert
v2bot/outbound.py            link -> xray / sing-box JSON config
v2bot/tester.py              binaries bootstrap, stage3 TCP, geo, stage4 speed (real DL/UL through core), stage5 filter/score
v2bot/pipeline.py            Pipeline class: timer loop, run_once, live log listeners
v2bot/state_sync.py          persistence to `state` git branch every N seconds + relaunch via GH_PAT
v2bot/bot/                   Telegram UI (aiogram 3): handlers, keyboards, access control, settings editor, subs, admins
v2bot/ai/                    kill_pv2 AI: registry.py (tools+budget), tools.py (this file), memory.py, skills.py,
                             prompt.py (3-tier system prompt), agent.py (conversation loop + approvals), llm.py (OpenAI-compatible client)
data/state.db                SQLite database (persisted). data/memories/MEMORY.md, USER.md. data/skills/<name>/SKILL.md. data/subs/*.txt
Secrets (env only): BOT_TOKEN, ADMIN_ID, GH_PAT, TAVILY_API_KEY. AI base_url/key/model live in settings table (key encrypted).
To change a setting: `set_setting(key, value)`. To change scan interval: key interval_minutes. Threads: tcp_concurrency / speed_concurrency.
To add a source: add_source(url, kind). To rebuild a sub: create_subscription(...). To run the pipeline now: run_pipeline().
Code changes land in the working tree of the current run; they persist only if committed (git_commit_push, needs approval) — the
`state` branch holds data/ only, code lives on `main`.
"""


@registry.register("project_map", "Return the project architecture map: every file, what it does, where data lives, which key to change for what.")
async def project_map():
    return PROJECT_MAP.strip()


@registry.register("list_files", "List files under a project directory (relative path).",
                   OBJ({"path": S("relative dir, default '.'"), "depth": I("max depth, default 2")}))
async def list_files(path: str = ".", depth: int = 2):
    base = _safe_path(path)
    out = []
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base)
        if any(part in ("node_modules", "__pycache__", ".git", "bin", "tmp", "_state_worktree") for part in rel.parts):
            continue
        if len(rel.parts) > depth:
            continue
        out.append(f"{'d' if p.is_dir() else 'f'} {rel}{'' if p.is_dir() else f'  ({p.stat().st_size}B)'}")
    return "\n".join(out[:400])


@registry.register("read_file", "Read a text file from the project (optionally a line range).",
                   OBJ({"path": S("relative path"), "start": I("1-based start line"), "end": I("end line (inclusive)")}, ["path"]), max_result_chars=20000)
async def read_file(path: str, start: int = 1, end: int = 0):
    p = _safe_path(path)
    if not p.is_file():
        return f"ERROR: not a file: {path}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    end = end or min(len(lines), start + 400)
    return "\n".join(f"{i:5d}| {l}" for i, l in enumerate(lines[start - 1:end], start))


@registry.register("search_code", "Grep the project source for a regex.", OBJ({"pattern": S("regex"), "path": S("subdir, default '.'")}, ["pattern"]))
async def search_code(pattern: str, path: str = "."):
    rx = re.compile(pattern)
    hits = []
    for p in _safe_path(path).rglob("*"):
        if p.suffix not in (".py", ".yml", ".yaml", ".md", ".txt", ".json") or ".git" in p.parts or "bin" in p.parts:
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()[:160]}")
        except Exception:
            pass
        if len(hits) > 200:
            break
    return "\n".join(hits) or "(no matches)"


@registry.register("write_file", "Create or overwrite a file in the project. SENSITIVE: needs user approval.",
                   OBJ({"path": S("relative path"), "content": S("full new content")}, ["path", "content"]),
                   risk=SENSITIVE, approval_reason="writes a file in the project")
async def write_file(path: str, content: str):
    p = _safe_path(path)
    old = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    diff = "".join(difflib.unified_diff(old.splitlines(True), content.splitlines(True), "old", "new", n=1))
    return f"written {len(content)} chars to {path}\n{diff[:3000]}"


@registry.register("edit_file", "Replace an exact substring in a file (must be unique). SENSITIVE: needs approval.",
                   OBJ({"path": S("relative path"), "old": S("exact text to replace"), "new": S("replacement")}, ["path", "old", "new"]),
                   risk=SENSITIVE, approval_reason="edits project code")
async def edit_file(path: str, old: str, new: str):
    p = _safe_path(path)
    txt = p.read_text(encoding="utf-8")
    n = txt.count(old)
    if n != 1:
        return f"ERROR: old text found {n} times (must be exactly 1)"
    p.write_text(txt.replace(old, new), encoding="utf-8")
    return f"edited {path}"


@registry.register("shell", "Run a shell command in the project root (timeout 120s). SENSITIVE: needs approval.",
                   OBJ({"command": S("bash command"), "timeout": I("seconds, default 120")}, ["command"]),
                   risk=SENSITIVE, approval_reason="executes a terminal command")
async def shell(command: str, timeout: int = 120):
    proc = await asyncio.create_subprocess_shell(command, cwd=str(ROOT), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return "ERROR: timeout"
    return f"$ {command}\n[exit {proc.returncode}]\n{out.decode('utf-8', 'replace')[-10000:]}"


@registry.register("run_tests", "Compile all python files and run the self-test suite (tests/selftest.py). Safe.")
async def run_tests():
    r = subprocess.run(["python", "-m", "compileall", "-q", "v2bot", "main.py"], cwd=ROOT, capture_output=True, text=True)
    out = f"compileall exit {r.returncode}\n{r.stdout}{r.stderr}"
    if (ROOT / "tests" / "selftest.py").exists():
        r2 = subprocess.run(["python", "tests/selftest.py"], cwd=ROOT, capture_output=True, text=True, timeout=300)
        out += f"\nselftest exit {r2.returncode}\n{r2.stdout[-6000:]}{r2.stderr[-3000:]}"
    return out


@registry.register("git_status", "Show git status/diff summary of code changes made in this run.")
async def git_status():
    r = subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True)
    d = subprocess.run(["git", "diff", "--stat"], cwd=ROOT, capture_output=True, text=True)
    return f"{r.stdout}\n{d.stdout}" or "(clean)"


@registry.register("git_commit_push", "Commit current code changes and push to the main branch using GH_PAT. DANGEROUS: needs approval.",
                   OBJ({"message": S("commit message")}, ["message"]), risk=DANGEROUS, approval_reason="pushes code to GitHub main branch")
async def git_commit_push(message: str):
    if not (ENV.gh_pat and ENV.gh_repo):
        return "ERROR: GH_PAT/GITHUB_REPOSITORY not available"
    url = f"https://x-access-token:{ENV.gh_pat}@github.com/{ENV.gh_repo}.git"
    cmds = [["git", "config", "user.name", "kill_pv2-ai"], ["git", "config", "user.email", "kill_pv2@users.noreply.github.com"],
            ["git", "add", "-A", "--", *CODE_DIRS], ["git", "commit", "-m", f"[kill_pv2] {message}"],
            ["git", "push", url, f"HEAD:{ENV.gh_ref or 'main'}"]]
    log = []
    for c in cmds:
        r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
        log.append(f"$ {' '.join(x if 'x-access-token' not in x else '<remote>' for x in c)} -> {r.returncode}\n{(r.stdout + r.stderr)[-500:]}")
        if r.returncode and c[1] != "config":
            break
    return "\n".join(log)


# ===================================================================== bot / pipeline control
@registry.register("bot_status", "Current pipeline stage, counters, settings snapshot, last runs.")
async def bot_status(ctx):
    st = await ctx.db.config_stats()
    runs = [dict(r) for r in await ctx.db.recent_runs(5)]
    return {"stage": ctx.pipeline.stage, "running": ctx.pipeline.running, "next_run_in_s": int(ctx.pipeline.next_run_in()),
            "stats": st, "recent_runs": runs, "settings": {k: v for k, v in ctx.db.all_settings().items() if k != "ai_api_key"}}


@registry.register("recent_logs", "Last N pipeline log lines.", OBJ({"n": I("default 40")}))
async def recent_logs(ctx, n: int = 40):
    return "\n".join(f"{time.strftime('%H:%M:%S', time.localtime(r['ts']))} [{r['stage']}] {r['msg']}" for r in await ctx.db.recent_logs(n))


@registry.register("run_pipeline", "Trigger a full scan now (collect->dedup->tcp->speed->filter). SENSITIVE.", risk=SENSITIVE,
                   approval_reason="starts a full scan run")
async def run_pipeline(ctx):
    return "started" if ctx.pipeline.trigger() else f"already running (stage {ctx.pipeline.stage})"


@registry.register("get_setting", "Read one or all settings.", OBJ({"key": S("setting key or empty for all")}))
async def get_setting(ctx, key: str = ""):
    s = ctx.db.all_settings()
    s["ai_api_key"] = "***" if s.get("ai_api_key") else ""
    return s.get(key, f"unknown key {key}") if key else s


@registry.register("set_setting", "Change a bot setting (see DEFAULT_SETTINGS in config.py). SENSITIVE.",
                   OBJ({"key": S("setting key"), "value": S("new value (JSON or plain)")}, ["key", "value"]),
                   risk=SENSITIVE, approval_reason="changes bot configuration")
async def set_setting(ctx, key: str, value: str):
    if key not in DEFAULT_SETTINGS:
        return f"ERROR: unknown setting {key}. Known: {', '.join(DEFAULT_SETTINGS)}"
    if key == "ai_api_key":
        return "ERROR: use the Telegram AI setup to change the API key"
    default = DEFAULT_SETTINGS[key]
    try:
        v = json.loads(value)
    except Exception:
        v = value
    if isinstance(default, bool):
        v = str(v).lower() in ("1", "true", "yes", "on")
    elif isinstance(default, int) and not isinstance(default, bool):
        v = int(float(v))
    elif isinstance(default, float):
        v = float(v)
    await ctx.db.set_setting(key, v)
    return f"{key} = {v!r}"


@registry.register("list_configs", "Query configs from the DB.",
                   OBJ({"limit": I("default 20"), "country": S("ISO2 e.g. US"), "protocol": S("vless|vmess|trojan|ss|hysteria2|tuic"),
                        "status": S("alive|tcp_ok|dead|new (default alive)"), "order": S("score|ping|dl|ul"), "max_ping": I("ms filter")}))
async def list_configs(ctx, limit: int = 20, country: str = "", protocol: str = "", status: str = "alive", order: str = "score", max_ping: int = 0):
    rows = await ctx.db.top_configs(limit * 3, country or None, protocol or None, status, order)
    if max_ping:
        rows = [r for r in rows if (r["http_ms"] or r["tcp_ms"] or 9e9) <= max_ping]
    return [{"hash": r["hash"], "proto": r["protocol"], "host": r["host"], "port": r["port"], "cc": r["country"],
             "tcp_ms": r["tcp_ms"], "http_ms": r["http_ms"], "dl_kbps": r["dl_kbps"], "ul_kbps": r["ul_kbps"], "score": r["score"],
             "link": r["link"]} for r in rows[:limit]]


@registry.register("history", "Daily test history, or best configs of one day (YYYY-MM-DD).", OBJ({"day": S("optional date")}))
async def history(ctx, day: str = ""):
    if day:
        return [dict(r) for r in await ctx.db.history_day(day)]
    return [dict(r) for r in await ctx.db.history_days(30)]


@registry.register("create_subscription",
                   "Build a subscription file from filtered configs and register it (user can fetch it with /sub NAME). SENSITIVE.",
                   OBJ({"name": S("sub name, slug"), "count": I("how many"), "country": S("ISO2 or comma list, optional"),
                        "protocol": S("optional"), "order": S("score|ping|dl|ul"), "max_ping": I("optional")}, ["name", "count"]),
                   risk=SENSITIVE, approval_reason="creates/overwrites a subscription")
async def create_subscription(ctx, name: str, count: int, country: str = "", protocol: str = "", order: str = "score", max_ping: int = 0):
    name = re.sub(r"[^a-zA-Z0-9_-]+", "-", name)[:32]
    picked: list = []
    countries = [c.strip().upper() for c in country.split(",") if c.strip()] or [None]
    per = max(1, count // len(countries))
    for cc in countries:
        rows = await ctx.db.top_configs(per * 4, cc, protocol or None, "alive", order)
        if max_ping:
            rows = [r for r in rows if (r["http_ms"] or r["tcp_ms"] or 9e9) <= max_ping]
        picked.extend(rows[:per])
    picked = picked[:count]
    hashes = [r["hash"] for r in picked]
    await ctx.db.save_sub(name, ctx.user_id, {"count": count, "country": country, "protocol": protocol, "order": order, "max_ping": max_ping}, hashes)
    links = [r["link"] for r in picked]
    (SUBS_DIR / f"{name}.txt").write_text(base64.b64encode("\n".join(links).encode()).decode())
    return {"name": name, "count": len(links), "file": f"data/subs/{name}.txt", "preview": [f"{r['protocol']} {r['country']} {r['host']} ping={r['http_ms'] or r['tcp_ms']}" for r in picked]}


@registry.register("list_sources", "List config sources with yield stats.", OBJ({"limit": I("default 50"), "failing_only": B("")}))
async def list_sources(ctx, limit: int = 50, failing_only: bool = False):
    rows = await ctx.db.sources(enabled_only=False)
    rows = sorted(rows, key=lambda r: -(r["last_count"] or 0))
    if failing_only:
        rows = [r for r in rows if (r["fail_count"] or 0) > (r["ok_count"] or 0)]
    return [{"id": r["id"], "url": r["url"], "kind": r["kind"], "enabled": r["enabled"], "last_count": r["last_count"],
             "ok": r["ok_count"], "fail": r["fail_count"], "by": r["added_by"]} for r in rows[:limit]]


@registry.register("add_source", "Add a config source URL. SENSITIVE.", OBJ({"url": S("http(s) url"), "kind": S("sub|raw|html|tg|auto")}, ["url"]),
                   risk=SENSITIVE, approval_reason="adds a new data source")
async def add_source(ctx, url: str, kind: str = "auto"):
    if not url.startswith("http"):
        return "ERROR: url must start with http"
    if "t.me/" in url and "/s/" not in url:
        url = url.replace("t.me/", "t.me/s/")
        kind = "tg"
    ok = await ctx.db.add_source(url, kind, added_by=f"ai:{ctx.user_id}")
    return "added" if ok else "already exists"


@registry.register("toggle_source", "Enable/disable a source by id. SENSITIVE.", OBJ({"id": I(""), "enabled": B("")}, ["id", "enabled"]),
                   risk=SENSITIVE, approval_reason="changes source list")
async def toggle_source(ctx, id: int, enabled: bool):
    await ctx.db.execute("UPDATE sources SET enabled=? WHERE id=?", (int(enabled), id))
    return "ok"


@registry.register("fetch_url", "Fetch a URL and report how many proxy links it contains (+ first 1500 chars). Safe read-only.",
                   OBJ({"url": S("")}, ["url"]))
async def fetch_url(url: str):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=20), ssl=False,
                             headers={"User-Agent": "Mozilla/5.0"}) as r:
                txt = (await r.read())[:2_000_000].decode("utf-8", "ignore")
                status = r.status
    except Exception as e:
        return f"ERROR: {e}"
    links = extract_links(txt)
    protos: dict[str, int] = {}
    for l in links:
        protos[l.split("://")[0]] = protos.get(l.split("://")[0], 0) + 1
    return {"status": status, "links": len(links), "protocols": protos, "head": txt[:1500]}


@registry.register("web_search", "Search the web with Tavily (needs TAVILY_API_KEY).",
                   OBJ({"query": S(""), "max_results": I("default 8"), "days": I("recency filter in days, optional")}, ["query"]))
async def web_search(query: str, max_results: int = 8, days: int = 0):
    if not ENV.tavily_key:
        return "ERROR: TAVILY_API_KEY not set"
    body = {"api_key": ENV.tavily_key, "query": query, "max_results": max_results, "search_depth": "advanced", "include_answer": False}
    if days:
        body["days"] = days
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://api.tavily.com/search", json=body, timeout=aiohttp.ClientTimeout(total=40)) as r:
                data = await r.json()
    except Exception as e:
        return f"ERROR: tavily {e}"
    return [{"title": x.get("title"), "url": x.get("url"), "content": (x.get("content") or "")[:400]} for x in data.get("results", [])]


@registry.register("discover_sources",
                   "Run the automatic source-discovery routine: Tavily search with DISCOVERY_QUERIES, probe each candidate URL, "
                   "return the ones that actually contain proxy links. Does not add them unless auto_add is true.",
                   OBJ({"max_queries": I("default 4"), "auto_add": B("add good ones directly (SENSITIVE)")}),
                   risk=SAFE)
async def discover_sources(ctx, max_queries: int = 4, auto_add: bool = False):
    if not ENV.tavily_key:
        return "ERROR: TAVILY_API_KEY not set"
    known = {r["url"] for r in await ctx.db.sources(enabled_only=False)}
    cands: dict[str, str] = {}
    import random
    for q in random.sample(DISCOVERY_QUERIES, min(max_queries, len(DISCOVERY_QUERIES))):
        res = await web_search(q, 10)
        if isinstance(res, str):
            continue
        for item in res:
            u = item["url"]
            if "github.com" in u and "/blob/" in u:
                u = u.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            if "t.me/" in u and "/s/" not in u:
                u = re.sub(r"t\.me/([A-Za-z0-9_]+).*", r"t.me/s/\1", u)
            if u not in known:
                cands[u] = q
    good = []
    for u in list(cands)[:30]:
        r = await fetch_url(u)
        if isinstance(r, dict) and r["links"] >= 5:
            kind = "tg" if "t.me/s/" in u else "sub"
            good.append({"url": u, "links": r["links"], "kind": kind})
            if auto_add or ctx.db.setting("auto_add_sources"):
                await ctx.db.add_source(u, kind, added_by="ai:discovery")
    await ctx.db.kv_set("last_discovery", time.time())
    return {"candidates_probed": min(len(cands), 30), "good": good, "added": bool(auto_add or ctx.db.setting("auto_add_sources"))}


# ===================================================================== memory / skills / sessions
@registry.register("memory", "Persistent memory. action=add|replace|remove, target=memory|user. Use for user preferences, "
                   "environment facts, corrections, completed work. replace/remove locate the entry with a unique substring old_text.",
                   OBJ({"action": S("add|replace|remove"), "target": S("memory|user"), "content": S("entry text"),
                        "old_text": S("unique substring of the entry to replace/remove")}, ["action", "target"]), toolset="memory")
async def memory(ctx, action: str, target: str, content: str = "", old_text: str = ""):
    if target not in ("memory", "user"):
        return "ERROR: target must be memory|user"
    m = ctx.memory
    if action == "add":
        res = m.add(target, content)
    elif action == "replace":
        res = m.replace(target, old_text, content)
    elif action == "remove":
        res = m.remove(target, old_text)
    else:
        return "ERROR: bad action"
    if res.get("success"):
        ctx.memory_events.append((action, target, content or res.get("old", "")))
    return res


@registry.register("skills_list", "List learned skills (name + description).", toolset="skills")
async def skills_list(ctx):
    return ctx.skills.list()


@registry.register("skill_view", "Load the full SKILL.md of a skill.", OBJ({"name": S("")}, ["name"]), toolset="skills")
async def skill_view(ctx, name: str):
    body = ctx.skills.view(name)
    if body:
        await ctx.db.execute("INSERT INTO ai_skills_meta(name,created,updated,origin,uses) VALUES(?,?,?,?,1) "
                             "ON CONFLICT(name) DO UPDATE SET uses=uses+1", (name, time.time(), time.time(), "agent"))
    return body or f"no skill '{name}'"


@registry.register("skill_manage", "Create/update/delete a skill (a reusable procedure you learned). action=create|update|delete.",
                   OBJ({"action": S(""), "name": S(""), "description": S("one line"), "body": S("markdown procedure")}, ["action", "name"]),
                   toolset="skills", risk=SENSITIVE, approval_reason="modifies learned skills")
async def skill_manage(ctx, action: str, name: str, description: str = "", body: str = ""):
    if action in ("create", "update"):
        slug = ctx.skills.write(name, description, body)
        ctx.memory_events.append(("skill", slug, description))
        return f"skill '{slug}' saved"
    if action == "delete":
        return "deleted" if ctx.skills.delete(name) else "not found"
    return "ERROR: bad action"


@registry.register("session_search", "Full-text search over all past AI conversations (FTS5).", OBJ({"query": S(""), "limit": I("default 10")}, ["query"]), toolset="memory")
async def session_search(ctx, query: str, limit: int = 10):
    rows = await ctx.db.fetchall(
        "SELECT m.session_id, m.ts, m.role, snippet(ai_messages_fts, 0, '[', ']', '…', 24) snip FROM ai_messages_fts "
        "JOIN ai_messages m ON m.id=ai_messages_fts.rowid WHERE ai_messages_fts MATCH ? ORDER BY m.ts DESC LIMIT ?", (query, limit))
    return [{"session": r["session_id"], "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ts"])), "role": r["role"], "text": r["snip"]} for r in rows]


@registry.register("send_telegram_file", "Send a text file to the current chat (e.g. a subscription or a list of links).",
                   OBJ({"filename": S(""), "content": S("")}, ["filename", "content"]))
async def send_telegram_file(ctx, filename: str, content: str):
    await ctx.send_file(filename, content)
    return "sent"


@registry.register("list_admins", "List admins and permissions.", toolset="admin")
async def list_admins(ctx):
    return [{"id": r["id"], "perms": json.loads(r["permissions"]), "note": r["note"]} for r in await ctx.db.admins()] + [{"id": ENV.admin_id, "perms": "owner"}]


@registry.register("manage_admin", "Add/remove an admin or change permissions. DANGEROUS.",
                   OBJ({"action": S("add|remove"), "user_id": I(""), "permissions": S(f"comma list of {','.join(PERMISSIONS)} or 'all'")}, ["action", "user_id"]),
                   toolset="admin", risk=DANGEROUS, approval_reason="changes who controls the bot")
async def manage_admin(ctx, action: str, user_id: int, permissions: str = "all"):
    if action == "remove":
        await ctx.db.remove_admin(user_id)
        return "removed"
    perms = PERMISSIONS if permissions == "all" else [p.strip() for p in permissions.split(",") if p.strip() in PERMISSIONS]
    await ctx.db.add_admin(user_id, ctx.user_id, perms, "via kill_pv2")
    return f"admin {user_id} -> {perms}"
