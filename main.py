"""v2ray_config bot — entrypoint.

Boot order: restore state branch -> open DB -> seed sources -> pipeline -> AI agent -> Telegram bot (polling)
            -> periodic state pusher -> discovery job -> relaunch timer (fires next GitHub Actions run before the 6h limit).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from v2bot import state_sync                                  # noqa: E402
from v2bot.config import ENV, PERMISSIONS                     # noqa: E402

LOG = logging.getLogger("v2bot.main")


async def seed_sources(db):
    from v2bot.sources import BUILTIN_SOURCES
    n = 0
    for url, kind in BUILTIN_SOURCES:
        n += await db.add_source(url, kind, "builtin")
    if n:
        LOG.info("seeded %d builtin sources", n)


async def amain():
    chain = int(os.environ.get("CHAIN", "0") or 0)
    # 1. restore persisted state (before DB open)
    restored = state_sync.restore()
    from v2bot.db import DB
    from v2bot.pipeline import Pipeline
    from v2bot.ai.agent import Agent
    from v2bot.bot import app as botapp
    from v2bot.i18n import t

    db = await DB().open()
    await seed_sources(db)
    await db.add_log("INFO", "boot", f"process started · chain {chain} · restored={restored} · run={ENV.gh_run_id or 'local'}")

    pipeline = Pipeline(db)
    agent = Agent(db, pipeline)
    stop = asyncio.Event()
    bot, dp = (None, None)
    if ENV.bot_token:
        bot, dp = await botapp.build(db, pipeline, agent, chain)
    else:
        LOG.warning("BOT_TOKEN missing — running pipeline only")

    if ENV.in_actions:
        await state_sync.cancel_other_runs()

    await pipeline.start()
    tasks = [asyncio.create_task(state_sync.periodic_pusher(db, lambda: db.setting("state_push_interval", 60)), name="pusher")]

    async def discovery_loop():
        while True:
            try:
                await agent.discovery_job(botapp.notify_admin)
            except Exception as e:
                LOG.warning("discovery: %s", e)
            await asyncio.sleep(900)

    tasks.append(asyncio.create_task(discovery_loop(), name="discovery"))

    async def relaunch_timer():
        if not ENV.in_actions:
            return
        limit = float(db.setting("max_run_minutes", ENV.max_run_minutes)) * 60
        await asyncio.sleep(limit)
        lang = await db.user_lang(ENV.admin_id)
        await botapp.notify_admin(t(lang, "relaunch"))
        await db.add_log("INFO", "relaunch", f"run time limit reached ({limit / 60:.0f} min) → dispatching next run")
        ok = await state_sync.relaunch("bot.yml", chain)
        if not ok:
            await botapp.notify_admin("⚠️ relaunch dispatch failed — check GH_PAT (needs `repo` + `workflow` scope). Will retry once.")
            await asyncio.sleep(60)
            await state_sync.relaunch("bot.yml", chain)
        stop.set()

    tasks.append(asyncio.create_task(relaunch_timer(), name="relaunch"))

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    if bot:
        lang = await db.user_lang(ENV.admin_id)
        await botapp.notify_admin(t(lang, "started", run=ENV.gh_run_id or "local", chain=chain))
        polling = asyncio.create_task(dp.start_polling(bot, handle_signals=False, allowed_updates=["message", "callback_query"]), name="polling")
        tasks.append(polling)

    await stop.wait()
    LOG.info("shutting down…")
    for tk in tasks:
        tk.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if bot:
        try:
            await bot.session.close()
        except Exception:
            pass
    await state_sync.push(db, "shutdown")
    await db.close()
    LOG.info("bye")


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
