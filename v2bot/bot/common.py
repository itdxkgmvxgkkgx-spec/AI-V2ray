"""Shared context + helpers for all handler modules."""
from __future__ import annotations

import time

from aiogram import Bot
from aiogram.types import CallbackQuery, Message

from ..config import DEFAULT_SETTINGS
from ..i18n import t
from .. import state_sync
from .ui import back_kb, flag, fmt_dur, main_inline, main_reply, role

START_TS = time.time()


class Ctx:
    """Injected singletons (set in main)."""
    db = None
    pipeline = None
    agent = None
    bot: Bot = None
    chain: int = 0


async def user_of(m: Message | CallbackQuery):
    u = m.from_user
    row = await Ctx.db.touch_user(u.id, u.username, u.first_name)
    rp = await role(Ctx.db, u.id)
    return row, row["lang"], rp


def is_cb(o) -> bool:
    return isinstance(o, CallbackQuery)


async def deny(obj, lang):
    txt = t(lang, "no_access")
    if is_cb(obj):
        await obj.answer(txt, show_alert=True)
    else:
        await obj.answer(txt)


async def show(obj, text: str, kb=None, *, edit: bool = True):
    """Send or edit depending on whether obj is a callback; tolerant to Telegram edit errors."""
    msg = obj.message if is_cb(obj) else obj
    text = text[:4000]
    try:
        if is_cb(obj) and edit:
            await msg.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        else:
            await msg.answer(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        if "not modified" not in str(e):
            try:
                await msg.answer(text, reply_markup=kb, disable_web_page_preview=True)
            except Exception:
                pass
    if is_cb(obj):
        try:
            await obj.answer()
        except Exception:
            pass


async def status_text(lang: str) -> str:
    st = await Ctx.db.config_stats()
    p = Ctx.pipeline
    srcs = await Ctx.db.sources()
    lp = state_sync.last_push()
    return t(lang, "status", uptime=fmt_dur(time.time() - START_TS), run=p.run_id or "-",
             runtime=fmt_dur(time.time() - p.run_started) if p.run_started and p.running else "idle", stage=p.stage,
             interval=Ctx.db.setting("interval_minutes"), next=fmt_dur(p.next_run_in()), total=st["total"], alive=st["alive"],
             tcp_ok=st["tcp_ok"], dead=st["dead"], new=st["new"], sources=len(srcs),
             protos=", ".join(f"{k} {v}" for k, v in list(st["protocols"].items())[:6]) or "—",
             countries=" ".join(f"{flag(k)}{v}" for k, v in st["countries"].items()) or "—",
             push=(fmt_dur(time.time() - lp) + " ago") if lp else "never", chain=Ctx.chain)


async def menu(obj, lang, rp, edit=True):
    st = await Ctx.db.config_stats()
    text = t(lang, "menu", status=f"{Ctx.pipeline.stage}{' 🏃' if Ctx.pipeline.running else ''}", alive=st["alive"], total=st["total"],
             next=fmt_dur(Ctx.pipeline.next_run_in()))
    if is_cb(obj):
        await show(obj, text, main_inline(lang, rp), edit=edit)
    else:
        await obj.answer(text, reply_markup=main_reply(lang, rp))
        await obj.answer("👇", reply_markup=main_inline(lang, rp))


def coerce_setting(key: str, raw: str):
    default = DEFAULT_SETTINGS[key]
    raw = raw.strip()
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "on", "yes", "بله", "روشن")
    if isinstance(default, int):
        return int(float(raw))
    if isinstance(default, float):
        return float(raw)
    return raw


async def apply_setting(key: str, value):
    await Ctx.db.set_setting(key, value)
    if Ctx.agent:
        if key in ("memory_char_limit", "user_char_limit"):
            Ctx.agent.memory.limits = {"memory": int(Ctx.db.setting("memory_char_limit")), "user": int(Ctx.db.setting("user_char_limit"))}
        if key.startswith("ai_"):
            Ctx.agent.invalidate_prompt()
