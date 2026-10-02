"""Core handlers: start, language, menu, status, about, list/best/get, history, scan, logs, settings, public."""
from __future__ import annotations

import asyncio
import base64
import time

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton as IB, Message

from ..config import DEFAULT_SETTINGS
from ..i18n import LANGS, t
from .common import Ctx, apply_setting, coerce_setting, deny, is_cb, menu, show, status_text, user_of
from .ui import (back_kb, can, esc, flag, fmt_kbps, fmt_ms, history_kb, lang_kb, list_kb, main_inline, main_reply,
                 send_how_kb, settings_kb)

router = Router()

COMMANDS = [
    ("start", "Start / main menu"), ("menu", "Main menu"), ("status", "Pipeline status"), ("best", "Best configs"),
    ("list", "List configs: /list [score|ping|dl|ul]"), ("get", "/get N [score|ping|dl|ul] [CC] — send N configs"),
    ("history", "Daily history"), ("sub", "/sub NAME — fetch a subscription"), ("sub_create", "/sub_create NAME COUNT [CC] [proto]"),
    ("subs", "List subscriptions"), ("scan", "Run a scan now (admin)"), ("logs", "Logs (admin)"), ("settings", "Settings (admin)"),
    ("set", "/set KEY VALUE (admin)"), ("ai", "kill_pv2 AI menu (admin)"), ("ai_new", "New AI session"), ("ai_setup", "Reconfigure AI"),
    ("ai_pending", "Pending approvals"), ("ai_memory", "Show AI memory"), ("sources", "Config sources (admin)"),
    ("source_add", "/source_add URL [kind]"), ("admins", "Admins (owner)"), ("admin_add", "/admin_add ID perm1,perm2|all"),
    ("admin_del", "/admin_del ID"), ("public", "Toggle public mode (owner)"), ("lang", "Change language"),
    ("about", "How the bot works"), ("help", "Command list"), ("cancel", "Cancel current input"),
]


# ---------------------------------------------------------------- start / lang / menu
@router.message(CommandStart())
async def cmd_start(m: Message):
    row, lang, rp = await user_of(m)
    if rp[0] == "none":
        return await m.answer(t(lang, "admin_only"))
    picked = await Ctx.db.kv_get(f"langpicked:{m.from_user.id}", False)
    if not picked:
        await m.answer(t(lang, "choose_lang"), reply_markup=lang_kb())
        return
    await menu(m, lang, rp)


@router.message(Command("menu", "home"))
async def cmd_menu(m: Message):
    _, lang, rp = await user_of(m)
    if rp[0] == "none":
        return await deny(m, lang)
    await menu(m, lang, rp)


@router.message(Command("lang"))
async def cmd_lang(m: Message):
    _, lang, _ = await user_of(m)
    await m.answer(t(lang, "choose_lang"), reply_markup=lang_kb())


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(c: CallbackQuery):
    code = c.data.split(":")[1]
    if code not in LANGS:
        return await c.answer()
    await Ctx.db.set_user_lang(c.from_user.id, code)
    await Ctx.db.kv_set(f"langpicked:{c.from_user.id}", True)
    _, lang, rp = await user_of(c)
    try:
        await c.message.edit_text(t(lang, "lang_set", lang=LANGS[code]))
    except Exception:
        pass
    await menu(c.message, lang, rp)
    await c.answer()


@router.callback_query(F.data == "m:lang")
async def cb_m_lang(c: CallbackQuery):
    _, lang, _ = await user_of(c)
    await show(c, t(lang, "choose_lang"), lang_kb())


