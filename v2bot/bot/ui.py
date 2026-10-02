"""Keyboards (inline + reply), access control helpers, formatting helpers."""
from __future__ import annotations

import time

from aiogram.types import InlineKeyboardButton as IB, InlineKeyboardMarkup as IM, KeyboardButton as KB, ReplyKeyboardMarkup as RM

from ..config import ENV, PERMISSIONS
from ..i18n import LANGS, t

FLAGS = {c: chr(0x1F1E6 + ord(c[0]) - 65) + chr(0x1F1E6 + ord(c[1]) - 65) for c in
         ["US", "DE", "NL", "FR", "GB", "FI", "SE", "TR", "AE", "SG", "JP", "CA", "RU", "IR", "PL", "IT", "ES", "HK", "KR", "IN", "AM", "GE", "KZ", "UA", "RO", "LT", "LV", "EE", "CZ", "AT", "CH", "BG", "NO", "DK", "BE", "IE", "AU", "BR", "ZA", "CY"]}


def flag(cc: str) -> str:
    return FLAGS.get((cc or "").upper(), "🏳️" if not cc or cc == "??" else cc)


def fmt_dur(sec: float) -> str:
    sec = int(max(0, sec))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def fmt_kbps(k) -> str:
    if not k:
        return "—"
    return f"{k / 1000:.1f}M" if k >= 1000 else f"{int(k)}k"


def fmt_ms(ms) -> str:
    return f"{int(ms)}ms" if ms else "—"


def esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- access
async def role(db, uid: int) -> tuple[str, list[str]]:
    """returns (role, perms). role: owner | admin | user | none"""
    if uid == ENV.admin_id:
        return "owner", PERMISSIONS
    perms = await db.admin_perms(uid)
    if perms is not None:
        return "admin", perms
    if db.setting("public_mode", False):
        return "user", []
    return "none", []


def can(role_perms: tuple[str, list[str]], perm: str) -> bool:
    r, p = role_perms
    return r == "owner" or (r == "admin" and perm in p)


# ---------------------------------------------------------------- keyboards
def lang_kb() -> IM:
    rows, cur = [], []
    for code, name in LANGS.items():
        cur.append(IB(text=name, callback_data=f"lang:{code}"))
        if len(cur) == 2:
            rows.append(cur); cur = []
    if cur:
        rows.append(cur)
    return IM(inline_keyboard=rows)


def main_inline(lang: str, rp) -> IM:
    r, _ = rp
    rows = [
        [IB(text=t(lang, "btn_status"), callback_data="m:status"), IB(text=t(lang, "btn_best"), callback_data="list:score:0")],
        [IB(text=t(lang, "btn_list"), callback_data="m:list"), IB(text=t(lang, "btn_history"), callback_data="hist:0")],
        [IB(text=t(lang, "btn_sub"), callback_data="m:subs"), IB(text=t(lang, "btn_about"), callback_data="m:about")],
        [IB(text=t(lang, "btn_lang"), callback_data="m:lang")],
    ]
    if can(rp, "logs"):
        rows[3].insert(0, IB(text=t(lang, "btn_logs"), callback_data="m:logs"))
    if can(rp, "pipeline"):
        rows.append([IB(text=t(lang, "btn_scan"), callback_data="m:scan")])
    if can(rp, "settings") or can(rp, "ai") or can(rp, "sources") or can(rp, "admins"):
        row = []
        if can(rp, "settings"):
            row.append(IB(text=t(lang, "btn_settings"), callback_data="set:0"))
        if can(rp, "ai"):
            row.append(IB(text=t(lang, "btn_ai"), callback_data="ai:menu"))
        rows.append(row)
        row2 = []
        if can(rp, "sources"):
            row2.append(IB(text=t(lang, "btn_sources"), callback_data="m:sources"))
        if can(rp, "admins"):
            row2.append(IB(text=t(lang, "btn_admins"), callback_data="m:admins"))
        if row2:
            rows.append(row2)
    return IM(inline_keyboard=rows)


def main_reply(lang: str, rp) -> RM:
    rows = [[KB(text=t(lang, "btn_status")), KB(text=t(lang, "btn_best")), KB(text=t(lang, "btn_list"))],
            [KB(text=t(lang, "btn_history")), KB(text=t(lang, "btn_sub")), KB(text=t(lang, "btn_about"))]]
    r3 = []
    if can(rp, "logs"):
        r3.append(KB(text=t(lang, "btn_logs")))
    if can(rp, "pipeline"):
        r3.append(KB(text=t(lang, "btn_scan")))
    if can(rp, "settings"):
        r3.append(KB(text=t(lang, "btn_settings")))
    if can(rp, "ai"):
        r3.append(KB(text=t(lang, "btn_ai")))
    if r3:
        rows.append(r3)
    rows.append([KB(text=t(lang, "btn_lang")), KB(text=t(lang, "btn_home"))])
    return RM(keyboard=rows, resize_keyboard=True, is_persistent=True)


def back_kb(lang: str, to: str = "m:home") -> IM:
    return IM(inline_keyboard=[[IB(text=t(lang, "btn_back"), callback_data=to)]])


