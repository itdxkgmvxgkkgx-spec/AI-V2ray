"""Stages 3-5: TCP ping -> real download/upload through xray/sing-box -> filter & score.

Also: Iran-friendliness heuristics, GeoIP (via ip-api batch), binary bootstrap for xray-core / sing-box.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import os
import platform
import re
import shutil
import socket
import tarfile
import time
import zipfile
from pathlib import Path

import aiohttp

from .config import BIN_DIR, DATA_DIR
from .db import DB
from .outbound import engine_for, singbox_config, xray_config

# ---------------------------------------------------------------- binaries
XRAY_VER = "v25.3.6"
SINGBOX_VER = "1.11.7"


def _arch() -> str:
    m = platform.machine().lower()
    return "arm64" if m in ("aarch64", "arm64") else "64"


async def ensure_binaries(log) -> dict[str, str | None]:
    """Download xray-core and sing-box into bin/ (once). Returns paths (None when unavailable)."""
    out: dict[str, str | None] = {"xray": None, "singbox": None}
    xray = BIN_DIR / "xray"
    sb = BIN_DIR / "sing-box"
    if not xray.exists() and not shutil.which("xray"):
        url = f"https://github.com/XTLS/Xray-core/releases/download/{XRAY_VER}/Xray-linux-{_arch()}.zip"
        try:
            await _download(url, BIN_DIR / "xray.zip")
            with zipfile.ZipFile(BIN_DIR / "xray.zip") as z:
                z.extract("xray", BIN_DIR)
            xray.chmod(0o755)
            (BIN_DIR / "xray.zip").unlink(missing_ok=True)
            await log("init", f"xray-core {XRAY_VER} installed")
        except Exception as e:
            await log("init", f"xray download failed: {e}", "WARN")
    if not sb.exists() and not shutil.which("sing-box"):
        a = "arm64" if _arch() == "arm64" else "amd64"
        url = f"https://github.com/SagerNet/sing-box/releases/download/v{SINGBOX_VER}/sing-box-{SINGBOX_VER}-linux-{a}.tar.gz"
        try:
            await _download(url, BIN_DIR / "sb.tgz")
            with tarfile.open(BIN_DIR / "sb.tgz") as t:
                for m in t.getmembers():
                    if m.name.endswith("/sing-box"):
                        m.name = "sing-box"
                        t.extract(m, BIN_DIR)
            sb.chmod(0o755)
            (BIN_DIR / "sb.tgz").unlink(missing_ok=True)
            await log("init", f"sing-box {SINGBOX_VER} installed")
        except Exception as e:
            await log("init", f"sing-box download failed: {e}", "WARN")
    out["xray"] = str(xray) if xray.exists() else shutil.which("xray")
    out["singbox"] = str(sb) if sb.exists() else shutil.which("sing-box")
    return out


async def _download(url: str, dest: Path):
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=180)) as r:
            r.raise_for_status()
            dest.write_bytes(await r.read())


# ---------------------------------------------------------------- Iran heuristics
IR_BLOCKED_SNI = re.compile(r"(speedtest\.net|\.ir$|instagram|facebook|youtube|twitter|telegram|t\.me)", re.I)
IR_PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "0.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16")]
# ports commonly throttled/blocked in Iran for plain traffic; heuristic penalty only
IR_SUSPECT_PORTS = {25, 110, 135, 137, 138, 139, 445, 1080, 3128, 8388, 1194, 51820}


def iran_prefilter(row) -> tuple[bool, str]:
    host = (row["host"] or "").lower()
    try:
        ip = ipaddress.ip_address(host)
        if any(ip in n for n in IR_PRIVATE) or ip.is_multicast or ip.is_reserved:
            return False, "private ip"
    except ValueError:
        if host.endswith(".ir"):
            return False, ".ir host"
    return True, ""


# ---------------------------------------------------------------- stage 3: TCP
async def tcp_ping(host: str, port: int, timeout: float) -> float | None:
    t0 = time.perf_counter()
    try:
        fut = asyncio.open_connection(host, port)
        r, w = await asyncio.wait_for(fut, timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return ms
    except Exception:
        return None


async def stage_tcp(db: DB, log, run_id: int) -> tuple[int, int, list]:
    limit = int(db.setting("max_tcp_test", 6000))
    conc = int(db.setting("tcp_concurrency", 300))
    timeout = float(db.setting("tcp_timeout", 4.0))
    rows = await db.configs_for_tcp(limit)
    await log("tcp", f"TCP testing {len(rows)} configs ({conc} threads, {timeout}s timeout)")
    sem = asyncio.Semaphore(conc)
    ok_rows: list[tuple] = []
    tests: list[tuple] = []
    updates: list[tuple[str, dict]] = []
    done = 0
    now = time.time()
    use_ir = bool(db.setting("iran_filter", True))

    async def one(r):
        nonlocal done
        if use_ir:
            okf, why = iran_prefilter(r)
            if not okf:
                updates.append((r["hash"], {"status": "dead", "fail_tests": 1}))
                tests.append((r["hash"], run_id, "tcp", now, None, None, None, None, 0, why))
                done += 1
                return
        async with sem:
            ms = await tcp_ping(r["host"], r["port"], timeout)
            if ms is None:  # one retry for flaky paths
                ms = await tcp_ping(r["host"], r["port"], timeout)
        done += 1
        if ms is None:
            updates.append((r["hash"], {"status": "dead", "tcp_ms": None}))
            tests.append((r["hash"], run_id, "tcp", now, None, None, None, None, 0, "timeout"))
        else:
            ok_rows.append((r, ms))
            updates.append((r["hash"], {"status": "tcp_ok", "tcp_ms": round(ms, 1)}))
            tests.append((r["hash"], run_id, "tcp", now, round(ms, 1), None, None, None, 1, None))
        if done % 500 == 0:
            await log("tcp", f"{done}/{len(rows)} · ok {len(ok_rows)}")

    await asyncio.gather(*(one(r) for r in rows))
    await db.bulk_update_results(updates)
    await db.record_tests(tests)
    # SQL-side increments of counters
    await db.execute("UPDATE configs SET fail_tests=fail_tests+1 WHERE status='dead' AND last_test>=?", (now - 1,))
    await log("tcp", f"done: {len(ok_rows)}/{len(rows)} reachable")
    await db.update_run(run_id, tcp_tested=len(rows), tcp_ok=len(ok_rows))
    ok_rows.sort(key=lambda x: x[1])
    return len(rows), len(ok_rows), ok_rows


# ---------------------------------------------------------------- stage 4: speed
_PORT_BASE = 20000
_port_lock = asyncio.Lock()
_free_ports: list[int] = []


def _pick_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


DL_URLS = ["https://speed.cloudflare.com/__down?bytes={n}", "https://cachefly.cachefly.net/10mb.test"]
UL_URL = "https://speed.cloudflare.com/__up"
LAT_URL = "https://www.gstatic.com/generate_204"


async def _wait_port(port: int, timeout: float = 12.0, proc=None) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc is not None and proc.returncode is not None:
            return False  # core exited (bad config)
        try:
            r, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 0.5)
            w.close()
            return True
        except Exception:
            await asyncio.sleep(0.15)
    return False


async def speed_one(link: str, protocol: str, security: str, bins: dict, settings: dict) -> dict:
    """Spin up a core, measure latency/download/upload through the local HTTP proxy."""
    res = {"ok": False, "http_ms": None, "dl_kbps": None, "ul_kbps": None, "error": None}
    engine = engine_for(protocol, security)
    exe = bins.get("xray") if engine == "xray" else bins.get("singbox") if engine == "singbox" else None
    if not exe:
        res["error"] = f"no engine for {protocol}"
        return res
    port = _pick_port()
    cfg = xray_config(link, port) if engine == "xray" else singbox_config(link, port)
    if not cfg:
        res["error"] = "unsupported link"
        return res
    tmp = DATA_DIR / "tmp"
    tmp.mkdir(exist_ok=True)
    cfg_path = tmp / f"cfg_{port}.json"
    cfg_path.write_text(json.dumps(cfg))
    args = [exe, "run", "-c", str(cfg_path)] if engine == "xray" else [exe, "run", "-c", str(cfg_path)]
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                                                env={**os.environ, "XRAY_LOCATION_ASSET": str(BIN_DIR)})
    try:
        if not await _wait_port(port, proc=proc):
            res["error"] = "core did not start" if proc.returncode is None else "invalid config (core exited)"
            return res
        proxy = f"http://127.0.0.1:{port}"
        tmo = aiohttp.ClientTimeout(total=float(settings["speed_timeout"]))
        async with aiohttp.ClientSession(timeout=tmo) as s:
            # latency (2 tries, best)
            best = None
            for _ in range(2):
                t0 = time.perf_counter()
                try:
                    async with s.get(LAT_URL, proxy=proxy, ssl=False, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        await r.read()
                        if r.status in (204, 200):
                            ms = (time.perf_counter() - t0) * 1000
                            best = ms if best is None else min(best, ms)
                except aiohttp.ClientHttpProxyError as e:
                    res["error"] = f"proxy refused ({e.status})"   # core up, remote handshake failed
                except aiohttp.ClientConnectorError as e:
                    res["error"] = "remote unreachable via core"
                except asyncio.TimeoutError:
                    res["error"] = "latency timeout"
                except Exception as e:
                    res["error"] = f"latency: {type(e).__name__}"
            if best is None:
                return res
            res["http_ms"] = round(best, 1)
            # download
            n = int(settings["speed_download_bytes"])
            try:
                t0 = time.perf_counter()
                got = 0
                async with s.get(DL_URLS[0].format(n=n), proxy=proxy, ssl=False) as r:
                    async for chunk in r.content.iter_chunked(65536):
                        got += len(chunk)
                        if time.perf_counter() - t0 > settings["speed_timeout"] * 0.6:
                            break
                dt = max(time.perf_counter() - t0, 0.05)
                res["dl_kbps"] = round(got * 8 / dt / 1000, 1)
            except Exception as e:
                res["error"] = f"download: {type(e).__name__}"
                res["dl_kbps"] = 0.0
            # upload
            n = int(settings["speed_upload_bytes"])
            try:
                payload = os.urandom(min(n, 2_000_000))
                t0 = time.perf_counter()
                async with s.post(UL_URL, data=payload, proxy=proxy, ssl=False) as r:
                    await r.read()
                dt = max(time.perf_counter() - t0, 0.05)
                res["ul_kbps"] = round(len(payload) * 8 / dt / 1000, 1)
            except Exception as e:
                res["ul_kbps"] = 0.0
                res["error"] = (res["error"] or "") + f" upload: {type(e).__name__}"
            res["ok"] = (res["dl_kbps"] or 0) > 50  # at least 50 kbps real throughput
    finally:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        cfg_path.unlink(missing_ok=True)
    return res


def score_of(tcp_ms: float | None, http_ms: float | None, dl: float | None, ul: float | None, ok_tests: int, fail_tests: int) -> float:
    """0..100. Download weighs most, then latency, then upload, then stability."""
    dl = dl or 0.0
    ul = ul or 0.0
    lat = http_ms or tcp_ms or 3000
    s_dl = min(math.log10(dl + 1) / math.log10(50_001), 1.0) * 45         # 50 Mbps -> full
    s_ul = min(math.log10(ul + 1) / math.log10(20_001), 1.0) * 15
    s_lat = max(0.0, 1 - (lat / 1500)) * 30
    total = ok_tests + fail_tests
    s_stab = (ok_tests / total if total else 0.5) * 10
    return round(s_dl + s_ul + s_lat + s_stab, 2)


async def stage_speed(db: DB, log, run_id: int, candidates: list, bins: dict) -> int:
    maxn = int(db.setting("max_speedtest", 150))
    conc = int(db.setting("speed_concurrency", 8))
    settings = {k: db.setting(k) for k in ("speed_timeout", "speed_download_bytes", "speed_upload_bytes")}
    # Selection: (1) previously-alive configs first (keep them fresh), (2) the rest by TCP ping but with host diversity —
    # at most 3 per host and 12 per /24 — so a wall of CDN anycast IPs (Cloudflare/Fastly) can't crowd out real servers.
    prev_alive = {r["hash"] for r in await db.fetchall("SELECT hash FROM configs WHERE status='alive' OR ok_tests>0")}
    recently_failed = {r["hash"] for r in await db.fetchall(
        "SELECT DISTINCT hash FROM tests WHERE stage='speed' AND ok=0 AND ts>?", (time.time() - 24 * 3600,))}
    first = [c for c in candidates if c[0]["hash"] in prev_alive]
    # bucket by 40ms so we rotate inside a tier instead of always hitting the same 1ms anycast IPs
    import random
    pool = [c for c in candidates if c[0]["hash"] not in prev_alive]
    random.shuffle(pool)
    pool.sort(key=lambda c: (c[0]["hash"] in recently_failed, int(c[1] // 40)))
    rest, per_host, per_net = [], {}, {}
    for c in pool:
        host = c[0]["host"]
        net = ".".join(host.split(".")[:3]) if host.replace(".", "").isdigit() else host
        if per_host.get(host, 0) >= 3 or per_net.get(net, 0) >= 12:
            continue
        per_host[host] = per_host.get(host, 0) + 1
        per_net[net] = per_net.get(net, 0) + 1
        rest.append(c)
    cand = (first + rest)[:maxn]
    await log("speed", f"speed-testing {len(cand)} configs via xray/sing-box ({conc} parallel)")
    sem = asyncio.Semaphore(conc)
    now = time.time()
    alive = 0
    done = 0
    tests, updates = [], []

    async def one(row, tcp_ms):
        nonlocal alive, done
        full = await db.fetchone("SELECT security, ok_tests, fail_tests FROM configs WHERE hash=?", (row["hash"],))
        async with sem:
            r = await speed_one(row["link"], row["protocol"], full["security"] or "", bins, settings)
        done += 1
        if r["ok"]:
            alive += 1
            okc, failc = full["ok_tests"] + 1, full["fail_tests"]
            updates.append((row["hash"], {"status": "alive", "http_ms": r["http_ms"], "dl_kbps": r["dl_kbps"], "ul_kbps": r["ul_kbps"],
                                          "ok_tests": okc, "score": score_of(tcp_ms, r["http_ms"], r["dl_kbps"], r["ul_kbps"], okc, failc)}))
        else:
            okc, failc = full["ok_tests"], full["fail_tests"] + 1
            updates.append((row["hash"], {"status": "tcp_ok", "fail_tests": failc, "dl_kbps": r["dl_kbps"], "ul_kbps": r["ul_kbps"],
                                          "score": score_of(tcp_ms, None, 0, 0, okc, failc) * 0.3}))
        tests.append((row["hash"], run_id, "speed", now, round(tcp_ms, 1), r["http_ms"], r["dl_kbps"], r["ul_kbps"], int(r["ok"]), r["error"]))
        if done % 10 == 0 or done == len(cand):
            await log("speed", f"{done}/{len(cand)} · alive {alive}")

    await asyncio.gather(*(one(r, ms) for r, ms in cand))
    await db.bulk_update_results(updates)
    await db.record_tests(tests)
    await db.update_run(run_id, speed_tested=len(cand), alive=alive)
    return alive


# ---------------------------------------------------------------- geo
async def stage_geo(db: DB, log):
    rows = await db.fetchall("SELECT hash, host FROM configs WHERE status IN ('alive','tcp_ok') AND country IN ('', '??') "
                             "ORDER BY CASE status WHEN 'alive' THEN 0 ELSE 1 END, tcp_ms LIMIT 600")
    if not rows:
        return
    hosts = sorted({r["host"] for r in rows})
    # resolve hostnames
    loop = asyncio.get_running_loop()

    async def resolve(h):
        try:
            ipaddress.ip_address(h)
            return h, h
        except ValueError:
            try:
                inf = await asyncio.wait_for(loop.getaddrinfo(h, None, family=socket.AF_INET), 4)
                return h, inf[0][4][0]
            except Exception:
                return h, None

    res = dict(await asyncio.gather(*(resolve(h) for h in hosts)))
    ips = sorted({ip for ip in res.values() if ip})
    geo: dict[str, str] = {}
    async with aiohttp.ClientSession() as s:
        for i in range(0, len(ips), 100):
            chunk = ips[i:i + 100]
            try:
                async with s.post("http://ip-api.com/batch?fields=query,countryCode", json=chunk,
                                  timeout=aiohttp.ClientTimeout(total=15)) as r:
                    for item in await r.json():
                        geo[item.get("query")] = item.get("countryCode") or ""
            except Exception as e:
                await log("geo", f"ip-api failed: {e}", "WARN")
                break
            await asyncio.sleep(1.5)  # 15 req/min limit on batch endpoint
    drop_ir = bool(db.setting("drop_ir_servers", True))
    upd = []
    for r in rows:
        ip = res.get(r["host"])
        cc = geo.get(ip, "") if ip else ""
        f = {"country": cc or "??", "ip": ip or ""}
        if drop_ir and cc == "IR":
            f["status"] = "dead"
        upd.append((r["hash"], f))
    await db.bulk_update_results(upd)
    await log("geo", f"geo-tagged {len(upd)} configs")


# ---------------------------------------------------------------- stage 5
async def stage_filter(db: DB, log):
    min_score = float(db.setting("min_score_keep", 0))
    # demote alive configs that failed 3 times in a row recently
    await db.execute("UPDATE configs SET status='tcp_ok' WHERE status='alive' AND fail_tests>ok_tests*2 AND fail_tests>=3")
    if min_score > 0:
        await db.execute("UPDATE configs SET status='tcp_ok' WHERE status='alive' AND score<?", (min_score,))
    pruned = await db.prune_dead(14)
    st = await db.config_stats()
    await log("filter", f"alive {st['alive']} · tcp_ok {st['tcp_ok']} · dead {st['dead']} · pruned {pruned}")
    return st
