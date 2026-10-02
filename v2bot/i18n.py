"""10-language UI strings. English is default; Persian is the second primary language.
Other languages get full coverage via a compact dictionary; missing keys fall back to English.
"""
from __future__ import annotations

LANGS: dict[str, str] = {
    "en": "🇬🇧 English", "fa": "🇮🇷 فارسی", "ar": "🇸🇦 العربية", "ru": "🇷🇺 Русский", "tr": "🇹🇷 Türkçe",
    "zh": "🇨🇳 中文", "es": "🇪🇸 Español", "de": "🇩🇪 Deutsch", "fr": "🇫🇷 Français", "hi": "🇮🇳 हिन्दी",
}

STRINGS: dict[str, dict[str, str]] = {
"en": {
    "choose_lang": "👋 Welcome! Choose your language:",
    "lang_set": "✅ Language set to {lang}",
    "menu": "🏠 <b>Main menu</b>\nStatus: {status}\nAlive configs: <b>{alive}</b> / total <b>{total}</b>\nNext scan in: {next}",
    "btn_status": "📊 Status", "btn_list": "📋 Configs", "btn_best": "🏆 Best", "btn_history": "📅 History",
    "btn_settings": "⚙️ Settings", "btn_logs": "🪵 Logs", "btn_about": "📖 How it works", "btn_ai": "🤖 kill_pv2 AI",
    "btn_sub": "🔗 Subscriptions", "btn_admins": "👮 Admins", "btn_sources": "🌐 Sources", "btn_lang": "🌍 Language",
    "btn_scan": "🚀 Scan now", "btn_back": "◀️ Back", "btn_home": "🏠 Home", "btn_public": "🌐 Public: {v}",
    "btn_send_file": "📄 Send as file", "btn_send_one": "📨 Send one by one", "btn_send_all": "📦 Send all together",
    "btn_refresh": "🔄 Refresh", "btn_cancel": "❌ Cancel", "btn_yes": "✅ Yes", "btn_no": "❌ No",
    "btn_approve": "✅ Allow", "btn_deny": "🚫 Deny", "btn_prev": "⬅️", "btn_next": "➡️",
    "no_access": "⛔ You don't have access to this.", "admin_only": "⛔ Admins only.",
    "status": ("📊 <b>Status</b>\n"
               "🤖 Bot uptime: {uptime}\n🏃 Run: #{run} ({runtime}) · stage: <b>{stage}</b>\n"
               "⏱ Scan interval: {interval} min · next in {next}\n"
               "📦 Configs: total {total} · ✅ alive {alive} · 🟡 tcp_ok {tcp_ok} · ❌ dead {dead} · 🆕 new {new}\n"
               "🌐 Sources: {sources} active\n🔝 Protocols: {protos}\n🌍 Top countries: {countries}\n"
               "💾 Last state push: {push}\n🔁 Relaunch chain: {chain}"),
    "list_title": "📋 <b>Configs</b> (sort: {order}, page {page}/{pages})",
    "list_empty": "No alive configs yet. Press 🚀 Scan now.",
    "cfg_line": "{i}. <code>{proto}</code> {flag} <b>{host}</b>:{port} · ping {ping} · ⬇️{dl} ⬆️{ul} · score {score}",
    "sort_score": "⭐ Score", "sort_ping": "⚡ Ping", "sort_dl": "⬇️ Download", "sort_ul": "⬆️ Upload",
    "pick_count": "How many configs do you want? (1–{max})", "pick_how": "How should I send {n} configs?",
    "sent_done": "✅ Sent {n} configs.", "bad_number": "Please send a valid number.",
    "history_title": "📅 <b>History</b> (per day)\n", "history_line": "{d}: tests {tests} · ok {ok} · alive {alive} · best ping {ms}ms",
    "history_day_title": "📅 <b>{d}</b> — best alive configs that day:\n",
    "settings_title": "⚙️ <b>Settings</b>\nTap a value to change it.",
    "set_prompt": "Send the new value for <b>{key}</b> (current: <code>{val}</code>):",
    "set_ok": "✅ <b>{key}</b> = <code>{val}</code>", "set_bad": "❌ Invalid value.",
    "logs_title": "🪵 <b>Live log</b> (stage: <b>{stage}</b>)\n", "log_empty": "No logs yet.",
    "scan_started": "🚀 Scan started (run #{run}). Follow it in 🪵 Logs.", "scan_running": "⏳ A scan is already running (stage: {stage}).",
    "about": (
        "📖 <b>How this bot works</b>\n\n"
        "This bot lives inside a GitHub Actions runner. Each run lasts up to ~5h45m, then it triggers a new run via the "
        "<code>GH_PAT</code> secret (workflow_dispatch) and exits. Every <b>{push}s</b> the SQLite database and files are committed "
        "to the <code>state</code> branch, so nothing is lost between runs.\n\n"
        "<b>Pipeline (every {interval} min):</b>\n"
        "1️⃣ <b>Collect</b> — fetch {sources} sources (GitHub subs, raw lists, HTML pages, Telegram channel previews). "
        "Base64 and plain text are both decoded. Protocols: vmess, vless, trojan, ss, ssr, hysteria2, tuic, wireguard.\n"
        "2️⃣ <b>Dedup</b> — each link is normalized (remark removed, params sorted) and hashed; duplicates merge into one record.\n"
        "3️⃣ <b>TCP ping</b> — {tcpc} parallel TCP handshakes to server:port, timeout {tcpt}s. Also applies Iran heuristics "
        "(blocked ports/SNI patterns, Iranian IPs removed).\n"
        "4️⃣ <b>Speed test</b> — best {maxspeed} by ping are started in real <b>xray-core</b> / <b>sing-box</b> instances; "
        "a real HTTP download ({dl}) and upload ({ul}) through the proxy measure throughput + latency.\n"
        "5️⃣ <b>Filter &amp; score</b> — score = f(ping, download, upload, stability history). Best ones become ✅ alive and go "
        "to the 🏆 Best list and subscriptions.\n\n"
        "<b>Storage:</b> SQLite (WAL) at <code>data/state.db</code> — configs, every test ever done, runs, logs, users, admins, "
        "AI sessions &amp; memory.\n\n"
        "<b>kill_pv2 AI</b> — an agent inspired by Hermes-Agent architecture: tool registry, iteration budget, "
        "approval gates for sensitive actions, persistent MEMORY/USER memory, learnable skills, Tavily web search to "
        "discover new config sources, terminal, file edit and self-bugfix with test runs.\n\n"
        "<b>Control:</b> inline buttons, reply keyboard and slash commands all work. Public mode lets anyone use the safe "
        "features; admins keep settings, AI, sources and admin management."),
    "ai_setup_url": "🤖 Let's set up kill_pv2 AI.\nSend the OpenAI-compatible <b>base_url</b> (e.g. <code>https://api.openai.com/v1</code>):",
    "ai_setup_key": "Now send the <b>API key</b> (it will be encrypted at rest and this message deleted):",
    "ai_setup_models": "Fetching models…", "ai_pick_model": "Pick a model ({n} found):",
    "ai_models_fail": "❌ Could not list models: {err}\nYou can type the model name manually:",
    "ai_ready": "✅ AI ready. Model: <code>{model}</code>\nJust send me a message, or /ai_new for a new session.",
    "ai_thinking": "🤔 thinking…", "ai_tool": "🔧 {tool}", "ai_need_approval": "⚠️ <b>Approval needed</b>\nTool: <code>{tool}</code>\n{reason}\n<pre>{args}</pre>",
    "ai_approved": "✅ Allowed — continuing…", "ai_denied": "🚫 Denied.", "ai_not_configured": "AI is not configured yet. Press 🤖 kill_pv2 AI.",
    "ai_mem_updated": "💾 Memory updated", "ai_new_session": "🆕 New AI session started.",
    "ai_menu": "🤖 <b>kill_pv2 AI</b>\nModel: <code>{model}</code>\nSession #{sid} · msgs {msgs}\nMemory {mem}% · User {user}%\nSkills: {skills}",
    "btn_ai_chat": "💬 Chat", "btn_ai_new": "🆕 New session", "btn_ai_model": "🧠 Change model", "btn_ai_reconf": "🔑 Reconfigure",
    "btn_ai_memory": "💾 Memory", "btn_ai_skills": "🧩 Skills", "btn_ai_discover": "🔎 Discover sources now", "btn_ai_pending": "⏳ Pending approvals",
    "sub_title": "🔗 <b>Subscriptions</b>\n{list}\n\nSend a request like:\n<i>best 5 configs, US ip, ping &lt; 150</i>\nor use /sub_create name count country",
    "sub_created": "✅ Subscription <b>{name}</b> created with {n} configs.", "sub_file_caption": "🔗 {name} — {n} configs (base64 sub)",
    "admins_title": "👮 <b>Admins</b>\n{list}\n\nSend <code>/admin_add ID perm1,perm2</code> or <code>/admin_del ID</code>.\nPermissions: {perms}",
    "admin_added": "✅ Admin {id} saved with: {perms}", "admin_removed": "✅ Admin {id} removed.",
    "public_on": "🌐 Public mode ON — everyone can use safe features.", "public_off": "🔒 Public mode OFF — admins only.",
    "sources_title": "🌐 <b>Sources</b> total {n} (ok {ok}, failing {fail})\nTop by yield:\n{list}\n\nSend <code>/source_add URL</code> to add.",
    "source_added": "✅ Source added.", "source_exists": "ℹ️ Source already exists.",
    "unknown": "🤷 I didn't understand. Use the menu.", "cancelled": "❌ Cancelled.",
    "relaunch": "🔁 Run time limit reached — relaunching a new run and saving state…",
    "started": "🟢 Bot started (run #{run}, chain {chain}).",
    "cmd_help": "Available commands:\n{cmds}",
},
"fa": {
    "choose_lang": "👋 خوش اومدی! زبانت رو انتخاب کن:",
    "lang_set": "✅ زبان روی {lang} تنظیم شد",
    "menu": "🏠 <b>منوی اصلی</b>\nوضعیت: {status}\nکانفیگ‌های سالم: <b>{alive}</b> / کل <b>{total}</b>\nاسکن بعدی: {next}",
    "btn_status": "📊 وضعیت", "btn_list": "📋 کانفیگ‌ها", "btn_best": "🏆 بهترین‌ها", "btn_history": "📅 تاریخچه",
    "btn_settings": "⚙️ تنظیمات", "btn_logs": "🪵 لاگ", "btn_about": "📖 توضیح کامل", "btn_ai": "🤖 kill_pv2 AI",
    "btn_sub": "🔗 ساب‌ها", "btn_admins": "👮 ادمین‌ها", "btn_sources": "🌐 منابع", "btn_lang": "🌍 زبان",
    "btn_scan": "🚀 اسکن الان", "btn_back": "◀️ برگشت", "btn_home": "🏠 خانه", "btn_public": "🌐 پابلیک: {v}",
    "btn_send_file": "📄 ارسال به‌صورت فایل", "btn_send_one": "📨 دونه‌دونه", "btn_send_all": "📦 همه باهم",
    "btn_refresh": "🔄 بروزرسانی", "btn_cancel": "❌ لغو", "btn_yes": "✅ بله", "btn_no": "❌ خیر",
    "btn_approve": "✅ اجازه بده", "btn_deny": "🚫 رد کن", "btn_prev": "⬅️", "btn_next": "➡️",
    "no_access": "⛔ به این بخش دسترسی نداری.", "admin_only": "⛔ فقط ادمین‌ها.",
    "status": ("📊 <b>وضعیت</b>\n"
               "🤖 آپتایم بات: {uptime}\n🏃 ران: #{run} ({runtime}) · مرحله: <b>{stage}</b>\n"
               "⏱ فاصله اسکن: {interval} دقیقه · بعدی تا {next}\n"
               "📦 کانفیگ‌ها: کل {total} · ✅ سالم {alive} · 🟡 tcp_ok {tcp_ok} · ❌ مرده {dead} · 🆕 جدید {new}\n"
               "🌐 منابع: {sources} فعال\n🔝 پروتکل‌ها: {protos}\n🌍 کشورها: {countries}\n"
               "💾 آخرین ذخیره‌ی وضعیت: {push}\n🔁 زنجیره‌ی ران: {chain}"),
    "list_title": "📋 <b>کانفیگ‌ها</b> (مرتب‌سازی: {order}، صفحه {page}/{pages})",
    "list_empty": "هنوز کانفیگ سالمی نیست. 🚀 اسکن الان رو بزن.",
    "cfg_line": "{i}. <code>{proto}</code> {flag} <b>{host}</b>:{port} · پینگ {ping} · ⬇️{dl} ⬆️{ul} · امتیاز {score}",
    "sort_score": "⭐ امتیاز", "sort_ping": "⚡ پینگ", "sort_dl": "⬇️ دانلود", "sort_ul": "⬆️ آپلود",
    "pick_count": "چندتا کانفیگ می‌خوای؟ (۱ تا {max})", "pick_how": "{n} کانفیگ رو چطور بفرستم؟",
    "sent_done": "✅ {n} کانفیگ ارسال شد.", "bad_number": "یه عدد معتبر بفرست.",
    "history_title": "📅 <b>تاریخچه</b> (روزانه)\n", "history_line": "{d}: تست {tests} · موفق {ok} · سالم {alive} · بهترین پینگ {ms}ms",
    "history_day_title": "📅 <b>{d}</b> — بهترین کانفیگ‌های سالم اون روز:\n",
    "settings_title": "⚙️ <b>تنظیمات</b>\nروی هر مقدار بزن تا عوضش کنی.",
    "set_prompt": "مقدار جدید برای <b>{key}</b> رو بفرست (فعلی: <code>{val}</code>):",
    "set_ok": "✅ <b>{key}</b> = <code>{val}</code>", "set_bad": "❌ مقدار نامعتبر.",
    "logs_title": "🪵 <b>لاگ زنده</b> (مرحله: <b>{stage}</b>)\n", "log_empty": "هنوز لاگی نیست.",
    "scan_started": "🚀 اسکن شروع شد (ران #{run}). از 🪵 لاگ دنبالش کن.", "scan_running": "⏳ یه اسکن در حال اجراست (مرحله: {stage}).",
    "about": (
        "📖 <b>این بات چطور کار می‌کنه</b>\n\n"
        "بات داخل یه رانر GitHub Actions زندگی می‌کنه. هر ران حداکثر ~۵ ساعت و ۴۵ دقیقه طول می‌کشه، بعد با سکرت "
        "<code>GH_PAT</code> یه ران جدید (workflow_dispatch) می‌زنه و خودش خارج می‌شه. هر <b>{push} ثانیه</b> دیتابیس SQLite و فایل‌ها "
        "روی برنچ <code>state</code> کامیت می‌شن، پس هیچ دیتایی بین ران‌ها از بین نمی‌ره.\n\n"
        "<b>پایپ‌لاین (هر {interval} دقیقه):</b>\n"
        "1️⃣ <b>جمع‌آوری</b> — {sources} منبع (ساب‌های گیت‌هاب، لیست‌های خام، صفحات HTML، پیش‌نمایش کانال‌های تلگرام). "
        "هم base64 و هم متن ساده دیکد می‌شن. پروتکل‌ها: vmess, vless, trojan, ss, ssr, hysteria2, tuic, wireguard.\n"
        "2️⃣ <b>حذف تکراری</b> — هر لینک نرمال می‌شه (ریمارک حذف، پارامترها مرتب) و هش می‌شه؛ تکراری‌ها یکی می‌شن.\n"
        "3️⃣ <b>تست پینگ TCP</b> — {tcpc} هندشیک TCP موازی به server:port با تایم‌اوت {tcpt} ثانیه. فیلتر ایران هم اعمال می‌شه "
        "(پورت/SNI های مسدود، آی‌پی‌های داخل ایران حذف).\n"
        "4️⃣ <b>تست سرعت</b> — {maxspeed} تای بهتر از نظر پینگ داخل <b>xray-core</b> / <b>sing-box</b> واقعی بالا میان؛ "
        "یه دانلود واقعی HTTP ({dl}) و آپلود ({ul}) از داخل پروکسی سرعت و تاخیر رو اندازه می‌گیره.\n"
        "5️⃣ <b>فیلتر و امتیاز</b> — امتیاز = تابعی از پینگ، دانلود، آپلود و سابقه پایداری. بهترین‌ها ✅ alive می‌شن و میرن "
        "تو لیست 🏆 و ساب‌ها.\n\n"
        "<b>ذخیره‌سازی:</b> SQLite (WAL) در <code>data/state.db</code> — کانفیگ‌ها، تمام تست‌های تاریخچه، ران‌ها، لاگ‌ها، کاربرها، ادمین‌ها، "
        "سشن‌ها و حافظه‌ی AI.\n\n"
        "<b>kill_pv2 AI</b> — ایجنتی با الهام از معماری Hermes-Agent: رجیستری ابزار، بودجه‌ی تکرار، گیت اجازه برای کارهای حساس، "
        "حافظه‌ی دائمی MEMORY/USER، اسکیل‌های قابل یادگیری، سرچ Tavily برای پیدا کردن منابع جدید کانفیگ، ترمینال، ویرایش فایل و "
        "باگ‌فیکس خودکار همراه با اجرای تست.\n\n"
        "<b>کنترل:</b> دکمه‌های شیشه‌ای، کیبورد پایین و دستورات اسلش همه کار می‌کنن. حالت پابلیک اجازه می‌ده همه از بخش‌های امن "
        "استفاده کنن؛ تنظیمات، AI، منابع و مدیریت ادمین‌ها برای ادمین‌ها می‌مونه."),
    "ai_setup_url": "🤖 بریم kill_pv2 AI رو راه بندازیم.\n<b>base_url</b> سازگار با OpenAI رو بفرست (مثلاً <code>https://api.openai.com/v1</code>):",
    "ai_setup_key": "حالا <b>API key</b> رو بفرست (رمزنگاری می‌شه و پیامت پاک می‌شه):",
    "ai_setup_models": "در حال گرفتن لیست مدل‌ها…", "ai_pick_model": "یه مدل انتخاب کن ({n} تا پیدا شد):",
    "ai_models_fail": "❌ نتونستم مدل‌ها رو بگیرم: {err}\nاسم مدل رو دستی بفرست:",
    "ai_ready": "✅ AI آماده‌ست. مدل: <code>{model}</code>\nهر پیامی بفرست، یا /ai_new برای سشن جدید.",
    "ai_thinking": "🤔 دارم فکر می‌کنم…", "ai_tool": "🔧 {tool}", "ai_need_approval": "⚠️ <b>نیاز به اجازه</b>\nابزار: <code>{tool}</code>\n{reason}\n<pre>{args}</pre>",
    "ai_approved": "✅ اجازه داده شد — ادامه می‌دم…", "ai_denied": "🚫 رد شد.", "ai_not_configured": "AI هنوز تنظیم نشده. 🤖 kill_pv2 AI رو بزن.",
    "ai_mem_updated": "💾 حافظه آپدیت شد", "ai_new_session": "🆕 سشن جدید AI شروع شد.",
    "ai_menu": "🤖 <b>kill_pv2 AI</b>\nمدل: <code>{model}</code>\nسشن #{sid} · پیام‌ها {msgs}\nحافظه {mem}% · کاربر {user}%\nاسکیل‌ها: {skills}",
    "btn_ai_chat": "💬 چت", "btn_ai_new": "🆕 سشن جدید", "btn_ai_model": "🧠 تغییر مدل", "btn_ai_reconf": "🔑 تنظیم مجدد",
    "btn_ai_memory": "💾 حافظه", "btn_ai_skills": "🧩 اسکیل‌ها", "btn_ai_discover": "🔎 پیدا کردن منبع جدید", "btn_ai_pending": "⏳ اجازه‌های معلق",
    "sub_title": "🔗 <b>ساب‌ها</b>\n{list}\n\nیه درخواست بفرست مثل:\n<i>بهترین ۵ کانفیگ، آی‌پی آمریکا، پینگ زیر ۱۵۰</i>\nیا /sub_create name count country",
    "sub_created": "✅ ساب <b>{name}</b> با {n} کانفیگ ساخته شد.", "sub_file_caption": "🔗 {name} — {n} کانفیگ (ساب base64)",
    "admins_title": "👮 <b>ادمین‌ها</b>\n{list}\n\n<code>/admin_add ID perm1,perm2</code> یا <code>/admin_del ID</code> بفرست.\nدسترسی‌ها: {perms}",
    "admin_added": "✅ ادمین {id} با دسترسی: {perms} ذخیره شد", "admin_removed": "✅ ادمین {id} حذف شد.",
    "public_on": "🌐 حالت پابلیک روشن — همه می‌تونن از بخش‌های امن استفاده کنن.", "public_off": "🔒 حالت پابلیک خاموش — فقط ادمین‌ها.",
    "sources_title": "🌐 <b>منابع</b> کل {n} (سالم {ok}، خراب {fail})\nپربازده‌ترین‌ها:\n{list}\n\n<code>/source_add URL</code> برای اضافه کردن.",
    "source_added": "✅ منبع اضافه شد.", "source_exists": "ℹ️ این منبع از قبل هست.",
    "unknown": "🤷 متوجه نشدم. از منو استفاده کن.", "cancelled": "❌ لغو شد.",
    "relaunch": "🔁 زمان ران تموم شد — ران جدید می‌زنم و وضعیت ذخیره می‌شه…",
    "started": "🟢 بات روشن شد (ران #{run}، زنجیره {chain}).",
    "cmd_help": "دستورات موجود:\n{cmds}",
},
}

