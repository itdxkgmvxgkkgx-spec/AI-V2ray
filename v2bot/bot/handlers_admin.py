"""AI (kill_pv2) UI, approvals, admins, sources, subscriptions, and the free-text router."""
from __future__ import annotations

import base64
import json
import re
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton as IB, InlineKeyboardMarkup as IM, Message

from ..config import DEFAULT_SETTINGS, ENV, PERMISSIONS, SUBS_DIR
from ..i18n import t
from ..ai.llm import LLM, LLMError, encrypt
from .common import Ctx, apply_setting, coerce_setting, deny, is_cb, menu, show, user_of
from .handlers_core import act_about, act_history, act_list, act_logs, act_scan, act_settings, act_status, do_send
from .ui import ai_menu_kb, approval_kb, back_kb, can, esc, models_kb, send_how_kb

router = Router()
_MODELS_CACHE: dict[int, list[str]] = {}


# ================================================================= AI
async def ai_menu(obj):
    _, lang, rp = await user_of(obj)
    if not can(rp, "ai"):
        return await deny(obj, lang)
    ag = Ctx.agent
    if not ag.configured():
        return await ai_setup_start(obj)
    sess = await ag.session(obj.message.chat.id if is_cb(obj) else obj.chat.id, obj.from_user.id)
    n = await Ctx.db.fetchone("SELECT COUNT(*) c FROM ai_messages WHERE session_id=?", (sess["id"],))
    text = t(lang, "ai_menu", model=esc(Ctx.db.setting("ai_model")), sid=sess["id"], msgs=n["c"], mem=ag.memory.pct("memory"),
             user=ag.memory.pct("user"), skills=len(ag.skills.list()))
    await show(obj, text, ai_menu_kb(lang))


async def ai_setup_start(obj):
    _, lang, rp = await user_of(obj)
    if not can(rp, "ai"):
        return await deny(obj, lang)
    await Ctx.db.set_user_state(obj.from_user.id, "ai_url")
    await show(obj, t(lang, "ai_setup_url"), back_kb(lang), edit=False)


@router.callback_query(F.data == "ai:menu")
async def cb_ai_menu(c: CallbackQuery):
    await ai_menu(c)


@router.callback_query(F.data == "ai:setup")
async def cb_ai_setup(c: CallbackQuery):
    await ai_setup_start(c)


@router.callback_query(F.data == "ai:chat")
async def cb_ai_chat(c: CallbackQuery):
    _, lang, _ = await user_of(c)
    await Ctx.db.set_user_state(c.from_user.id, "ai_chat")
    await show(c, "💬 " + t(lang, "ai_ready", model=esc(Ctx.db.setting("ai_model"))), back_kb(lang, "ai:menu"), edit=False)


@router.callback_query(F.data == "ai:new")
async def cb_ai_new(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "ai"):
        return await deny(c, lang)
    await Ctx.agent.session(c.message.chat.id, c.from_user.id, new=True)
    await show(c, t(lang, "ai_new_session"), back_kb(lang, "ai:menu"), edit=False)


@router.message(Command("ai_new"))
async def cmd_ai_new(m: Message):
    _, lang, rp = await user_of(m)
    if not can(rp, "ai"):
        return await deny(m, lang)
    await Ctx.agent.session(m.chat.id, m.from_user.id, new=True)
    await m.answer(t(lang, "ai_new_session"))


async def _list_models(obj, lang, page=0):
    uid = obj.from_user.id
    if uid not in _MODELS_CACHE:
        from ..ai.llm import decrypt
        llm = LLM(Ctx.db.setting("ai_base_url"), decrypt(Ctx.db.setting("ai_api_key", "")), "")
        try:
            _MODELS_CACHE[uid] = await llm.list_models()
        except Exception as e:
            await Ctx.db.set_user_state(uid, "ai_model_manual")
            return await show(obj, t(lang, "ai_models_fail", err=esc(str(e)[:200])), None, edit=False)
    models = _MODELS_CACHE[uid]
    if not models:
        await Ctx.db.set_user_state(uid, "ai_model_manual")
        return await show(obj, t(lang, "ai_models_fail", err="empty list"), None, edit=False)
    await show(obj, t(lang, "ai_pick_model", n=len(models)), models_kb(models, page), edit=is_cb(obj))


