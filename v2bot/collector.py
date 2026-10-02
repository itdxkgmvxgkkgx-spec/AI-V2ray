"""Stage 1 (collect) + Stage 2 (dedup).  Fetches all enabled sources concurrently."""
from __future__ import annotations

import asyncio
import re
import time
from html import unescape

import aiohttp

from .db import DB
from .parser import extract_links, parse_many

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    text = text.replace("<br/>", "\n").replace("<br>", "\n").replace("</div>", "\n")
    text = _TAG_RE.sub(" ", text)
    return unescape(text)


async def fetch_source(session: aiohttp.ClientSession, url: str, kind: str, timeout: int) -> tuple[bool, list[str]]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout), headers={"User-Agent": UA}, ssl=False) as r:
            if r.status != 200:
                return False, []
            raw = await r.read()
            if len(raw) > 12_000_000:
                raw = raw[:12_000_000]
            text = raw.decode("utf-8", "ignore")
    except Exception:
        return False, []
    if kind in ("html", "tg") or ("<html" in text[:2000].lower()):
        text = _strip_html(text)
    links = extract_links(text)
    return True, links


async def collect(db: DB, log, run_id: int | None = None) -> tuple[int, int, int]:
    """Returns (found_links, unique_after_dedup, brand_new_in_db)."""
    sources = await db.sources(enabled_only=True)
    conc = int(db.setting("fetch_concurrency", 24))
    timeout = int(db.setting("fetch_timeout", 20))
    sem = asyncio.Semaphore(conc)
    found_total = 0
    all_parsed: dict[str, dict] = {}
    done = 0

    connector = aiohttp.TCPConnector(limit=conc, ttl_dns_cache=300, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        async def one(src):
            nonlocal found_total, done
            async with sem:
                ok, links = await fetch_source(session, src["url"], src["kind"], timeout)
            parsed = parse_many(links, src["id"]) if ok else []
            await db.source_result(src["id"], ok and len(links) > 0, len(parsed))
            found_total += len(links)
            for p in parsed:
                if p["hash"] not in all_parsed:
                    all_parsed[p["hash"]] = p
            done += 1
            if done % 25 == 0 or done == len(sources):
                await log("collect", f"fetched {done}/{len(sources)} sources · links {found_total} · unique {len(all_parsed)}")

        await asyncio.gather(*(one(s) for s in sources), return_exceptions=True)

    items = list(all_parsed.values())
    await log("dedup", f"{found_total} links -> {len(items)} unique (removed {found_total - len(items)} duplicates)")
    new = 0
    for i in range(0, len(items), 2000):
        new += await db.upsert_configs(items[i:i + 2000])
    await log("dedup", f"{new} brand-new configs stored")
    if run_id:
        await db.update_run(run_id, found=found_total, deduped=found_total - len(items), unique_new=new)
    return found_total, len(items), new


async def fetch_text(url: str, timeout: int = 20) -> str:
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout), headers={"User-Agent": UA}, ssl=False) as r:
            return (await r.read())[:3_000_000].decode("utf-8", "ignore")