# Compact translations for the other 8 languages (keys not present fall back to English).
_COMPACT: dict[str, dict[str, str]] = {
"ar": {"choose_lang": "👋 أهلاً! اختر لغتك:", "lang_set": "✅ تم ضبط اللغة: {lang}", "btn_status": "📊 الحالة", "btn_list": "📋 الإعدادات",
       "btn_best": "🏆 الأفضل", "btn_history": "📅 السجل", "btn_settings": "⚙️ الإعدادات", "btn_logs": "🪵 السجلات", "btn_about": "📖 كيف يعمل",
       "btn_sub": "🔗 الاشتراكات", "btn_admins": "👮 المشرفون", "btn_sources": "🌐 المصادر", "btn_lang": "🌍 اللغة", "btn_scan": "🚀 افحص الآن",
       "btn_back": "◀️ رجوع", "btn_home": "🏠 الرئيسية", "no_access": "⛔ ليس لديك صلاحية.", "list_empty": "لا توجد إعدادات حية بعد.",
       "menu": "🏠 <b>القائمة الرئيسية</b>\nالحالة: {status}\nحية: <b>{alive}</b> / الكل <b>{total}</b>\nالفحص التالي: {next}"},
"ru": {"choose_lang": "👋 Привет! Выберите язык:", "lang_set": "✅ Язык: {lang}", "btn_status": "📊 Статус", "btn_list": "📋 Конфиги",
       "btn_best": "🏆 Лучшие", "btn_history": "📅 История", "btn_settings": "⚙️ Настройки", "btn_logs": "🪵 Логи", "btn_about": "📖 Как работает",
       "btn_sub": "🔗 Подписки", "btn_admins": "👮 Админы", "btn_sources": "🌐 Источники", "btn_lang": "🌍 Язык", "btn_scan": "🚀 Сканировать",
       "btn_back": "◀️ Назад", "btn_home": "🏠 Домой", "no_access": "⛔ Нет доступа.", "list_empty": "Живых конфигов пока нет.",
       "menu": "🏠 <b>Главное меню</b>\nСтатус: {status}\nЖивых: <b>{alive}</b> / всего <b>{total}</b>\nСледующий скан: {next}"},
"tr": {"choose_lang": "👋 Hoş geldin! Dilini seç:", "lang_set": "✅ Dil: {lang}", "btn_status": "📊 Durum", "btn_list": "📋 Configler",
       "btn_best": "🏆 En iyiler", "btn_history": "📅 Geçmiş", "btn_settings": "⚙️ Ayarlar", "btn_logs": "🪵 Loglar", "btn_about": "📖 Nasıl çalışır",
       "btn_sub": "🔗 Abonelikler", "btn_admins": "👮 Yöneticiler", "btn_sources": "🌐 Kaynaklar", "btn_lang": "🌍 Dil", "btn_scan": "🚀 Şimdi tara",
       "btn_back": "◀️ Geri", "btn_home": "🏠 Ana sayfa", "no_access": "⛔ Erişimin yok.", "list_empty": "Henüz çalışan config yok.",
       "menu": "🏠 <b>Ana menü</b>\nDurum: {status}\nÇalışan: <b>{alive}</b> / toplam <b>{total}</b>\nSonraki tarama: {next}"},
"zh": {"choose_lang": "👋 欢迎！请选择语言：", "lang_set": "✅ 语言：{lang}", "btn_status": "📊 状态", "btn_list": "📋 配置",
       "btn_best": "🏆 最佳", "btn_history": "📅 历史", "btn_settings": "⚙️ 设置", "btn_logs": "🪵 日志", "btn_about": "📖 工作原理",
       "btn_sub": "🔗 订阅", "btn_admins": "👮 管理员", "btn_sources": "🌐 来源", "btn_lang": "🌍 语言", "btn_scan": "🚀 立即扫描",
       "btn_back": "◀️ 返回", "btn_home": "🏠 主页", "no_access": "⛔ 无权限。", "list_empty": "还没有可用配置。",
       "menu": "🏠 <b>主菜单</b>\n状态：{status}\n可用：<b>{alive}</b> / 总计 <b>{total}</b>\n下次扫描：{next}"},
"es": {"choose_lang": "👋 ¡Bienvenido! Elige tu idioma:", "lang_set": "✅ Idioma: {lang}", "btn_status": "📊 Estado", "btn_list": "📋 Configs",
       "btn_best": "🏆 Mejores", "btn_history": "📅 Historial", "btn_settings": "⚙️ Ajustes", "btn_logs": "🪵 Logs", "btn_about": "📖 Cómo funciona",
       "btn_sub": "🔗 Suscripciones", "btn_admins": "👮 Admins", "btn_sources": "🌐 Fuentes", "btn_lang": "🌍 Idioma", "btn_scan": "🚀 Escanear",
       "btn_back": "◀️ Atrás", "btn_home": "🏠 Inicio", "no_access": "⛔ Sin acceso.", "list_empty": "Aún no hay configs vivas.",
       "menu": "🏠 <b>Menú principal</b>\nEstado: {status}\nVivas: <b>{alive}</b> / total <b>{total}</b>\nPróximo escaneo: {next}"},
"de": {"choose_lang": "👋 Willkommen! Wähle deine Sprache:", "lang_set": "✅ Sprache: {lang}", "btn_status": "📊 Status", "btn_list": "📋 Configs",
       "btn_best": "🏆 Beste", "btn_history": "📅 Verlauf", "btn_settings": "⚙️ Einstellungen", "btn_logs": "🪵 Logs", "btn_about": "📖 Funktionsweise",
       "btn_sub": "🔗 Abos", "btn_admins": "👮 Admins", "btn_sources": "🌐 Quellen", "btn_lang": "🌍 Sprache", "btn_scan": "🚀 Jetzt scannen",
       "btn_back": "◀️ Zurück", "btn_home": "🏠 Start", "no_access": "⛔ Kein Zugriff.", "list_empty": "Noch keine funktionierenden Configs.",
       "menu": "🏠 <b>Hauptmenü</b>\nStatus: {status}\nAktiv: <b>{alive}</b> / gesamt <b>{total}</b>\nNächster Scan: {next}"},
"fr": {"choose_lang": "👋 Bienvenue ! Choisissez votre langue :", "lang_set": "✅ Langue : {lang}", "btn_status": "📊 Statut", "btn_list": "📋 Configs",
       "btn_best": "🏆 Meilleurs", "btn_history": "📅 Historique", "btn_settings": "⚙️ Réglages", "btn_logs": "🪵 Logs", "btn_about": "📖 Fonctionnement",
       "btn_sub": "🔗 Abonnements", "btn_admins": "👮 Admins", "btn_sources": "🌐 Sources", "btn_lang": "🌍 Langue", "btn_scan": "🚀 Scanner",
       "btn_back": "◀️ Retour", "btn_home": "🏠 Accueil", "no_access": "⛔ Accès refusé.", "list_empty": "Pas encore de configs actives.",
       "menu": "🏠 <b>Menu principal</b>\nStatut : {status}\nActives : <b>{alive}</b> / total <b>{total}</b>\nProchain scan : {next}"},
"hi": {"choose_lang": "👋 स्वागत है! अपनी भाषा चुनें:", "lang_set": "✅ भाषा: {lang}", "btn_status": "📊 स्थिति", "btn_list": "📋 कॉन्फ़िग",
       "btn_best": "🏆 सर्वश्रेष्ठ", "btn_history": "📅 इतिहास", "btn_settings": "⚙️ सेटिंग्स", "btn_logs": "🪵 लॉग", "btn_about": "📖 कैसे काम करता है",
       "btn_sub": "🔗 सब्सक्रिप्शन", "btn_admins": "👮 एडमिन", "btn_sources": "🌐 स्रोत", "btn_lang": "🌍 भाषा", "btn_scan": "🚀 अभी स्कैन करें",
       "btn_back": "◀️ वापस", "btn_home": "🏠 होम", "no_access": "⛔ पहुँच नहीं है।", "list_empty": "अभी कोई सक्रिय कॉन्फ़िग नहीं।",
       "menu": "🏠 <b>मुख्य मेनू</b>\nस्थिति: {status}\nसक्रिय: <b>{alive}</b> / कुल <b>{total}</b>\nअगला स्कैन: {next}"},
}
for _code, _d in _COMPACT.items():
    STRINGS[_code] = _d


def t(lang: str, _key: str, /, **kw) -> str:
    key = _key
    table = STRINGS.get(lang) or STRINGS["en"]
    s = table.get(key) or STRINGS["en"].get(key) or key
    try:
        return s.format(**kw) if kw else s
    except (KeyError, IndexError):
        return s