def list_kb(lang: str, order: str, page: int, pages: int, rp) -> IM:
    orders = [("score", "sort_score"), ("ping", "sort_ping"), ("dl", "sort_dl"), ("ul", "sort_ul")]
    row1 = [IB(text=("• " if o == order else "") + t(lang, k), callback_data=f"list:{o}:0") for o, k in orders]
    nav = []
    if page > 0:
        nav.append(IB(text=t(lang, "btn_prev"), callback_data=f"list:{order}:{page - 1}"))
    nav.append(IB(text=f"{page + 1}/{max(pages, 1)}", callback_data="noop"))
    if page + 1 < pages:
        nav.append(IB(text=t(lang, "btn_next"), callback_data=f"list:{order}:{page + 1}"))
    rows = [row1, nav, [IB(text="📤 " + t(lang, "btn_send_file").split(" ", 1)[1] if " " in t(lang, "btn_send_file") else "📤", callback_data=f"pick:{order}"),
                        IB(text=t(lang, "btn_refresh"), callback_data=f"list:{order}:{page}")],
            [IB(text=t(lang, "btn_home"), callback_data="m:home")]]
    return IM(inline_keyboard=rows)


def send_how_kb(lang: str, order: str, n: int) -> IM:
    return IM(inline_keyboard=[
        [IB(text=t(lang, "btn_send_file"), callback_data=f"send:file:{order}:{n}")],
        [IB(text=t(lang, "btn_send_all"), callback_data=f"send:all:{order}:{n}")],
        [IB(text=t(lang, "btn_send_one"), callback_data=f"send:one:{order}:{n}")],
        [IB(text=t(lang, "btn_cancel"), callback_data=f"list:{order}:0")]])


def approval_kb(lang: str, pid: str) -> IM:
    return IM(inline_keyboard=[[IB(text=t(lang, "btn_approve"), callback_data=f"ap:y:{pid}"), IB(text=t(lang, "btn_deny"), callback_data=f"ap:n:{pid}")]])


def ai_menu_kb(lang: str) -> IM:
    return IM(inline_keyboard=[
        [IB(text=t(lang, "btn_ai_chat"), callback_data="ai:chat"), IB(text=t(lang, "btn_ai_new"), callback_data="ai:new")],
        [IB(text=t(lang, "btn_ai_model"), callback_data="ai:model"), IB(text=t(lang, "btn_ai_reconf"), callback_data="ai:setup")],
        [IB(text=t(lang, "btn_ai_memory"), callback_data="ai:memory"), IB(text=t(lang, "btn_ai_skills"), callback_data="ai:skills")],
        [IB(text=t(lang, "btn_ai_discover"), callback_data="ai:discover"), IB(text=t(lang, "btn_ai_pending"), callback_data="ai:pending")],
        [IB(text=t(lang, "btn_home"), callback_data="m:home")]])


SETTING_GROUPS = [
    ("⏱ Pipeline", ["interval_minutes", "max_tcp_test", "max_speedtest", "retest_alive_hours", "min_score_keep"]),
    ("🧵 Threads", ["fetch_concurrency", "fetch_timeout", "tcp_concurrency", "tcp_timeout", "speed_concurrency", "speed_timeout"]),
    ("📶 Speed test", ["speed_download_bytes", "speed_upload_bytes", "iran_filter", "drop_ir_servers"]),
    ("🤖 AI", ["ai_model", "ai_temperature", "ai_max_iterations", "ai_memory_notifications", "ai_approval_required", "auto_add_sources", "discover_interval_hours"]),
    ("🔧 System", ["public_mode", "state_push_interval", "max_run_minutes", "default_lang", "top_list_size", "log_ring_size", "memory_char_limit", "user_char_limit"]),
]


def settings_kb(lang: str, db, group: int) -> IM:
    rows = [[IB(text=("• " if i == group else "") + name, callback_data=f"set:{i}") for i, (name, _) in enumerate(SETTING_GROUPS)][:3],
            [IB(text=("• " if i == group else "") + name, callback_data=f"set:{i}") for i, (name, _) in enumerate(SETTING_GROUPS)][3:]]
    for key in SETTING_GROUPS[group][1]:
        v = db.setting(key)
        if isinstance(v, bool):
            rows.append([IB(text=f"{key}: {'✅ ON' if v else '❌ OFF'}", callback_data=f"tog:{key}:{group}")])
        else:
            rows.append([IB(text=f"{key}: {v}", callback_data=f"edit:{key}:{group}")])
    rows.append([IB(text=t(lang, "btn_home"), callback_data="m:home")])
    return IM(inline_keyboard=rows)


def models_kb(models: list[str], page: int = 0) -> IM:
    per = 16
    chunk = models[page * per:(page + 1) * per]
    rows = [[IB(text=m[:40], callback_data=f"aim:{i + page * per}")] for i, m in enumerate(chunk)]
    nav = []
    if page > 0:
        nav.append(IB(text="⬅️", callback_data=f"aimp:{page - 1}"))
    if (page + 1) * per < len(models):
        nav.append(IB(text="➡️", callback_data=f"aimp:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([IB(text="◀️", callback_data="ai:menu")])
    return IM(inline_keyboard=rows)


def history_kb(lang: str, days: list[str], page: int) -> IM:
    per = 10
    chunk = days[page * per:(page + 1) * per]
    rows = [[IB(text=d, callback_data=f"histd:{d}")] for d in chunk]
    nav = []
    if page > 0:
        nav.append(IB(text="⬅️", callback_data=f"hist:{page - 1}"))
    if (page + 1) * per < len(days):
        nav.append(IB(text="➡️", callback_data=f"hist:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([IB(text=t(lang, "btn_home"), callback_data="m:home")])
    return IM(inline_keyboard=rows)