@router.callback_query(F.data == "ai:model")
async def cb_ai_model(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "ai"):
        return await deny(c, lang)
    _MODELS_CACHE.pop(c.from_user.id, None)
    await _list_models(c, lang)


@router.callback_query(F.data.startswith("aimp:"))
async def cb_aimp(c: CallbackQuery):
    _, lang, _ = await user_of(c)
    await _list_models(c, lang, int(c.data.split(":")[1]))


@router.callback_query(F.data.startswith("aim:"))
async def cb_aim(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "ai"):
        return await deny(c, lang)
    idx = int(c.data.split(":")[1])
    models = _MODELS_CACHE.get(c.from_user.id, [])
    if idx >= len(models):
        return await c.answer("expired", show_alert=True)
    await apply_setting("ai_model", models[idx])
    await Ctx.db.set_user_state(c.from_user.id, "ai_chat")
    await show(c, t(lang, "ai_ready", model=esc(models[idx])), ai_menu_kb(lang))


@router.callback_query(F.data == "ai:memory")
async def cb_ai_memory(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "ai"):
        return await deny(c, lang)
    await show(c, f"<pre>{esc(Ctx.agent.memory.render())[:3800]}</pre>", back_kb(lang, "ai:menu"))


@router.message(Command("ai_memory"))
async def cmd_ai_memory(m: Message):
    _, lang, rp = await user_of(m)
    if not can(rp, "ai"):
        return await deny(m, lang)
    await m.answer(f"<pre>{esc(Ctx.agent.memory.render())[:3800]}</pre>")


@router.callback_query(F.data == "ai:skills")
async def cb_ai_skills(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "ai"):
        return await deny(c, lang)
    await show(c, "🧩 <b>Skills</b>\n" + esc(Ctx.agent.skills.index()), back_kb(lang, "ai:menu"))


@router.callback_query(F.data == "ai:discover")
async def cb_ai_discover(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "ai"):
        return await deny(c, lang)
    if not ENV.tavily_key:
        return await c.answer("TAVILY_API_KEY missing", show_alert=True)
    await c.answer("🔎 running…")
    await Ctx.db.kv_set("last_discovery", 0)

    async def notify(txt):
        await c.message.answer(txt, disable_web_page_preview=True)

    await Ctx.agent.discovery_job(notify)
    await c.message.answer("🔎 discovery finished.", reply_markup=back_kb(lang, "ai:menu"))


async def ai_pending(obj):
    _, lang, rp = await user_of(obj)
    if not can(rp, "ai"):
        return await deny(obj, lang)
    chat_id = (obj.message.chat.id if is_cb(obj) else obj.chat.id) if hasattr(obj.message if is_cb(obj) else obj, "chat") else obj.from_user.id
    rows = await Ctx.agent.pending(chat_id)
    if not rows:
        return await show(obj, "✅ no pending approvals", back_kb(lang, "ai:menu"))
    for r in rows:
        await (obj.message if is_cb(obj) else obj).answer(
            t(lang, "ai_need_approval", tool=r["tool"], reason=esc(r["reason"]), args=esc(r["args"][:1500])), reply_markup=approval_kb(lang, r["id"]))
    if is_cb(obj):
        await obj.answer()


router.callback_query(F.data == "ai:pending")(ai_pending)
router.message(Command("ai_pending"))(ai_pending)
router.message(Command("ai"))(ai_menu)
router.message(Command("ai_setup"))(ai_setup_start)


@router.callback_query(F.data.startswith("ap:"))
async def cb_approval(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "ai"):
        return await deny(c, lang)
    _, yn, pid = c.data.split(":")
    approved = yn == "y"
    try:
        await c.message.edit_reply_markup(reply_markup=None)
        await c.message.answer(t(lang, "ai_approved" if approved else "ai_denied"))
    except Exception:
        pass
    await c.answer()
    reply = await Ctx.agent.resume(pid, approved, c.from_user.first_name or "", lang)
    if reply:
        await send_ai_reply(c.message.chat.id, reply)


async def send_ai_reply(chat_id: int, text: str):
    text = text.strip()
    if not text:
        return
    # chunk at 3900 on paragraph boundaries
    while text:
        if len(text) <= 3900:
            chunk, text = text, ""
        else:
            cut = text.rfind("\n", 0, 3900)
            cut = cut if cut > 1000 else 3900
            chunk, text = text[:cut], text[cut:]
        try:
            await Ctx.bot.send_message(chat_id, chunk, disable_web_page_preview=True)
        except Exception:
            await Ctx.bot.send_message(chat_id, esc(chunk), parse_mode=None, disable_web_page_preview=True)


