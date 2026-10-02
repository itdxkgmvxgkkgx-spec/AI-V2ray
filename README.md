# v2ray_config — Always-on V2Ray config hunter (GitHub Actions + Telegram + kill_pv2 AI)

> 🇮🇷 نسخه فارسی پایین‌تر است.

A bot that lives permanently inside **GitHub Actions**, crawls the whole internet for V2Ray/Xray configs that work from
inside Iran, pushes them through a 5-stage pipeline (collect → dedup → TCP ping → real download/upload through
xray-core / sing-box → filter & score), and is fully controlled from **Telegram**. Every byte of state is persisted to a
git branch every 60 s, so a new run picks up *exactly* where the previous one stopped. It also ships **kill_pv2**, a
Hermes-Agent-style AI operator that can search the web (Tavily) for new sources, edit the project, fix bugs, run tests,
remember you, and learn skills — but asks permission before anything sensitive.

---

## 1. Quick start (5 minutes)

1. **Create the repo** → upload this project (or `git push`) to GitHub, branch `main`.
2. **Create a Telegram bot** with [@BotFather](https://t.me/BotFather) → copy the token.
3. **Get your Telegram numeric ID** (e.g. from [@userinfobot](https://t.me/userinfobot)).
4. **Create a GitHub PAT** (classic) with scopes **`repo`** + **`workflow`** → this is what lets a run start the next run.
5. **(Optional) Tavily key** from https://tavily.com → used by kill_pv2 to discover new config sources.
6. **Repo → Settings → Secrets and variables → Actions → New repository secret**:

   | Secret            | Required | Value                                   |
   |-------------------|----------|-----------------------------------------|
   | `BOT_TOKEN`       | ✅       | BotFather token                         |
   | `ADMIN_ID`        | ✅       | your numeric Telegram id (owner)        |
   | `GH_PAT`          | ✅       | PAT with `repo` + `workflow`            |
   | `TAVILY_API_KEY`  | ⬜       | Tavily search key                       |

7. **Repo → Settings → Actions → General → Workflow permissions → "Read and write permissions"** (needed to push the `state` branch).
8. **Actions → "v2ray_config bot" → Run workflow**. That's it — from now on it relaunches itself forever.
9. Open your bot in Telegram, press **/start**, pick a language, press **🚀 Scan now**.

The first run creates an orphan branch **`state`** that holds `data/` (SQLite db, memories, skills, subs). Never edit it by hand.

---

## 2. How the always-on loop works

```
run N (≤ 5h45m) ──► GH_PAT workflow_dispatch(chain=N+1) ──► run N+1 ──► …
   │  every 60 s: PRAGMA wal_checkpoint → copy data/ → git commit → push `state`
   └─ on boot: clone `state` → copy data/ back → open DB → nothing lost
```

* `MAX_RUN_MINUTES=345` (settings → `max_run_minutes`) keeps us under GitHub's 6 h hard limit.
* `concurrency.group` + `cancel_other_runs()` guarantee only one bot polls the Telegram token.
* A 6-hourly `schedule` cron is a watchdog: if the chain ever breaks, it restarts.
* On the rare overlapping push, `state_sync.push()` rebases, and force-pushes as last resort — the DB file is a single
  binary, so the newest full snapshot wins.

---

## 3. The pipeline (every `interval_minutes`, default 30)

| Stage | Module | What happens |
|---|---|---|
| 1 Collect | `collector.py` | ~160 built-in sources (GitHub raw subs, HTML pages, `t.me/s/<channel>` previews) fetched with `fetch_concurrency` workers. Plain, base64 and HTML-embedded links are all extracted. |
| 2 Dedup | `parser.py` | Each link is parsed (vmess/vless/trojan/ss/ssr/hysteria2/tuic/wireguard), normalized (remark dropped, params canonical) and hashed → duplicates merge into one row with `seen_count`. |
| 3 TCP ping | `tester.py:stage_tcp` | `tcp_concurrency` (300) parallel TCP handshakes, `tcp_timeout` s, one retry. Iran pre-filter: private IPs, `.ir` hosts. |
| 3b Geo | `tester.py:stage_geo` | ip-api batch lookup → country flag; servers located in **IR** are dropped (`drop_ir_servers`). |
| 4 Speed | `tester.py:stage_speed` | Best `max_speedtest` by ping (host-diverse: ≤3 per host, ≤12 per /24, rotating, recently-failed last) are started as real **xray-core** / **sing-box** processes; a real HTTPS latency probe + `speed_download_bytes` download + `speed_upload_bytes` upload through the local proxy. |
| 5 Filter/Score | `tester.py:stage_filter` | `score = 45·log(dl) + 15·log(ul) + 30·latency + 10·stability` (0–100). Alive configs feed 🏆 Best and subscriptions; dead ones are pruned after 14 days. |

Every single test is stored in the `tests` table → 📅 History shows per-day stats and the best configs of any day.

**Measured in the sandbox:** 159 sources → 238 k links → 53 k unique → 1 170/3 000 TCP-alive → real speeds up to 35 Mbps down / 46 Mbps up.

---

## 4. Telegram UI

Everything is reachable three ways: **inline (glass) buttons**, the **reply keyboard**, and **slash commands** (`/help`).

| Feature | Buttons / command |
|---|---|
| Status, uptime, run #, stage, counts, last state push | 📊 Status · `/status` |
| Best / full list with sort by ⭐score ⚡ping ⬇️dl ⬆️ul, paging | 🏆 Best · 📋 Configs · `/best` · `/list ping` |
| Send N configs: as **file** (plain + base64 sub), **all together**, or **one by one** | 📤 on list · `/get 10 ping US` |
| Daily history + drill into a day | 📅 History · `/history` |
| Live log stream (edits one message for 60 s) + stage | 🪵 Logs · `/logs` |
| Settings editor (grouped: Pipeline / Threads / Speed test / AI / System), toggles + typed values | ⚙️ Settings · `/set key value` |
| Subscriptions: natural language ("بهترین ۵ کانفیگ آمریکا پینگ زیر ۱۵۰"), `/sub_create name count CC`, `/sub name`, refresh | 🔗 Subscriptions |
| Admin management with per-feature permissions | 👮 Admins · `/admin_add ID logs,pipeline` · `/admin_del ID` |
| Public mode (anyone can use safe features; sensitive stays admin-only) | 🌐 Public toggle · `/public` |
| Sources list + add | 🌐 Sources · `/source_add URL` |
| Full explanation of how the bot works | 📖 How it works · `/about` |
| 10 languages (EN default, FA second, AR RU TR ZH ES DE FR HI) | 🌍 Language · `/lang` |
| kill_pv2 AI | 🤖 · `/ai` · `/ai_new` · `/ai_setup` · `/ai_pending` · `/ai_memory` |

Permissions: `settings, pipeline, ai, admins, logs, subs, sources, terminal`. The owner (`ADMIN_ID`) has everything.

---

## 5. kill_pv2 AI (Hermes-Agent-inspired)

First press of 🤖 asks for an OpenAI-compatible **base_url** and **API key** (encrypted at rest with a key derived from
your secrets; the message with the key is deleted), then lists `/models` so you pick one. Change later in ⚙️ AI group.

Architecture borrowed from [hermes-agent](https://github.com/NousResearch/hermes-agent):

* **Tool registry** (`ai/registry.py`) — 32 self-registering tools with a *risk tier*; `ai/tools.py` holds them.
* **Iteration budget** per turn (`ai_max_iterations`).
* **3-tier system prompt** (`ai/prompt.py`): stable (identity, rules, project map, skills index) · context · volatile (memory, date); cached per session.
* **Approval gates** — `shell`, `write_file`, `edit_file`, `set_setting`, `add_source`, `run_pipeline`, `create_subscription`,
  `skill_manage`, `git_commit_push`, `manage_admin` pause the turn and show ✅ Allow / 🚫 Deny buttons. The pending call is
  stored in SQLite, so it survives a relaunch (`/ai_pending`).
* **Memory** — `data/memories/MEMORY.md` + `USER.md`, `§`-separated, char-limited, add/replace/remove, injection scan,
  and **notifications** (`ai_memory_notifications = off|on|verbose`) e.g. `💾 user ➕ User wants to be called داداش`.
* **Skills** — `data/skills/<name>/SKILL.md`, progressive disclosure, provenance; two builtin skills (add-config-source, fix-bug).
* **Session DB + FTS5** `session_search`; automatic context compression with summary.
* **Project awareness** — `project_map`, `list_files`, `read_file`, `search_code`, `git_status`, `run_tests`
  (compiles + `tests/selftest.py`), `git_commit_push` to `main`.
* **Source discovery** — `web_search` (Tavily) + `discover_sources` + `fetch_url` verification; runs automatically every
  `discover_interval_hours`, adds automatically only when `auto_add_sources` is on, otherwise notifies the owner.

Just type to it. Examples: *"منو داداش صدا کن"*, *"interval رو بکن ۱۵ دقیقه"*, *"5 best configs with US ip, ping < 150, send as sub"*,
*"the TCP stage logs nothing when 0 sources — find and fix it, run tests"*.

---

## 6. Project layout

```
main.py                     entrypoint (restore → DB → pipeline → bot → pusher → discovery → relaunch timer)
.github/workflows/bot.yml   the workflow (workflow_dispatch chain, cron watchdog, cores cache)
v2bot/config.py             ENV secrets + DEFAULT_SETTINGS (everything editable from Telegram)
v2bot/db.py                 SQLite WAL schema + queries (settings, users, admins, sources, configs, tests, runs, logs, subs, ai_*)
v2bot/i18n.py               10 languages
v2bot/sources.py            builtin sources + Tavily discovery queries
v2bot/parser.py             link parsing + dedup hash
v2bot/collector.py          stage 1+2
v2bot/outbound.py           link → xray / sing-box JSON
v2bot/tester.py             binaries, stage 3/geo/4/5, scoring
v2bot/pipeline.py           orchestrator + live log listeners
v2bot/state_sync.py         state branch persistence + relaunch + overlap cancel
v2bot/bot/                  aiogram 3 UI (ui.py keyboards, common.py, handlers_core.py, handlers_admin.py, app.py)
v2bot/ai/                   kill_pv2 (registry, tools, memory, skills, llm, prompt, agent)
tests/selftest.py           31 offline checks; SELFTEST_NET=1 adds live fetch/tcp/xray checks
data/                       runtime state (persisted on branch `state`)
```

### Settings reference (`/set key value` or ⚙️)

`interval_minutes` scan period · `fetch_concurrency/fetch_timeout` · `tcp_concurrency/tcp_timeout/max_tcp_test` ·
`speed_concurrency/speed_timeout/max_speedtest/speed_download_bytes/speed_upload_bytes` · `retest_alive_hours` ·
`min_score_keep` · `iran_filter` · `drop_ir_servers` · `public_mode` · `auto_add_sources` · `discover_interval_hours` ·
`ai_model/ai_temperature/ai_max_iterations/ai_memory_notifications/ai_approval_required` · `memory_char_limit/user_char_limit` ·
`state_push_interval` · `max_run_minutes` · `default_lang` · `top_list_size` · `log_ring_size`.

### Run locally
```bash
pip install -r requirements.txt
export BOT_TOKEN=… ADMIN_ID=… TAVILY_API_KEY=…      # GH_PAT optional locally (no relaunch / no state branch)
python main.py
python tests/selftest.py            # offline tests
SELFTEST_NET=1 python tests/selftest.py
```

### Known limits / next steps
* GitHub runners are outside Iran: "works in Iran" is approximated with heuristics (IR servers removed, blocked
  patterns, real TLS/WS handshake through xray). Adding a probe from inside Iran (a tiny VPS reporting back) would make it exact.
* ip-api free tier is 15 batch calls/min → geo tagging is capped at 600 configs per run (catches up over runs).
* Telegram message edits are rate-limited; the live log refreshes ≤1×/1.2 s.

---
---

# 🇮🇷 راهنمای فارسی

## این پروژه چیه؟
یه بات تلگرامه که **همیشه داخل GitHub Actions روشنه**، کل اینترنت رو دنبال کانفیگ V2Ray/Xray که تو ایران کار کنه می‌گرده،
کانفیگ‌ها رو از ۵ مرحله رد می‌کنه (جمع‌آوری → حذف تکراری → تست پینگ TCP → تست واقعی دانلود/آپلود داخل xray-core / sing-box →
فیلتر و امتیازدهی) و همه‌چیزش از تلگرام کنترل می‌شه. هر ۶۰ ثانیه کل دیتابیس روی برنچ `state` ذخیره می‌شه، پس وقتی ران جدید
شروع می‌شه **هیچ دیتایی از بین نمی‌ره**. یه ایجنت هوش مصنوعی به اسم **kill_pv2** هم داره (با معماری الهام‌گرفته از Hermes-Agent)
که با Tavily منبع جدید پیدا می‌کنه، می‌تونه تو پروژه تغییر بده، باگ فیکس کنه، تست بزنه، حافظه داره، اسکیل یاد می‌گیره — ولی
برای هر کار حساس اول ازت اجازه می‌گیره.

## راه‌اندازی (۵ دقیقه)
1. پروژه رو تو یه ریپوی گیت‌هاب روی برنچ `main` بذار.
2. از [@BotFather](https://t.me/BotFather) بات بساز و توکن بگیر.
3. آی‌دی عددی تلگرامت رو بگیر ([@userinfobot](https://t.me/userinfobot)).
4. یه **GitHub PAT (classic)** با دسترسی **`repo` + `workflow`** بساز — این همونیه که اجازه می‌ده هر ران، ران بعدی رو استارت بزنه.
5. (اختیاری) کلید Tavily از tavily.com.
6. **Settings → Secrets and variables → Actions** این سکرت‌ها رو بساز: `BOT_TOKEN`، `ADMIN_ID`، `GH_PAT`، `TAVILY_API_KEY`.
7. **Settings → Actions → General → Workflow permissions** رو روی **Read and write** بذار (برای پوش برنچ `state`).
8. **Actions → v2ray_config bot → Run workflow**. تمام! از اینجا به بعد خودش خودش رو دوباره اجرا می‌کنه.
9. تو تلگرام `/start` بزن، زبان انتخاب کن، بعد **🚀 اسکن الان**.

## چطور همیشه روشن می‌مونه؟
هر ران حداکثر ۵ ساعت و ۴۵ دقیقه (`max_run_minutes`) کار می‌کنه، بعد با `GH_PAT` یه `workflow_dispatch` می‌زنه و خودش خاموش می‌شه.
`concurrency` + کنسل کردن ران‌های هم‌زمان تضمین می‌کنه فقط یه بات به توکن تلگرام وصله. یه cron هر ۶ ساعت هم نگهبانه: اگه زنجیره
شکست، دوباره راهش می‌ندازه. دیتا (`data/`: دیتابیس SQLite، حافظه‌ی AI، اسکیل‌ها، ساب‌ها) هر ۶۰ ثانیه روی برنچ `state` کامیت می‌شه
و هر ران اول همون رو برمی‌گردونه.

## منوی تلگرام
همه‌چیز سه راه داره: **دکمه‌های شیشه‌ای**، **کیبورد پایین**، **دستورات اسلش** (`/help`).

* 📊 **وضعیت** — آپتایم، شماره ران، مرحله، تعداد کانفیگ‌ها، منابع، آخرین ذخیره‌ی وضعیت، زنجیره‌ی ران.
* 🏆 **بهترین‌ها** / 📋 **کانفیگ‌ها** — مرتب‌سازی با امتیاز/پینگ/دانلود/آپلود، صفحه‌بندی، دکمه 📤 → تعداد بده → **فایل** (متن + ساب base64)،
  **همه باهم**، یا **دونه‌دونه**. دستور: `/get 10 ping US`.
* 📅 **تاریخچه** — آمار روزانه؛ روی هر روز بزن بهترین کانفیگ‌های همون روز رو می‌آره (همه‌ی تست‌ها تو دیتابیس می‌مونن).
* 🪵 **لاگ** — ۲۵ خط آخر + حالت **📡 Live** که ۶۰ ثانیه همون پیام رو زنده آپدیت می‌کنه؛ مرحله‌ی فعلی هم نشون می‌ده.
* ⚙️ **تنظیمات** — گروه‌بندی‌شده: پایپ‌لاین (فاصله‌ی اسکن، تعداد تست)، تردها (`tcp_concurrency`, `speed_concurrency`…)، تست سرعت،
  AI، سیستم. سوییچ‌ها با یه کلیک، مقدارها با تایپ. دستور: `/set interval_minutes 15`.
* 🔗 **ساب‌ها** — به زبان آدمیزاد بنویس: «بهترین ۵ کانفیگ آمریکا پینگ زیر ۱۵۰» → فایل ساب + لینک‌ها می‌آد. یا `/sub_create usfast 5 US`
  و بعداً `/sub usfast`. دکمه 🔄 ساب رو با کانفیگ‌های تازه می‌سازه.
* 👮 **ادمین‌ها** — `/admin_add 123456 logs,pipeline` یا `all`؛ `/admin_del 123456`؛ دسترسی‌ها: `settings, pipeline, ai, admins, logs, subs, sources, terminal`.
* 🌐 **پابلیک** — روشن کنی هر کسی می‌تونه استارت بزنه و از بخش‌های امن (لیست، ساب، تاریخچه، توضیح) استفاده کنه؛ تنظیمات/AI/منابع/ادمین‌ها فقط برای ادمین‌ها.
* 🌐 **منابع** — لیست و بازدهی هر منبع، `/source_add URL`. منابعی که ۱۰ بار پشت‌سرهم خراب باشن خودکار غیرفعال می‌شن.
* 📖 **توضیح کامل** — همون چیزی که اینجا نوشته، داخل بات.
* 🌍 **زبان** — ۱۰ زبان، پیش‌فرض انگلیسی، فارسی زبان دوم اصلی.

## kill_pv2 AI
اولین بار که 🤖 رو بزنی `base_url` و `API key` (سازگار با OpenAI: OpenAI، OpenRouter، Groq، DeepSeek، لوکال…) رو می‌گیره، کلید رو
رمزنگاری‌شده ذخیره می‌کنه و پیامت رو پاک می‌کنه، بعد لیست مدل‌ها رو می‌آره که انتخاب کنی. بعداً از ⚙️ → AI عوضش می‌کنی.

* **۳۲ ابزار** با سطح ریسک: خواندنی‌ها (نقشه‌ی پروژه، خوندن فایل، سرچ کد، وضعیت، لاگ، لیست کانفیگ، تاریخچه، منابع، Tavily، تست) خودکار
  اجرا می‌شن؛ حساس‌ها (ترمینال، نوشتن/ویرایش فایل، تغییر تنظیمات، اضافه کردن منبع، ساخت ساب، اجرای اسکن، کامیت/پوش، مدیریت ادمین،
  ساخت اسکیل) **اول با دکمه ✅/🚫 ازت اجازه می‌گیرن**. درخواست‌های معلق تو دیتابیس می‌مونن (`/ai_pending`).
* **حافظه**: `MEMORY.md` (پروژه/محیط) و `USER.md` (تو). بگی «منو داداش صدا کن» ذخیره می‌کنه و نوتیف می‌ده:
  `💾 user ➕ User wants to be called داداش`. (`ai_memory_notifications = off|on|verbose`)
* **اسکیل‌ها**: `data/skills/<name>/SKILL.md` — وقتی یه روال چندمرحله‌ای تکرارشونده انجام داد، ذخیره‌ش می‌کنه و دفعه‌ی بعد اول اونو می‌خونه.
* **پروژه رو کامل می‌شناسه**: `project_map` دقیقاً می‌گه هر فایل چیه، دیتا کجاست، برای هر کاری چه کلیدی رو عوض کنه.
* **باگ‌فیکس**: بگی «این بخش این باگو داره» → پیدا می‌کنه، می‌خونه، اگه لازم شد سرچ می‌کنه، با اجازه‌ی تو ویرایش می‌کنه، `run_tests` می‌زنه،
  دیف رو گزارش می‌ده، با اجازه `git_commit_push` روی `main`.
* **منبع‌یابی**: هر `discover_interval_hours` ساعت با Tavily سرچ می‌کنه، هر URL رو با `fetch_url` چک می‌کنه (حداقل ۵ لینک)، اگه
  `auto_add_sources` روشن باشه اضافه می‌کنه وگرنه بهت گزارش می‌ده. از منوی AI دکمه «🔎 پیدا کردن منبع جدید» هم هست.
* **سشن‌ها** تو SQLite با جست‌وجوی متنی (`session_search`)، فشرده‌سازی خودکار کانتکست، بودجه‌ی تکرار، `/ai_new` برای سشن تازه.

## چیزهایی که خودم اضافه کردم (طبق سلیقه، چیزی حذف نشده)
* نگهبان cron ۶ ساعته + کنسل ران‌های هم‌زمان (که دو تا بات روی یه توکن نیفتن).
* کش باینری xray/sing-box بین ران‌ها.
* انتخاب هوشمند کاندیدای تست سرعت (تنوع هاست/شبکه، چرخش، شکست‌خورده‌های اخیر آخر صف) تا آی‌پی‌های anycast کلودفلر جا رو تنگ نکنن.
* امتیاز پایداری (سابقه‌ی موفق/ناموفق هر کانفیگ) داخل score.
* فیلتر رمز‌های نامعتبر Shadowsocks قبل از تست.
* ساب‌ساز با زبان طبیعی بدون نیاز به LLM (برای وقتی AI تنظیم نشده یا کاربر پابلیکه).
* کلید AI رمزنگاری‌شده (Fernet مشتق از سکرت‌ها)، اسکن injection روی حافظه، مخفی ماندن سکرت‌ها از AI.
* زبان‌ها: ۸ زبان دیگه با ترجمه‌ی فشرده و fallback به انگلیسی.

## محدودیت‌ها
رانر گیت‌هاب داخل ایران نیست؛ «تو ایران کار می‌کنه» با heuristics تقریب زده می‌شه (حذف سرورهای ایران، هندشیک واقعی TLS/WS، سرعت واقعی).
اگه یه پروب کوچیک داخل ایران اضافه بشه که نتیجه رو برگردونه، دقیق می‌شه — جاش تو `tester.py` آماده‌ست.
