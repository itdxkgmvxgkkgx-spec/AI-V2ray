"""kill_pv2 conversation loop with persisted sessions, approval gates, memory notifications and context compression."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..config import ENV
from ..db import DB
from . import tools as _tools  # noqa: F401  (import registers tools)
from .llm import LLM, LLMError, decrypt
from .memory import MemoryStore
from .prompt import build_system_prompt
from .registry import DANGEROUS, SAFE, SENSITIVE, IterationBudget, registry
from .skills import SkillStore

MAX_HISTORY_CHARS = 60_000     # soft context window guard (chars ≈ tokens*4)
KEEP_TAIL = 12


@dataclass
class ToolContext:
    db: DB
    pipeline: object
    memory: MemoryStore
    skills: SkillStore
    user_id: int
    chat_id: int
    send_file: Callable[[str, str], Awaitable[None]]
    memory_events: list = field(default_factory=list)


class ApprovalRequired(Exception):
    def __init__(self, pending_id: str):
        self.pending_id = pending_id


class Agent:
    """One Agent object per process; sessions are per chat and stored in SQLite."""

    def __init__(self, db: DB, pipeline):
        self.db = db
        self.pipeline = pipeline
        self.memory = MemoryStore({"memory": int(db.setting("memory_char_limit", 4000)), "user": int(db.setting("user_char_limit", 2000))})
        self.skills = SkillStore()
        self._prompt_cache: dict[int, str] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        # callbacks set by the bot layer
        self.on_status: Callable[[int, str], Awaitable[None]] | None = None          # (chat_id, text)
        self.on_approval: Callable[[int, dict], Awaitable[None]] | None = None       # (chat_id, pending row)
        self.send_file: Callable[[int, str, str], Awaitable[None]] | None = None    # (chat_id, filename, content)

    # ------------------------------------------------------------- config
    def configured(self) -> bool:
        return bool(self.db.setting("ai_base_url") and decrypt(self.db.setting("ai_api_key", "")) and self.db.setting("ai_model"))

    def llm(self) -> LLM:
        return LLM(self.db.setting("ai_base_url"), decrypt(self.db.setting("ai_api_key", "")), self.db.setting("ai_model"),
                   float(self.db.setting("ai_temperature", 0.3)))

    # ------------------------------------------------------------- sessions
    async def session(self, chat_id: int, user_id: int, new: bool = False):
        row = await self.db.fetchone("SELECT * FROM ai_sessions WHERE chat_id=? AND active=1 ORDER BY id DESC LIMIT 1", (chat_id,))
        if row and not new:
            return row
        if row:
            await self.db.execute("UPDATE ai_sessions SET active=0 WHERE id=?", (row["id"],))
        now = time.time()
        cur = await self.db.execute("INSERT INTO ai_sessions(chat_id,user_id,title,started,last_active,model) VALUES(?,?,?,?,?,?)",
                                    (chat_id, user_id, "", now, now, self.db.setting("ai_model")))
        self._prompt_cache.pop(chat_id, None)
        return await self.db.fetchone("SELECT * FROM ai_sessions WHERE id=?", (cur.lastrowid,))

    async def _history(self, sid: int) -> list[dict]:
        rows = await self.db.fetchall("SELECT role,content,tool_calls,tool_call_id,name FROM ai_messages WHERE session_id=? ORDER BY id", (sid,))
        out = []
        for r in rows:
            m: dict = {"role": r["role"], "content": r["content"] or ""}
            if r["tool_calls"]:
                m["tool_calls"] = json.loads(r["tool_calls"])
            if r["tool_call_id"]:
                m["tool_call_id"] = r["tool_call_id"]
            if r["name"]:
                m["name"] = r["name"]
            out.append(m)
        return out

    async def _append(self, sid: int, m: dict):
        await self.db.execute("INSERT INTO ai_messages(session_id,ts,role,content,tool_calls,tool_call_id,name) VALUES(?,?,?,?,?,?,?)",
                              (sid, time.time(), m["role"], m.get("content") or "", json.dumps(m["tool_calls"]) if m.get("tool_calls") else None,
                               m.get("tool_call_id"), m.get("name")))
        await self.db.execute("UPDATE ai_sessions SET last_active=? WHERE id=?", (time.time(), sid))

    def _system(self, chat_id: int, sid: int, user_name: str, lang: str) -> str:
        if chat_id not in self._prompt_cache:
            self._prompt_cache[chat_id] = build_system_prompt(self.memory.render(), self.skills.index(), user_name, lang, sid, self.db.setting("ai_model"))
        return self._prompt_cache[chat_id]

    def invalidate_prompt(self, chat_id: int | None = None):
        if chat_id is None:
            self._prompt_cache.clear()
        else:
            self._prompt_cache.pop(chat_id, None)

    # ------------------------------------------------------------- compression
    async def _compress(self, sid: int, history: list[dict], llm: LLM) -> list[dict]:
        total = sum(len(m.get("content") or "") for m in history)
        if total < MAX_HISTORY_CHARS:
            return history
        head, tail = history[:-KEEP_TAIL], history[-KEEP_TAIL:]
        # make sure tail does not start with a tool result
        while tail and tail[0]["role"] == "tool":
            tail = tail[1:]
        text = "\n".join(f"{m['role']}: {(m.get('content') or '')[:800]}" for m in head)
        try:
            r = await llm.chat([{"role": "system", "content": "Summarize this conversation for continuity. Keep decisions, facts, pending tasks, user preferences. ≤400 words."},
                                {"role": "user", "content": text[:40000]}], None, 800)
            summary = r["content"]
        except LLMError:
            summary = "(older history dropped)"
        await self.db.execute("UPDATE ai_messages SET content='[compressed]' WHERE session_id=? AND id NOT IN "
                              "(SELECT id FROM ai_messages WHERE session_id=? ORDER BY id DESC LIMIT ?)", (sid, sid, KEEP_TAIL))
        await self.db.execute("UPDATE ai_sessions SET summary=? WHERE id=?", (summary, sid))
        if self.on_status:
            await self.on_status(sid, "🗜 context compressed")
        return [{"role": "user", "content": f"[Summary of earlier conversation]\n{summary}"},
                {"role": "assistant", "content": "Understood, continuing."}] + tail

    # ------------------------------------------------------------- main turn
    async def run_turn(self, chat_id: int, user_id: int, user_name: str, lang: str, text: str | None,
                       resume_pending: dict | None = None) -> str:
        """Run one user turn. If a sensitive tool is hit, persists a pending approval and returns '' (bot shows buttons).
        resume_pending: the approved/denied pending row to continue from."""
        lock = self._locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            if not self.configured():
                return "__not_configured__"
            llm = self.llm()
            sess = await self.session(chat_id, user_id)
            sid = sess["id"]
            ctx = ToolContext(self.db, self.pipeline, self.memory, self.skills, user_id, chat_id,
                              send_file=lambda fn, c: self.send_file(chat_id, fn, c) if self.send_file else None)
            if text is not None:
                await self._append(sid, {"role": "user", "content": text})
            history = await self._history(sid)
            if resume_pending:
                # execute (or refuse) the gated call and append its tool result
                tc_id, tool, args = resume_pending["tool_call_id"], resume_pending["tool"], json.loads(resume_pending["args"])
                if resume_pending["status"] == "approved":
                    result = await registry.call(tool, args, ctx)
                else:
                    result = "USER DENIED this action. Do not retry it; ask what to do instead."
                await self._append(sid, {"role": "tool", "tool_call_id": tc_id, "name": tool, "content": result})
                history = await self._history(sid)
            history = await self._compress(sid, history, llm)
            system = self._system(chat_id, sid, user_name, lang)
            budget = IterationBudget(int(self.db.setting("ai_max_iterations", 40)))
            tool_defs = registry.definitions()
            empty_retries = 0
            final = ""
            while True:
                if not budget.consume():
                    final = "⚠️ Iteration budget exhausted for this turn. Tell me how to continue."
                    break
                try:
                    r = await llm.chat([{"role": "system", "content": system}] + history, tool_defs)
                except LLMError as e:
                    final = f"❌ LLM error: <code>{_esc(str(e))}</code>"
                    break
                await self.db.execute("UPDATE ai_sessions SET tokens_in=tokens_in+?, tokens_out=tokens_out+? WHERE id=?",
                                      (r["usage"].get("prompt_tokens", 0), r["usage"].get("completion_tokens", 0), sid))
                calls = r["tool_calls"]
                if not calls:
                    if not r["content"].strip() and empty_retries < 2:
                        empty_retries += 1
                        history.append({"role": "user", "content": "(empty reply) Please answer or call a tool."})
                        continue
                    final = r["content"]
                    await self._append(sid, {"role": "assistant", "content": final})
                    break
                assistant_msg = {"role": "assistant", "content": r["content"] or "", "tool_calls": calls}
                await self._append(sid, assistant_msg)
                history.append(assistant_msg)
                paused = False
                for tc in calls:
                    name = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        args = _repair_json(raw_args)
                    entry = registry.get(name)
                    if self.on_status:
                        await self.on_status(chat_id, f"🔧 {name}")
                    needs = entry is not None and entry.risk in (SENSITIVE, DANGEROUS) and (
                        self.db.setting("ai_approval_required", True) or entry.risk == DANGEROUS)
                    if needs:
                        pid = uuid.uuid4().hex[:10]
                        await self.db.execute(
                            "INSERT INTO ai_pending(id,session_id,chat_id,created,tool,args,reason,status,result) VALUES(?,?,?,?,?,?,?,?,?)",
                            (pid, sid, chat_id, time.time(), name, json.dumps(args, ensure_ascii=False), entry.approval_reason, "pending", tc["id"]))
                        if self.on_approval:
                            await self.on_approval(chat_id, {"id": pid, "tool": name, "args": args, "reason": entry.approval_reason, "tool_call_id": tc["id"]})
                        paused = True
                        break
                    result = await registry.call(name, args, ctx)
                    tool_msg = {"role": "tool", "tool_call_id": tc["id"], "name": name, "content": result}
                    await self._append(sid, tool_msg)
                    history.append(tool_msg)
                if paused:
                    final = ""
                    break
            # memory notifications
            if ctx.memory_events:
                self.invalidate_prompt(chat_id)
                mode = self.db.setting("ai_memory_notifications", "verbose")
                if mode != "off" and self.on_status:
                    for action, target, content in ctx.memory_events:
                        icon = {"add": "➕", "replace": "✏️", "remove": "➖", "skill": "🧩"}.get(action, "💾")
                        line = f"💾 {'Skill' if action == 'skill' else 'Memory'} updated" if mode == "on" else \
                               f"💾 {target} {icon} <i>{_esc(content[:160])}</i>"
                        await self.on_status(chat_id, line)
            return final

    async def resume(self, pending_id: str, approved: bool, user_name: str, lang: str) -> str:
        row = await self.db.fetchone("SELECT * FROM ai_pending WHERE id=?", (pending_id,))
        if not row or row["status"] != "pending":
            return "⚠️ This approval is no longer pending."
        status = "approved" if approved else "denied"
        await self.db.execute("UPDATE ai_pending SET status=? WHERE id=?", (status, pending_id))
        pend = dict(row)
        pend["status"] = status
        pend["tool_call_id"] = row["result"]
        sess = await self.db.fetchone("SELECT user_id FROM ai_sessions WHERE id=?", (row["session_id"],))
        return await self.run_turn(row["chat_id"], sess["user_id"] if sess else 0, user_name, lang, None, resume_pending=pend)

    async def pending(self, chat_id: int) -> list:
        return await self.db.fetchall("SELECT * FROM ai_pending WHERE chat_id=? AND status='pending' ORDER BY created", (chat_id,))

    # ------------------------------------------------------------- autonomous jobs
    async def discovery_job(self, notify: Callable[[str], Awaitable[None]]):
        """Periodic Tavily discovery (no LLM needed). Adds sources only when auto_add_sources is on; otherwise reports."""
        hours = float(self.db.setting("discover_interval_hours", 12))
        if hours <= 0 or not ENV.tavily_key:
            return
        last = await self.db.kv_get("last_discovery", 0)
        if time.time() - last < hours * 3600:
            return
        ctx = ToolContext(self.db, self.pipeline, self.memory, self.skills, ENV.admin_id, ENV.admin_id, send_file=lambda *a: None)
        res = await registry.call("discover_sources", {"max_queries": 4}, ctx)
        try:
            data = json.loads(res)
            good = data.get("good", [])
            if good:
                lines = "\n".join(f"• <code>{_esc(g['url'])}</code> ({g['links']} links)" for g in good[:15])
                await notify(f"🔎 <b>kill_pv2 discovery</b> found {len(good)} new sources{' (added)' if data.get('added') else ' — use /source_add URL or enable auto_add_sources'}:\n{lines}")
        except Exception:
            pass


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _repair_json(s: str) -> dict:
    s = s.strip()
    if s.endswith(",}"):
        s = s[:-2] + "}"
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        return json.loads(s + "}")
    except Exception:
        return {"_raw": s}