async def ai_message(m: Message, lang: str):
    """Free-text to the agent (status line is edited as tools run)."""
    status = await m.answer(t(lang, "ai_thinking"))
    last = {"txt": ""}

    async def on_status(chat_id, line):
        if line.startswith("🔧"):
            try:
                if line != last["txt"]:
                    last["txt"] = line
                    await status.edit_text(f"{t(lang, 'ai_thinking')} {line}")
            except Exception:
                pass
        else:
            await Ctx.bot.send_message(chat_id, line)

    Ctx.agent.on_status = on_status
    reply = await Ctx.agent.run_turn(m.chat.id, m.from_user.id, m.from_user.first_name or "", lang, m.text)
    try:
        await status.delete()
    except Exception:
        pass
    if reply == "__not_configured__":
        return await m.answer(t(lang, "ai_not_configured"))
    if reply:
        await send_ai_reply(m.chat.id, reply)


async def on_approval(chat_id: int, p: dict):
    lang = await Ctx.db.user_lang(ENV.admin_id)
    await Ctx.bot.send_message(chat_id, t(lang, "ai_need_approval", tool=p["tool"], reason=esc(p["reason"]),
                                         args=esc(json.dumps(p["args"], ensure_ascii=False, indent=1)[:1500])),
                               reply_markup=approval_kb(lang, p["id"]))


async def send_file_cb(chat_id: int, filename: str, content: str):
    await Ctx.bot.send_document(chat_id, BufferedInputFile(content.encode(), filename=filename))


# ================================================================= admins
async def act_admins(obj):
    _, lang, rp = await user_of(obj)
    if not can(rp, "admins"):
        return await deny(obj, lang)
    rows = await Ctx.db.admins()
    lst = f"👑 <code>{ENV.admin_id}</code> owner\n" + "\n".join(
        f"• <code>{r['id']}</code> {', '.join(json.loads(r['permissions']))} {esc(r['note'])}" for r in rows) or "—"
    kb = IM(inline_keyboard=[[IB(text=f"🗑 {r['id']}", callback_data=f"admdel:{r['id']}")] for r in rows[:20]] +
            [[IB(text=t(lang, "btn_public", v="ON" if Ctx.db.setting("public_mode") else "OFF"), callback_data="admpub")],
             [IB(text=t(lang, "btn_home"), callback_data="m:home")]])
    await show(obj, t(lang, "admins_title", list=lst, perms=", ".join(PERMISSIONS)), kb)


@router.callback_query(F.data.startswith("admdel:"))
async def cb_admdel(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "admins"):
        return await deny(c, lang)
    uid = int(c.data.split(":")[1])
    await Ctx.db.remove_admin(uid)
    await c.answer(t(lang, "admin_removed", id=uid))
    await act_admins(c)


