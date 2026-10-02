"""Builds Bot + Dispatcher, wires agent callbacks, registers slash commands."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from ..config import ENV
from .common import Ctx
from . import handlers_core, handlers_admin

LOG = logging.getLogger("v2bot.bot")


async def build(db, pipeline, agent, chain: int) -> tuple[Bot, Dispatcher]:
    bot = Bot(ENV.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(handlers_core.router)
    dp.include_router(handlers_admin.router)
    Ctx.db, Ctx.pipeline, Ctx.agent, Ctx.bot, Ctx.chain = db, pipeline, agent, bot, chain
    agent.on_approval = handlers_admin.on_approval
    agent.send_file = handlers_admin.send_file_cb

    @dp.errors()
    async def on_error(event, exception=None):
        LOG.exception("handler error: %s", getattr(event, "exception", exception))
        return True

    try:
        await bot.set_my_commands([BotCommand(command=c, description=d[:60]) for c, d in handlers_core.COMMANDS[:50]])
    except Exception as e:
        LOG.warning("set_my_commands: %s", e)
    return bot, dp


async def notify_admin(text: str):
    if Ctx.bot and ENV.admin_id:
        try:
            await Ctx.bot.send_message(ENV.admin_id, text, disable_web_page_preview=True)
        except Exception as e:
            LOG.warning("notify_admin: %s", e)