@router.callback_query(F.data == "m:home")
async def cb_home(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    await menu(c, lang, rp)


@router.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()


@router.message(Command("help"))
async def cmd_help(m: Message):
    _, lang, _ = await user_of(m)
    await m.answer(t(lang, "cmd_help", cmds="\n".join(f"/{c} — {esc(d)}" for c, d in COMMANDS)))


@router.message(Command("cancel"))
async def cmd_cancel(m: Message):
    _, lang, _ = await user_of(m)
    await Ctx.db.set_user_state(m.from_user.id, "")
    await m.answer(t(lang, "cancelled"))


# ---------------------------------------------------------------- status / about
async def act_status(obj):
    _, lang, rp = await user_of(obj)
    if rp[0] == "none":
        return await deny(obj, lang)
    kb = back_kb(lang)
    kb.inline_keyboard.insert(0, [IB(text=t(lang, "btn_refresh"), callback_data="m:status")])
    await show(obj, await status_text(lang), kb)


async def act_about(obj):
    _, lang, _ = await user_of(obj)
    d = Ctx.db
    srcs = await d.sources()
    text = t(lang, "about", push=d.setting("state_push_interval"), interval=d.setting("interval_minutes"), sources=len(srcs),
             tcpc=d.setting("tcp_concurrency"), tcpt=d.setting("tcp_timeout"), maxspeed=d.setting("max_speedtest"),
             dl=f"{int(d.setting('speed_download_bytes')) // 1_000_000}MB", ul=f"{int(d.setting('speed_upload_bytes')) // 1_000_000}MB")
    await show(obj, text, back_kb(lang))


router.message(Command("status"))(act_status)
router.message(Command("about"))(act_about)
router.callback_query(F.data == "m:status")(act_status)
router.callback_query(F.data == "m:about")(act_about)


# ---------------------------------------------------------------- list / best / get
async def render_list(lang: str, order: str, page: int) -> tuple[str, int]:
    per = int(Ctx.db.setting("top_list_size", 20))
    rows = await Ctx.db.top_configs(per * 10, order=order)
    pages = max(1, (len(rows) + per - 1) // per)
    page = min(page, pages - 1)
    chunk = rows[page * per:(page + 1) * per]
    if not rows:
        return t(lang, "list_empty"), 1
    lines = [t(lang, "list_title", order=t(lang, f"sort_{order}"), page=page + 1, pages=pages)]
    for i, r in enumerate(chunk, page * per + 1):
        lines.append(t(lang, "cfg_line", i=i, proto=r["protocol"], flag=flag(r["country"]), host=esc(r["host"][:28]), port=r["port"],
                       ping=fmt_ms(r["http_ms"] or r["tcp_ms"]), dl=fmt_kbps(r["dl_kbps"]), ul=fmt_kbps(r["ul_kbps"]), score=r["score"]))
    return "\n".join(lines), pages


async def act_list(obj, order="score", page=0):
    _, lang, rp = await user_of(obj)
    if rp[0] == "none":
        return await deny(obj, lang)
    text, pages = await render_list(lang, order, page)
    await show(obj, text, list_kb(lang, order, page, pages, rp))


@router.callback_query(F.data.startswith("list:"))
async def cb_list(c: CallbackQuery):
    _, order, page = c.data.split(":")
    await act_list(c, order, int(page))


@router.callback_query(F.data == "m:list")
async def cb_m_list(c: CallbackQuery):
    await act_list(c)


@router.message(Command("best"))
async def cmd_best(m: Message):
    await act_list(m, "score", 0)


@router.message(Command("list"))
async def cmd_list(m: Message):
    parts = m.text.split()
    order = parts[1] if len(parts) > 1 and parts[1] in ("score", "ping", "dl", "ul") else "score"
    await act_list(m, order, 0)


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick(c: CallbackQuery):
    _, lang, _ = await user_of(c)
    order = c.data.split(":")[1]
    st = await Ctx.db.config_stats()
    await Ctx.db.set_user_state(c.from_user.id, "pick_count", {"order": order})
    await c.message.answer(t(lang, "pick_count", max=max(1, min(st["alive"], 200))))
    await c.answer()


@router.callback_query(F.data.startswith("send:"))
async def cb_send(c: CallbackQuery):
    parts = c.data.split(":")
    how, order, n = parts[1], parts[2], int(parts[3])
    cc = parts[4] if len(parts) > 4 and parts[4] else None
    await do_send(c, how, order, n, cc)


async def do_send(obj, how: str, order: str, n: int, country: str | None = None):
    _, lang, rp = await user_of(obj)
    if rp[0] == "none":
        return await deny(obj, lang)
    rows = await Ctx.db.top_configs(n, country=country, order=order)
    msg = obj.message if is_cb(obj) else obj
    if not rows:
        return await show(obj, t(lang, "list_empty"), back_kb(lang), edit=False)
    links = [r["link"] for r in rows]
    if how == "file":
        content = "\n".join(links)
        await msg.answer_document(BufferedInputFile(content.encode(), filename=f"configs_{order}_{len(links)}.txt"),
                                  caption=f"{len(links)} configs · {order}")
        await msg.answer_document(BufferedInputFile(base64.b64encode(content.encode()), filename=f"sub_{order}_{len(links)}.txt"),
                                  caption="base64 subscription")
    elif how == "all":
        buf = ""
        for l in links:
            piece = f"<code>{esc(l)}</code>\n\n"
            if len(buf) + len(piece) > 3900:
                await msg.answer(buf, disable_web_page_preview=True)
                buf = ""
            buf += piece
        if buf:
            await msg.answer(buf, disable_web_page_preview=True)
    else:
        for r in rows:
            await msg.answer(f"{flag(r['country'])} <b>{r['protocol']}</b> {esc(r['host'])}:{r['port']} · {fmt_ms(r['http_ms'] or r['tcp_ms'])} · ⬇️{fmt_kbps(r['dl_kbps'])}\n<code>{esc(r['link'])}</code>",
                             disable_web_page_preview=True)
            await asyncio.sleep(0.05)
    await msg.answer(t(lang, "sent_done", n=len(links)))
    if is_cb(obj):
        await obj.answer()


@router.message(Command("get"))
async def cmd_get(m: Message):
    _, lang, rp = await user_of(m)
    if rp[0] == "none":
        return await deny(m, lang)
    parts = m.text.split()
    n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
    order = parts[2] if len(parts) > 2 and parts[2] in ("score", "ping", "dl", "ul") else "score"
    cc = parts[3].upper() if len(parts) > 3 else ""
    kb = send_how_kb(lang, order, min(n, 200))
    if cc:
        for row in kb.inline_keyboard:
            for b in row:
                if b.callback_data.startswith("send:"):
                    b.callback_data += f":{cc}"
    await m.answer(t(lang, "pick_how", n=n), reply_markup=kb)


# ---------------------------------------------------------------- history
async def act_history(obj, page=0):
    _, lang, rp = await user_of(obj)
    if rp[0] == "none":
        return await deny(obj, lang)
    days = await Ctx.db.history_days(60)
    lines = [t(lang, "history_title")]
    for r in days[page * 10:(page + 1) * 10]:
        lines.append(t(lang, "history_line", d=r["d"], tests=r["tests"], ok=r["ok"] or 0, alive=r["alive"] or 0, ms=int(r["best_ms"] or 0)))
    await show(obj, "\n".join(lines) if days else t(lang, "list_empty"), history_kb(lang, [r["d"] for r in days], page))


@router.callback_query(F.data.startswith("hist:"))
async def cb_hist(c: CallbackQuery):
    await act_history(c, int(c.data.split(":")[1]))


@router.callback_query(F.data.startswith("histd:"))
async def cb_histd(c: CallbackQuery):
    _, lang, _ = await user_of(c)
    d = c.data.split(":")[1]
    rows = await Ctx.db.history_day(d, 20)
    lines = [t(lang, "history_day_title", d=d)]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {flag(r['country'])} <code>{r['protocol']}</code> {fmt_ms(r['tcp_ms'])} ⬇️{fmt_kbps(r['dl_kbps'])} ⬆️{fmt_kbps(r['ul_kbps'])}\n<code>{esc(r['link'][:160])}</code>")
    await show(c, "\n".join(lines) or t(lang, "list_empty"), back_kb(lang, "hist:0"))


router.message(Command("history"))(act_history)


# ---------------------------------------------------------------- scan / logs
async def act_scan(obj):
    _, lang, rp = await user_of(obj)
    if not can(rp, "pipeline"):
        return await deny(obj, lang)
    if Ctx.pipeline.trigger():
        await show(obj, t(lang, "scan_started", run=(Ctx.pipeline.run_id or 0) + 1), back_kb(lang), edit=False)
    else:
        await show(obj, t(lang, "scan_running", stage=Ctx.pipeline.stage), back_kb(lang), edit=False)


async def act_logs(obj):
    _, lang, rp = await user_of(obj)
    if not can(rp, "logs"):
        return await deny(obj, lang)
    rows = await Ctx.db.recent_logs(25)
    body = "\n".join(f"<code>{time.strftime('%H:%M:%S', time.localtime(r['ts']))}</code> [{r['stage']}] {esc(r['msg'][:150])}" for r in rows) or t(lang, "log_empty")
    kb = back_kb(lang)
    kb.inline_keyboard.insert(0, [IB(text=t(lang, "btn_refresh"), callback_data="m:logs"), IB(text="📡 Live 60s", callback_data="m:logslive")])
    await show(obj, t(lang, "logs_title", stage=Ctx.pipeline.stage) + body, kb)


@router.callback_query(F.data == "m:logslive")
async def cb_logs_live(c: CallbackQuery):
    """Stream log lines into one message for 60 seconds (edited in place)."""
    _, lang, rp = await user_of(c)
    if not can(rp, "logs"):
        return await deny(c, lang)
    msg = await c.message.answer("📡 live…")
    await c.answer()
    buf: list[str] = []
    ev = asyncio.Event()

    async def cb(level, stage, text):
        buf.append(f"[{stage}] {esc(text[:140])}")
        ev.set()

    Ctx.pipeline.listeners.append(cb)
    t0 = time.time()
    last = ""
    try:
        while time.time() - t0 < 60:
            try:
                await asyncio.wait_for(ev.wait(), 3)
            except asyncio.TimeoutError:
                pass
            ev.clear()
            txt = ("📡 <b>live</b> (" + Ctx.pipeline.stage + ")\n" + "\n".join(buf[-25:]))[:4000]
            if buf and txt != last:
                last = txt
                try:
                    await msg.edit_text(txt)
                except Exception:
                    pass
            await asyncio.sleep(1.2)
    finally:
        if cb in Ctx.pipeline.listeners:
            Ctx.pipeline.listeners.remove(cb)
    try:
        await msg.edit_text((last or "📡") + "\n⏹ live ended", reply_markup=back_kb(lang))
    except Exception:
        pass


router.message(Command("scan"))(act_scan)
router.message(Command("logs"))(act_logs)
router.callback_query(F.data == "m:scan")(act_scan)
router.callback_query(F.data == "m:logs")(act_logs)


# ---------------------------------------------------------------- settings
async def act_settings(obj, group=0):
    _, lang, rp = await user_of(obj)
    if not can(rp, "settings"):
        return await deny(obj, lang)
    await show(obj, t(lang, "settings_title"), settings_kb(lang, Ctx.db, group))


@router.callback_query(F.data.startswith("set:"))
async def cb_set(c: CallbackQuery):
    await act_settings(c, int(c.data.split(":")[1]))


@router.callback_query(F.data.startswith("tog:"))
async def cb_tog(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "settings"):
        return await deny(c, lang)
    _, key, group = c.data.split(":")
    if key == "public_mode" and rp[0] != "owner":
        return await deny(c, lang)
    await apply_setting(key, not bool(Ctx.db.setting(key)))
    await act_settings(c, int(group))


@router.callback_query(F.data.startswith("edit:"))
async def cb_edit(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "settings"):
        return await deny(c, lang)
    _, key, group = c.data.split(":")
    await Ctx.db.set_user_state(c.from_user.id, "set_value", {"key": key, "group": int(group)})
    await c.message.answer(t(lang, "set_prompt", key=key, val=esc(Ctx.db.setting(key))))
    await c.answer()


@router.message(Command("set"))
async def cmd_set(m: Message):
    _, lang, rp = await user_of(m)
    if not can(rp, "settings"):
        return await deny(m, lang)
    parts = m.text.split(maxsplit=2)
    if len(parts) < 3 or parts[1] not in DEFAULT_SETTINGS:
        return await m.answer("Usage: /set KEY VALUE\n" + ", ".join(k for k in DEFAULT_SETTINGS if k != "ai_api_key"))
    try:
        v = coerce_setting(parts[1], parts[2])
    except ValueError:
        return await m.answer(t(lang, "set_bad"))
    await apply_setting(parts[1], v)
    await m.answer(t(lang, "set_ok", key=parts[1], val=esc(v)))


router.message(Command("settings"))(act_settings)


@router.message(Command("public"))
async def cmd_public(m: Message):
    _, lang, rp = await user_of(m)
    if rp[0] != "owner":
        return await deny(m, lang)
    v = not bool(Ctx.db.setting("public_mode"))
    await Ctx.db.set_setting("public_mode", v)
    await m.answer(t(lang, "public_on" if v else "public_off"))