@router.callback_query(F.data == "admpub")
async def cb_admpub(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if rp[0] != "owner":
        return await deny(c, lang)
    v = not bool(Ctx.db.setting("public_mode"))
    await Ctx.db.set_setting("public_mode", v)
    await c.answer(t(lang, "public_on" if v else "public_off"), show_alert=True)
    await act_admins(c)


@router.message(Command("admin_add"))
async def cmd_admin_add(m: Message):
    _, lang, rp = await user_of(m)
    if not can(rp, "admins"):
        return await deny(m, lang)
    parts = m.text.split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        return await m.answer("Usage: /admin_add ID perm1,perm2 | all\nPerms: " + ", ".join(PERMISSIONS))
    uid = int(parts[1])
    perms = PERMISSIONS if len(parts) < 3 or parts[2] == "all" else [p for p in parts[2].split(",") if p in PERMISSIONS]
    if rp[0] != "owner":
        perms = [p for p in perms if p != "admins"]  # admins cannot grant admin-management
    await Ctx.db.add_admin(uid, m.from_user.id, perms)
    await m.answer(t(lang, "admin_added", id=uid, perms=", ".join(perms)))


@router.message(Command("admin_del"))
async def cmd_admin_del(m: Message):
    _, lang, rp = await user_of(m)
    if not can(rp, "admins"):
        return await deny(m, lang)
    parts = m.text.split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        return await m.answer("Usage: /admin_del ID")
    await Ctx.db.remove_admin(int(parts[1]))
    await m.answer(t(lang, "admin_removed", id=parts[1]))


router.message(Command("admins"))(act_admins)
router.callback_query(F.data == "m:admins")(act_admins)


# ================================================================= sources
async def act_sources(obj):
    _, lang, rp = await user_of(obj)
    if not can(rp, "sources"):
        return await deny(obj, lang)
    rows = await Ctx.db.sources(enabled_only=False)
    ok = sum(1 for r in rows if (r["ok_count"] or 0) >= (r["fail_count"] or 0))
    top = sorted(rows, key=lambda r: -(r["last_count"] or 0))[:15]
    lst = "\n".join(f"• {r['last_count'] or 0} · <code>{esc(r['url'][:60])}</code>" for r in top)
    await show(obj, t(lang, "sources_title", n=len(rows), ok=ok, fail=len(rows) - ok, list=lst), back_kb(lang))


@router.message(Command("source_add"))
async def cmd_source_add(m: Message):
    _, lang, rp = await user_of(m)
    if not can(rp, "sources"):
        return await deny(m, lang)
    parts = m.text.split()
    if len(parts) < 2 or not parts[1].startswith("http"):
        return await m.answer("Usage: /source_add URL [sub|raw|html|tg]")
    url = parts[1]
    kind = parts[2] if len(parts) > 2 else "auto"
    if "t.me/" in url and "/s/" not in url:
        url = url.replace("t.me/", "t.me/s/")
        kind = "tg"
    ok = await Ctx.db.add_source(url, kind, added_by=f"tg:{m.from_user.id}")
    await m.answer(t(lang, "source_added" if ok else "source_exists"))


router.message(Command("sources"))(act_sources)
router.callback_query(F.data == "m:sources")(act_sources)


# ================================================================= subscriptions
async def act_subs(obj):
    _, lang, rp = await user_of(obj)
    if rp[0] == "none":
        return await deny(obj, lang)
    rows = await Ctx.db.subs()
    lst = "\n".join(f"• <b>{esc(r['name'])}</b> — {r['count']} configs · {time.strftime('%m-%d %H:%M', time.localtime(r['updated_at']))}" for r in rows) or "—"
    kb = IM(inline_keyboard=[[IB(text=f"📥 {r['name']}", callback_data=f"subget:{r['name']}"),
                              IB(text="🔄", callback_data=f"subref:{r['name']}")] for r in rows[:15]] +
            [[IB(text=t(lang, "btn_home"), callback_data="m:home")]])
    await Ctx.db.set_user_state(obj.from_user.id, "sub_request")
    await show(obj, t(lang, "sub_title", list=lst), kb)


async def build_sub(name: str, by: int, count: int, country: str = "", protocol: str = "", order: str = "score", max_ping: int = 0) -> int:
    countries = [c.strip().upper() for c in country.split(",") if c.strip()] or [None]
    per = max(1, count // len(countries))
    picked = []
    for cc in countries:
        rows = await Ctx.db.top_configs(per * 4, cc, protocol or None, "alive", order)
        if max_ping:
            rows = [r for r in rows if (r["http_ms"] or r["tcp_ms"] or 9e9) <= max_ping]
        picked.extend(rows[:per])
    picked = picked[:count]
    await Ctx.db.save_sub(name, by, {"count": count, "country": country, "protocol": protocol, "order": order, "max_ping": max_ping},
                          [r["hash"] for r in picked])
    (SUBS_DIR / f"{name}.txt").write_text(base64.b64encode("\n".join(r["link"] for r in picked).encode()).decode())
    return len(picked)


async def send_sub(msg: Message, name: str, lang: str):
    row = await Ctx.db.sub(name)
    if not row:
        return await msg.answer("❌ no such subscription")
    links = await Ctx.db.links_for_hashes(json.loads(row["hashes"]))
    plain = "\n".join(links)
    await msg.answer_document(BufferedInputFile(base64.b64encode(plain.encode()), filename=f"{name}_sub.txt"),
                              caption=t(lang, "sub_file_caption", name=name, n=len(links)))
    await msg.answer_document(BufferedInputFile(plain.encode(), filename=f"{name}_links.txt"), caption=f"{name} — plain links")


@router.callback_query(F.data.startswith("subget:"))
async def cb_subget(c: CallbackQuery):
    _, lang, _ = await user_of(c)
    await send_sub(c.message, c.data.split(":", 1)[1], lang)
    await c.answer()


@router.callback_query(F.data.startswith("subref:"))
async def cb_subref(c: CallbackQuery):
    _, lang, rp = await user_of(c)
    if not can(rp, "subs") and rp[0] != "user":
        return await deny(c, lang)
    name = c.data.split(":", 1)[1]
    row = await Ctx.db.sub(name)
    if row:
        f = json.loads(row["filter_json"])
        n = await build_sub(name, c.from_user.id, **{k: f.get(k, d) for k, d in (("count", 10), ("country", ""), ("protocol", ""), ("order", "score"), ("max_ping", 0))})
        await c.answer(f"🔄 {n} configs", show_alert=True)
        await act_subs(c)


@router.message(Command("sub"))
async def cmd_sub(m: Message):
    _, lang, rp = await user_of(m)
    if rp[0] == "none":
        return await deny(m, lang)
    parts = m.text.split()
    if len(parts) < 2:
        return await act_subs(m)
    await send_sub(m, parts[1], lang)


@router.message(Command("sub_create"))
async def cmd_sub_create(m: Message):
    _, lang, rp = await user_of(m)
    if rp[0] == "none":
        return await deny(m, lang)
    parts = m.text.split()
    if len(parts) < 3 or not parts[2].isdigit():
        return await m.answer("Usage: /sub_create NAME COUNT [CC[,CC]] [protocol] [score|ping|dl|ul]")
    name = re.sub(r"[^a-zA-Z0-9_-]+", "-", parts[1])[:32]
    cc = parts[3] if len(parts) > 3 else ""
    proto = parts[4] if len(parts) > 4 else ""
    order = parts[5] if len(parts) > 5 else "score"
    n = await build_sub(name, m.from_user.id, int(parts[2]), cc, proto, order)
    await m.answer(t(lang, "sub_created", name=name, n=n))
    await send_sub(m, name, lang)


router.message(Command("subs"))(act_subs)
router.callback_query(F.data == "m:subs")(act_subs)


# ================================================================= natural-language sub request (no LLM needed)
_CC_WORDS = {"us": "US", "usa": "US", "america": "US", "آمریکا": "US", "امریکا": "US", "de": "DE", "germany": "DE", "آلمان": "DE",
             "nl": "NL", "netherlands": "NL", "هلند": "NL", "fr": "FR", "france": "FR", "فرانسه": "FR", "uk": "GB", "gb": "GB", "england": "GB", "انگلیس": "GB",
             "tr": "TR", "turkey": "TR", "ترکیه": "TR", "fi": "FI", "finland": "FI", "فنلاند": "FI", "se": "SE", "sweden": "SE", "سوئد": "SE",
             "ae": "AE", "uae": "AE", "امارات": "AE", "sg": "SG", "singapore": "SG", "سنگاپور": "SG", "jp": "JP", "japan": "JP", "ژاپن": "JP",
             "ca": "CA", "canada": "CA", "کانادا": "CA", "ru": "RU", "russia": "RU", "روسیه": "RU", "pl": "PL", "poland": "PL", "لهستان": "PL"}
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def parse_sub_request(text: str) -> dict | None:
    t_ = text.translate(_FA_DIGITS).lower()
    if not any(w in t_ for w in ("config", "کانفیگ", "sub", "ساب", "best", "بهترین")):
        return None
    nums = [int(x) for x in re.findall(r"\b(\d{1,3})\b", t_)]
    count = next((n for n in nums if n <= 200), 5)
    ccs = sorted({cc for w, cc in _CC_WORDS.items() if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t_)})
    mp = re.search(r"(?:ping|پینگ)\D{0,12}(\d{2,4})", t_)
    max_ping = int(mp.group(1)) if mp else 0
    proto = next((p for p in ("vless", "vmess", "trojan", "ss", "hysteria2", "tuic") if p in t_), "")
    order = "ping" if ("ping" in t_ or "پینگ" in t_) and not mp else "dl" if ("speed" in t_ or "سرعت" in t_ or "download" in t_) else "score"
    return {"count": count, "country": ",".join(ccs), "protocol": proto, "order": order, "max_ping": max_ping}


# ================================================================= free-text router (reply keyboard + states + AI)
@router.message(F.text & ~F.text.startswith("/"))
async def on_text(m: Message):
    row, lang, rp = await user_of(m)
    if rp[0] == "none":
        return await m.answer(t(lang, "admin_only"))
    txt = m.text.strip()
    # reply-keyboard buttons (any language)
    btn = {t(lang, k): k for k in ("btn_status", "btn_best", "btn_list", "btn_history", "btn_sub", "btn_about", "btn_logs", "btn_scan",
                                   "btn_settings", "btn_ai", "btn_lang", "btn_home", "btn_sources", "btn_admins")}.get(txt)
    if btn:
        await Ctx.db.set_user_state(m.from_user.id, "")
        return await {
            "btn_status": act_status, "btn_best": lambda o: act_list(o, "score", 0), "btn_list": lambda o: act_list(o, "ping", 0),
            "btn_history": act_history, "btn_sub": act_subs, "btn_about": act_about, "btn_logs": act_logs, "btn_scan": act_scan,
            "btn_settings": act_settings, "btn_ai": ai_menu, "btn_sources": act_sources, "btn_admins": act_admins,
            "btn_lang": lambda o: o.answer(t(lang, "choose_lang"), reply_markup=__import__("v2bot.bot.ui", fromlist=["lang_kb"]).lang_kb()),
            "btn_home": lambda o: menu(o, lang, rp),
        }[btn](m)

    state, data = await Ctx.db.get_user_state(m.from_user.id)

    if state == "pick_count":
        n = txt.translate(_FA_DIGITS)
        if not n.isdigit() or not 1 <= int(n) <= 200:
            return await m.answer(t(lang, "bad_number"))
        await Ctx.db.set_user_state(m.from_user.id, "")
        return await m.answer(t(lang, "pick_how", n=n), reply_markup=send_how_kb(lang, data.get("order", "score"), int(n)))

    if state == "set_value":
        key = data["key"]
        if not can(rp, "settings"):
            return await deny(m, lang)
        try:
            v = coerce_setting(key, txt)
        except ValueError:
            return await m.answer(t(lang, "set_bad"))
        await apply_setting(key, v)
        await Ctx.db.set_user_state(m.from_user.id, "")
        await m.answer(t(lang, "set_ok", key=key, val=esc(v)))
        return await act_settings(m, data.get("group", 0))

    if state == "ai_url":
        if not can(rp, "ai"):
            return await deny(m, lang)
        url = txt.rstrip("/")
        if not url.startswith("http"):
            return await m.answer("❌ URL must start with http(s)://")
        await Ctx.db.set_setting("ai_base_url", url)
        await Ctx.db.set_user_state(m.from_user.id, "ai_key")
        return await m.answer(t(lang, "ai_setup_key"))

    if state == "ai_key":
        if not can(rp, "ai"):
            return await deny(m, lang)
        await Ctx.db.set_setting("ai_api_key", encrypt(txt))
        try:
            await m.delete()
        except Exception:
            pass
        await Ctx.db.set_user_state(m.from_user.id, "")
        await m.answer(t(lang, "ai_setup_models"))
        _MODELS_CACHE.pop(m.from_user.id, None)
        return await _list_models(m, lang)

    if state == "ai_model_manual":
        await apply_setting("ai_model", txt)
        await Ctx.db.set_user_state(m.from_user.id, "ai_chat")
        return await m.answer(t(lang, "ai_ready", model=esc(txt)), reply_markup=ai_menu_kb(lang))

    if state == "sub_request":
        req = parse_sub_request(txt)
        if req:
            name = f"sub{int(time.time()) % 100000}"
            n = await build_sub(name, m.from_user.id, **req)
            await m.answer(t(lang, "sub_created", name=name, n=n) + f"\n<i>{esc(json.dumps(req, ensure_ascii=False))}</i>")
            return await send_sub(m, name, lang)
        await Ctx.db.set_user_state(m.from_user.id, "")

    # default: talk to kill_pv2 (admins with ai perm); users get a hint
    if can(rp, "ai"):
        if not Ctx.agent.configured():
            return await m.answer(t(lang, "ai_not_configured"))
        return await ai_message(m, lang)
    req = parse_sub_request(txt)
    if req:
        name = f"sub{int(time.time()) % 100000}"
        n = await build_sub(name, m.from_user.id, **req)
        await m.answer(t(lang, "sub_created", name=name, n=n))
        return await send_sub(m, name, lang)
    await m.answer(t(lang, "unknown"))
