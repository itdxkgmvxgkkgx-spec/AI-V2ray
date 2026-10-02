"""Pipeline orchestrator: runs the 5 stages on a timer or on demand; exposes live status for /logs."""
from __future__ import annotations

import asyncio
import logging
import time
import traceback

from .collector import collect
from .config import LOG_FILE
from .db import DB
from .tester import ensure_binaries, stage_filter, stage_geo, stage_speed, stage_tcp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")])
LOG = logging.getLogger("v2bot")


class Pipeline:
    def __init__(self, db: DB):
        self.db = db
        self.stage = "idle"
        self.run_id: int | None = None
        self.run_started: float | None = None
        self.last_finished: float | None = None
        self.running = False
        self.bins: dict = {}
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self.last_stats: dict = {}
        self.listeners: list = []     # async callbacks(level, stage, msg) used by the bot for live log streaming

    async def log(self, stage: str, msg: str, level: str = "INFO"):
        self.stage = stage
        LOG.log(getattr(logging, level, logging.INFO), "[%s] %s", stage, msg)
        await self.db.add_log(level, stage, msg)
        for cb in list(self.listeners):
            try:
                await cb(level, stage, msg)
            except Exception:
                self.listeners.remove(cb)

    def next_run_in(self) -> float:
        interval = float(self.db.setting("interval_minutes", 30)) * 60
        base = self.last_finished or self.run_started or time.time()
        return max(0.0, base + interval - time.time())

    async def start(self):
        self.bins = await ensure_binaries(self.log)
        self._task = asyncio.create_task(self._loop(), name="pipeline")

    def trigger(self) -> bool:
        if self.running:
            return False
        self._wake.set()
        return True

    async def _loop(self):
        # run immediately at boot if last run is older than interval
        last = await self.db.kv_get("last_run_finished", 0)
        self.last_finished = last or None
        while True:
            wait = self.next_run_in()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            trig = "manual" if wait > 1 else "timer"
            await self.run_once(trig)

    async def run_once(self, trigger: str = "timer") -> dict:
        if self.running:
            return {"error": "already running"}
        self.running = True
        self.run_started = time.time()
        self.run_id = await self.db.start_run(trigger)
        rid = self.run_id
        try:
            await self.log("collect", f"run #{rid} started ({trigger})")
            await self.db.update_run(rid, stage="collect")
            found, uniq, new = await collect(self.db, self.log, rid)
            await self.db.update_run(rid, stage="tcp")
            n, ok, cand = await stage_tcp(self.db, self.log, rid)
            await self.db.update_run(rid, stage="geo")
            await stage_geo(self.db, self.log)
            # drop IR-located from candidates
            ir = {r["hash"] for r in await self.db.fetchall("SELECT hash FROM configs WHERE country='IR'")}
            cand = [c for c in cand if c[0]["hash"] not in ir]
            await self.db.update_run(rid, stage="speed")
            alive = await stage_speed(self.db, self.log, rid, cand, self.bins)
            await stage_geo(self.db, self.log)   # tag any alive configs that still miss a country
            await self.db.update_run(rid, stage="filter")
            st = await stage_filter(self.db, self.log)
            self.last_stats = {**st, "found": found, "unique": uniq, "new_configs": new, "tcp_tested": n, "tcp_ok": ok, "alive_now": alive}
            await self.db.update_run(rid, stage="done", finished=time.time())
            await self.log("done", f"run #{rid} finished: found {found} · unique {uniq} · new {new} · tcp_ok {ok} · alive {alive}")
        except Exception as e:
            LOG.error(traceback.format_exc())
            await self.log("error", f"run #{rid} failed: {e}", "ERROR")
            await self.db.update_run(rid, stage="error", finished=time.time(), error=str(e)[:500])
        finally:
            self.running = False
            self.last_finished = time.time()
            await self.db.kv_set("last_run_finished", self.last_finished)
            self.stage = "idle"
        return self.last_stats
