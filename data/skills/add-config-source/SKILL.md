---
name: add-config-source
description: Add a new v2ray config source URL to the bot
origin: builtin
updated: 2026-10-02
---
# Add a config source

1. Validate with `fetch_url` that the URL returns links (vmess://, vless://...) or a base64 blob.
2. Call `add_source(url, kind)` — kind: sub|raw|html|tg. Telegram channels must be https://t.me/s/<name>.
3. Confirm with `list_sources`. Yield is visible after the next pipeline run (`run_pipeline`).
