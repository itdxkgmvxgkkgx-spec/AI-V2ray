"""SQLite (WAL) persistence layer. Everything the bot knows lives here.

Tables
------
settings        key/value JSON settings (editable from Telegram)
users           every Telegram user we have seen (+ language)
admins          admin ids + permission list
sources         subscription / raw URLs we collect from (+ health stats)
configs         unique configs (hash of normalized link) + latest test results
tests           every test ever run (history) -> `/history`
runs            each pipeline run with stage counters
logs            ring-buffer of log lines (also mirrored to file)
subs            generated subscription files
ai_sessions     AI chat sessions (one per telegram chat unless /ai_new)
ai_messages     AI messages (FTS5 searchable)
ai_pending      pending approvals for sensitive AI actions
ai_skills_meta  skill provenance
kv              generic key-value for misc runtime state
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from .config import DB_PATH, DEFAULT_SETTINGS

SCHEMA_VERSION = 3

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL);

CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, lang TEXT DEFAULT 'en',
  first_seen REAL, last_seen REAL, state TEXT DEFAULT '', state_data TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS admins(
  id INTEGER PRIMARY KEY, added_by INTEGER, added_at REAL,
  permissions TEXT NOT NULL DEFAULT '[]', note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sources(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT UNIQUE NOT NULL, kind TEXT DEFAULT 'auto',   -- auto|sub|raw|html|tg
  enabled INTEGER DEFAULT 1, added_by TEXT DEFAULT 'builtin', added_at REAL,
  last_fetch REAL, last_ok REAL, ok_count INTEGER DEFAULT 0, fail_count INTEGER DEFAULT 0,
  last_count INTEGER DEFAULT 0, total_found INTEGER DEFAULT 0, note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS configs(
  hash TEXT PRIMARY KEY,
  link TEXT NOT NULL, protocol TEXT, host TEXT, port INTEGER, remark TEXT,
  network TEXT, security TEXT, sni TEXT, country TEXT DEFAULT '', ip TEXT DEFAULT '',
  first_seen REAL, last_seen REAL, seen_count INTEGER DEFAULT 1, source_id INTEGER,
  tcp_ms REAL, dl_kbps REAL, ul_kbps REAL, http_ms REAL,
  score REAL DEFAULT 0, status TEXT DEFAULT 'new',   -- new|tcp_ok|alive|dead
  last_test REAL, ok_tests INTEGER DEFAULT 0, fail_tests INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_configs_status ON configs(status);
CREATE INDEX IF NOT EXISTS idx_configs_score ON configs(score DESC);
CREATE INDEX IF NOT EXISTS idx_configs_country ON configs(country);
CREATE INDEX IF NOT EXISTS idx_configs_last_seen ON configs(last_seen);

CREATE TABLE IF NOT EXISTS tests(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hash TEXT NOT NULL, run_id INTEGER, stage TEXT, ts REAL,
  tcp_ms REAL, http_ms REAL, dl_kbps REAL, ul_kbps REAL, ok INTEGER, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_tests_ts ON tests(ts);
CREATE INDEX IF NOT EXISTS idx_tests_hash ON tests(hash);

CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started REAL, finished REAL, stage TEXT DEFAULT 'init', trigger TEXT DEFAULT 'timer',
  found INTEGER DEFAULT 0, unique_new INTEGER DEFAULT 0, deduped INTEGER DEFAULT 0,
  tcp_tested INTEGER DEFAULT 0, tcp_ok INTEGER DEFAULT 0,
  speed_tested INTEGER DEFAULT 0, alive INTEGER DEFAULT 0, error TEXT
);

CREATE TABLE IF NOT EXISTS logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT, stage TEXT, msg TEXT
);

CREATE TABLE IF NOT EXISTS subs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, created_by INTEGER, created_at REAL,
  updated_at REAL, filter_json TEXT, hashes TEXT, count INTEGER DEFAULT 0, auto_refresh INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ai_sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER, title TEXT,
  started REAL, last_active REAL, active INTEGER DEFAULT 1, parent_id INTEGER,
  model TEXT, tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, summary TEXT
);
CREATE TABLE IF NOT EXISTS ai_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, ts REAL, role TEXT,
  content TEXT, tool_calls TEXT, tool_call_id TEXT, name TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_messages_session ON ai_messages(session_id);
CREATE VIRTUAL TABLE IF NOT EXISTS ai_messages_fts USING fts5(content, content='ai_messages', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS ai_msg_ai AFTER INSERT ON ai_messages BEGIN
  INSERT INTO ai_messages_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS ai_msg_ad AFTER DELETE ON ai_messages BEGIN
  INSERT INTO ai_messages_fts(ai_messages_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

CREATE TABLE IF NOT EXISTS ai_pending(
  id TEXT PRIMARY KEY, session_id INTEGER, chat_id INTEGER, created REAL,
  tool TEXT, args TEXT, reason TEXT, status TEXT DEFAULT 'pending', result TEXT
);

CREATE TABLE IF NOT EXISTS ai_skills_meta(
  name TEXT PRIMARY KEY, created REAL, updated REAL, origin TEXT, uses INTEGER DEFAULT 0, description TEXT
);

CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
"""


class DB:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._settings_cache: dict[str, Any] = {}

    # ---------------------------------------------------------------- lifecycle
    async def open(self) -> "DB":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path, timeout=30)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        await self._conn.commit()
        await self._load_settings()
        return self

    async def close(self):
        if self._conn:
            await self._conn.commit()
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "DB not opened"
        return self._conn

    async def execute(self, sql: str, params: Iterable = ()) -> aiosqlite.Cursor:
        async with self._lock:
            cur = await self.conn.execute(sql, tuple(params))
            await self.conn.commit()
            return cur

    async def executemany(self, sql: str, rows: Iterable[Iterable]):
        async with self._lock:
            await self.conn.executemany(sql, [tuple(r) for r in rows])
            await self.conn.commit()

    async def fetchone(self, sql: str, params: Iterable = ()):
        cur = await self.conn.execute(sql, tuple(params))
        row = await cur.fetchone()
        await cur.close()
        return row

    async def fetchall(self, sql: str, params: Iterable = ()) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(sql, tuple(params))
        rows = await cur.fetchall()
        await cur.close()
        return list(rows)

    async def checkpoint(self):
        """Flush WAL into the main file so a `git add data/state.db` captures everything."""
        async with self._lock:
            await self.conn.commit()
            await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # ---------------------------------------------------------------- settings
    async def _load_settings(self):
        rows = await self.fetchall("SELECT key,value FROM settings")
        self._settings_cache = dict(DEFAULT_SETTINGS)
        for r in rows:
            try:
                self._settings_cache[r["key"]] = json.loads(r["value"])
            except json.JSONDecodeError:
                self._settings_cache[r["key"]] = r["value"]

    def setting(self, key: str, default: Any = None) -> Any:
        return self._settings_cache.get(key, DEFAULT_SETTINGS.get(key, default))

    def all_settings(self) -> dict:
        return dict(self._settings_cache)

    async def set_setting(self, key: str, value: Any):
        self._settings_cache[key] = value
        await self.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value), time.time()),
        )

    # ---------------------------------------------------------------- kv
    async def kv_get(self, key: str, default: Any = None) -> Any:
        row = await self.fetchone("SELECT value FROM kv WHERE key=?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]

    async def kv_set(self, key: str, value: Any):
        await self.execute(
            "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value), time.time()),
        )

    # ---------------------------------------------------------------- users / admins
    async def touch_user(self, uid: int, username: str | None, first_name: str | None) -> aiosqlite.Row:
        now = time.time()
        row = await self.fetchone("SELECT * FROM users WHERE id=?", (uid,))
        if row:
            await self.execute("UPDATE users SET username=?, first_name=?, last_seen=? WHERE id=?",
                               (username, first_name, now, uid))
        else:
            await self.execute(
                "INSERT INTO users(id,username,first_name,lang,first_seen,last_seen) VALUES(?,?,?,?,?,?)",
                (uid, username, first_name, self.setting("default_lang", "en"), now, now))
        return await self.fetchone("SELECT * FROM users WHERE id=?", (uid,))

    async def user_lang(self, uid: int) -> str:
        row = await self.fetchone("SELECT lang FROM users WHERE id=?", (uid,))
        return row["lang"] if row else self.setting("default_lang", "en")

    async def set_user_lang(self, uid: int, lang: str):
        await self.execute("UPDATE users SET lang=? WHERE id=?", (lang, uid))

    async def set_user_state(self, uid: int, state: str, data: dict | None = None):
        await self.execute("UPDATE users SET state=?, state_data=? WHERE id=?",
                           (state, json.dumps(data or {}), uid))

    async def get_user_state(self, uid: int) -> tuple[str, dict]:
        row = await self.fetchone("SELECT state,state_data FROM users WHERE id=?", (uid,))
        if not row:
            return "", {}
        try:
            return row["state"] or "", json.loads(row["state_data"] or "{}")
        except Exception:
            return row["state"] or "", {}

    async def admins(self) -> list[aiosqlite.Row]:
        return await self.fetchall("SELECT * FROM admins ORDER BY added_at")

    async def admin_perms(self, uid: int) -> list[str] | None:
        row = await self.fetchone("SELECT permissions FROM admins WHERE id=?", (uid,))
        return json.loads(row["permissions"]) if row else None

    async def add_admin(self, uid: int, by: int, perms: list[str], note: str = ""):
        await self.execute(
            "INSERT INTO admins(id,added_by,added_at,permissions,note) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET permissions=excluded.permissions, note=excluded.note",
            (uid, by, time.time(), json.dumps(perms), note))

    async def remove_admin(self, uid: int):
        await self.execute("DELETE FROM admins WHERE id=?", (uid,))

    # ---------------------------------------------------------------- sources
    async def add_source(self, url: str, kind: str = "auto", added_by: str = "builtin", note: str = "") -> bool:
        cur = await self.execute(
            "INSERT OR IGNORE INTO sources(url,kind,added_by,added_at,note) VALUES(?,?,?,?,?)",
            (url.strip(), kind, added_by, time.time(), note))
        return cur.rowcount > 0

    async def sources(self, enabled_only: bool = True) -> list[aiosqlite.Row]:
        q = "SELECT * FROM sources" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY id"
        return await self.fetchall(q)

    async def source_result(self, sid: int, ok: bool, count: int):
        now = time.time()
        if ok:
            await self.execute(
                "UPDATE sources SET last_fetch=?, last_ok=?, ok_count=ok_count+1, last_count=?, total_found=total_found+? WHERE id=?",
                (now, now, count, count, sid))
        else:
            await self.execute("UPDATE sources SET last_fetch=?, fail_count=fail_count+1, last_count=0 WHERE id=?", (now, sid))
            # auto-disable sources that never worked and failed 10+ times (admin/AI can re-enable)
            await self.execute("UPDATE sources SET enabled=0, note='auto-disabled: never yielded' WHERE id=? AND ok_count=0 AND fail_count>=10", (sid,))

    # ---------------------------------------------------------------- configs
    async def upsert_configs(self, items: list[dict]) -> int:
        """Insert parsed configs; returns number of brand-new hashes."""
        if not items:
            return 0
        now = time.time()
        hashes = [i["hash"] for i in items]
        existing: set[str] = set()
        for i in range(0, len(hashes), 900):
            chunk = hashes[i:i + 900]
            rows = await self.fetchall(
                f"SELECT hash FROM configs WHERE hash IN ({','.join('?' * len(chunk))})", chunk)
            existing.update(r["hash"] for r in rows)
        new_rows, upd_rows = [], []
        for it in items:
            if it["hash"] in existing:
                upd_rows.append((now, it["hash"]))
            else:
                existing.add(it["hash"])
                new_rows.append((it["hash"], it["link"], it["protocol"], it["host"], it["port"], it["remark"],
                                 it.get("network"), it.get("security"), it.get("sni"), now, now, it.get("source_id")))
        if new_rows:
            await self.executemany(
                "INSERT OR IGNORE INTO configs(hash,link,protocol,host,port,remark,network,security,sni,first_seen,last_seen,source_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", new_rows)
        if upd_rows:
            await self.executemany("UPDATE configs SET last_seen=?, seen_count=seen_count+1 WHERE hash=?", upd_rows)
        return len(new_rows)

    async def configs_for_tcp(self, limit: int) -> list[aiosqlite.Row]:
        retest = self.setting("retest_alive_hours", 6) * 3600
        cutoff = time.time() - retest
        return await self.fetchall(
            "SELECT hash,link,protocol,host,port FROM configs WHERE host IS NOT NULL AND ("
            " status='new' OR last_test IS NULL OR last_test<? ) "
            "ORDER BY CASE status WHEN 'alive' THEN 0 WHEN 'tcp_ok' THEN 1 WHEN 'new' THEN 2 ELSE 3 END, last_seen DESC LIMIT ?",
            (cutoff, limit))

    async def record_tests(self, rows: list[tuple]):
        """rows: (hash, run_id, stage, ts, tcp_ms, http_ms, dl, ul, ok, error)"""
        if rows:
            await self.executemany(
                "INSERT INTO tests(hash,run_id,stage,ts,tcp_ms,http_ms,dl_kbps,ul_kbps,ok,error) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)

    async def update_config_result(self, h: str, **fields):
        fields["last_test"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        await self.execute(f"UPDATE configs SET {cols} WHERE hash=?", (*fields.values(), h))

    async def bulk_update_results(self, updates: list[tuple[str, dict]]):
        if not updates:
            return
        now = time.time()
        async with self._lock:
            for h, f in updates:
                f = dict(f)
                f["last_test"] = now
                cols = ", ".join(f"{k}=?" for k in f)
                await self.conn.execute(f"UPDATE configs SET {cols} WHERE hash=?", (*f.values(), h))
            await self.conn.commit()

    async def top_configs(self, limit: int = 20, country: str | None = None, protocol: str | None = None,
                          status: str = "alive", order: str = "score") -> list[aiosqlite.Row]:
        where, params = ["status=?"], [status]
        if country:
            where.append("country=?"); params.append(country.upper())
        if protocol:
            where.append("protocol=?"); params.append(protocol)
        order_sql = {"score": "score DESC", "ping": "tcp_ms ASC", "dl": "dl_kbps DESC", "ul": "ul_kbps DESC"}.get(order, "score DESC")
        params.append(limit)
        return await self.fetchall(
            f"SELECT * FROM configs WHERE {' AND '.join(where)} ORDER BY {order_sql} LIMIT ?", params)

    async def config_stats(self) -> dict:
        row = await self.fetchone(
            "SELECT COUNT(*) total, SUM(status='alive') alive, SUM(status='tcp_ok') tcp_ok, "
            "SUM(status='dead') dead, SUM(status='new') new FROM configs")
        protos = await self.fetchall("SELECT protocol, COUNT(*) c FROM configs WHERE status='alive' GROUP BY protocol ORDER BY c DESC")
        countries = await self.fetchall(
            "SELECT country, COUNT(*) c FROM configs WHERE status='alive' AND country!='' GROUP BY country ORDER BY c DESC LIMIT 12")
        return {"total": row["total"] or 0, "alive": row["alive"] or 0, "tcp_ok": row["tcp_ok"] or 0,
                "dead": row["dead"] or 0, "new": row["new"] or 0,
                "protocols": {r["protocol"]: r["c"] for r in protos},
                "countries": {r["country"]: r["c"] for r in countries}}

    async def prune_dead(self, days: int = 14) -> int:
        cutoff = time.time() - days * 86400
        cur = await self.execute("DELETE FROM configs WHERE status='dead' AND last_seen<? AND fail_tests>=3", (cutoff,))
        return cur.rowcount

    # ---------------------------------------------------------------- runs / logs
    async def start_run(self, trigger: str = "timer") -> int:
        cur = await self.execute("INSERT INTO runs(started,trigger) VALUES(?,?)", (time.time(), trigger))
        return cur.lastrowid

    async def update_run(self, run_id: int, **fields):
        cols = ", ".join(f"{k}=?" for k in fields)
        await self.execute(f"UPDATE runs SET {cols} WHERE id=?", (*fields.values(), run_id))

    async def recent_runs(self, limit: int = 10) -> list[aiosqlite.Row]:
        return await self.fetchall("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))

    async def add_log(self, level: str, stage: str, msg: str):
        await self.execute("INSERT INTO logs(ts,level,stage,msg) VALUES(?,?,?,?)", (time.time(), level, stage, msg[:2000]))
        ring = int(self.setting("log_ring_size", 400))
        await self.execute("DELETE FROM logs WHERE id < (SELECT MAX(id) FROM logs) - ?", (ring * 5,))

    async def recent_logs(self, limit: int = 30) -> list[aiosqlite.Row]:
        rows = await self.fetchall("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
        return rows[::-1]

    async def history_days(self, limit: int = 30) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT date(ts,'unixepoch') d, COUNT(*) tests, SUM(ok) ok, "
            "SUM(stage='speed' AND ok=1) alive, MIN(CASE WHEN ok=1 AND tcp_ms>0 THEN tcp_ms END) best_ms "
            "FROM tests GROUP BY d ORDER BY d DESC LIMIT ?", (limit,))

    async def history_day(self, day: str, limit: int = 20) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT t.hash, c.link, c.remark, c.protocol, c.country, t.tcp_ms, t.dl_kbps, t.ul_kbps, t.ts FROM tests t "
            "JOIN configs c ON c.hash=t.hash WHERE date(t.ts,'unixepoch')=? AND t.ok=1 AND t.stage='speed' "
            "ORDER BY t.dl_kbps DESC LIMIT ?", (day, limit))

    # ---------------------------------------------------------------- subs
    async def save_sub(self, name: str, by: int, filt: dict, hashes: list[str]) -> int:
        now = time.time()
        cur = await self.execute(
            "INSERT INTO subs(name,created_by,created_at,updated_at,filter_json,hashes,count) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at, filter_json=excluded.filter_json, "
            "hashes=excluded.hashes, count=excluded.count",
            (name, by, now, now, json.dumps(filt), json.dumps(hashes), len(hashes)))
        return cur.lastrowid

    async def subs(self) -> list[aiosqlite.Row]:
        return await self.fetchall("SELECT * FROM subs ORDER BY id")

    async def sub(self, name: str):
        return await self.fetchone("SELECT * FROM subs WHERE name=?", (name,))

    async def links_for_hashes(self, hashes: list[str]) -> list[str]:
        out = []
        for i in range(0, len(hashes), 900):
            chunk = hashes[i:i + 900]
            rows = await self.fetchall(f"SELECT hash,link FROM configs WHERE hash IN ({','.join('?' * len(chunk))})", chunk)
            m = {r["hash"]: r["link"] for r in rows}
            out.extend(m[h] for h in chunk if h in m)
        return out
