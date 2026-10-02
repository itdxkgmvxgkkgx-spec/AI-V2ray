"""Parse proxy share-links of all supported protocols into a normalized dict and a dedup hash.

Supported: vmess, vless, trojan, ss, ssr, hysteria2/hy2, hysteria, tuic, wireguard, socks, http.
Dedup: hash(protocol + host + port + user/password + core transport params) -> remark/ordering ignored.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

PROTOCOLS = ("vmess", "vless", "trojan", "ss", "ssr", "hysteria2", "hy2", "hysteria", "tuic", "wireguard", "wg", "socks", "socks5", "http", "https")

LINK_RE = re.compile(
    r"(?:vmess|vless|trojan|ss|ssr|hysteria2|hy2|hysteria|tuic|wireguard|wg|socks5?)://[^\s\"'<>`\\]+",
    re.IGNORECASE,
)
_B64_CLEAN = re.compile(r"[^A-Za-z0-9+/=_-]")
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-_:\[\]]+$")
SS_METHODS = {"aes-128-gcm", "aes-192-gcm", "aes-256-gcm", "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
              "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm", "2022-blake3-chacha20-poly1305",
              "aes-128-cfb", "aes-192-cfb", "aes-256-cfb", "aes-128-ctr", "aes-192-ctr", "aes-256-ctr", "chacha20-ietf",
              "chacha20", "rc4-md5", "none", "plain", "aes-256-cfb8"}


def b64decode(s: str) -> bytes | None:
    s = s.strip()
    if not s:
        return None
    s = _B64_CLEAN.sub("", s)
    s = s.replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    try:
        return base64.b64decode(s + "=" * pad, validate=False)
    except (binascii.Error, ValueError):
        return None


def looks_base64_blob(text: str) -> bool:
    t = text.strip()
    if len(t) < 16 or "://" in t[:200]:
        return False
    sample = t[:4000]
    return bool(re.fullmatch(r"[A-Za-z0-9+/=_\-\s]+", sample))


def extract_links(text: str) -> list[str]:
    """Pull every share link out of arbitrary text (plain, base64 blob, HTML...)."""
    if not text:
        return []
    out: list[str] = []
    # Direct
    out.extend(m.group(0) for m in LINK_RE.finditer(text))
    # Whole document base64?
    if not out and looks_base64_blob(text):
        dec = b64decode(text)
        if dec:
            try:
                out.extend(m.group(0) for m in LINK_RE.finditer(dec.decode("utf-8", "ignore")))
            except Exception:
                pass
    # Line-wise base64 (some lists mix)
    if len(out) < 3:
        for line in text.splitlines():
            line = line.strip()
            if 24 < len(line) < 20000 and "://" not in line and looks_base64_blob(line):
                dec = b64decode(line)
                if dec:
                    out.extend(m.group(0) for m in LINK_RE.finditer(dec.decode("utf-8", "ignore")))
    # HTML-escaped ampersands
    out = [l.replace("&amp;", "&").rstrip(".,;)") for l in out]
    return out


def _clean_host(h: str | None) -> str:
    h = (h or "").strip().strip("[]")
    return h if _HOST_RE.match(h or "x") else ""


def _h(*parts) -> str:
    return hashlib.sha1("|".join(str(p).lower() for p in parts).encode()).hexdigest()[:24]


def parse_link(link: str) -> dict | None:
    link = link.strip()
    try:
        scheme = link.split("://", 1)[0].lower()
    except Exception:
        return None
    try:
        if scheme == "vmess":
            return _parse_vmess(link)
        if scheme in ("vless", "trojan", "hysteria2", "hy2", "hysteria", "tuic", "socks", "socks5", "http", "https"):
            return _parse_url_like(link, scheme)
        if scheme == "ss":
            return _parse_ss(link)
        if scheme == "ssr":
            return _parse_ssr(link)
        if scheme in ("wireguard", "wg"):
            return _parse_url_like(link, "wireguard")
    except Exception:
        return None
    return None


def _parse_vmess(link: str) -> dict | None:
    body = link[len("vmess://"):]
    dec = b64decode(body.split("#", 1)[0])
    if not dec:
        return None
    try:
        j = json.loads(dec.decode("utf-8", "ignore"))
    except json.JSONDecodeError:
        return None
    if not isinstance(j, dict):
        return None
    host = _clean_host(str(j.get("add", "")))
    try:
        port = int(str(j.get("port", "0")).strip() or 0)
    except ValueError:
        return None
    uid = str(j.get("id", ""))
    if not host or not port or not uid:
        return None
    net = str(j.get("net", "tcp") or "tcp")
    tls = str(j.get("tls", "") or "")
    path = str(j.get("path", "") or "")
    hhost = str(j.get("host", "") or "")
    sni = str(j.get("sni", "") or hhost)
    # Rebuild a normalized vmess JSON (drop remark) for a stable link
    j.setdefault("v", "2")
    return {
        "protocol": "vmess", "host": host, "port": port, "remark": str(j.get("ps", ""))[:80],
        "network": net, "security": tls or "none", "sni": sni,
        "hash": _h("vmess", host, port, uid, net, path, hhost, tls),
        "link": link,
    }


def _parse_url_like(link: str, scheme: str) -> dict | None:
    u = urlparse(link)
    host = _clean_host(u.hostname)
    port = u.port
    if not host or not port:
        # hysteria/tuic may use host:port,port ranges
        m = re.match(r"^[^:]+://(?:[^@]+@)?(\[[^\]]+\]|[^:/?#]+):(\d+)", link)
        if not m:
            return None
        host, port = _clean_host(m.group(1)), int(m.group(2))
    if not host:
        return None
    user = unquote(u.username or "")
    if u.password:
        user = f"{user}:{unquote(u.password)}"
    q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
    net = q.get("type", q.get("network", "tcp" if scheme in ("vless", "trojan") else scheme))
    sec = q.get("security", "tls" if scheme in ("trojan", "hysteria2", "hy2", "hysteria", "tuic") else "none")
    sni = q.get("sni", q.get("peer", q.get("host", "")))
    proto = {"hy2": "hysteria2", "socks5": "socks", "https": "http"}.get(scheme, scheme)
    core = [proto, host, port, user, net, sec, q.get("path", ""), q.get("host", ""), q.get("pbk", ""),
            q.get("serviceName", ""), q.get("flow", ""), q.get("sid", ""), q.get("obfs-password", q.get("password", ""))]
    return {
        "protocol": proto, "host": host, "port": int(port), "remark": unquote(u.fragment or "")[:80],
        "network": net, "security": sec, "sni": sni, "hash": _h(*core), "link": link,
    }


def _parse_ss(link: str) -> dict | None:
    body = link[len("ss://"):]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    body = body.split("?", 1)[0]
    if "@" in body:
        userinfo, hostport = body.rsplit("@", 1)
        if ":" not in userinfo:
            dec = b64decode(userinfo)
            userinfo = dec.decode("utf-8", "ignore") if dec else userinfo
        else:
            userinfo = unquote(userinfo)
    else:
        dec = b64decode(body)
        if not dec:
            return None
        txt = dec.decode("utf-8", "ignore")
        if "@" not in txt:
            return None
        userinfo, hostport = txt.rsplit("@", 1)
    if ":" not in userinfo:
        return None
    method, password = userinfo.split(":", 1)
    if method.lower() not in SS_METHODS or not password or not password.isprintable():
        return None
    hostport = hostport.rstrip("/")
    m = re.match(r"^(\[[^\]]+\]|[^:]+):(\d+)$", hostport)
    if not m:
        return None
    host, port = _clean_host(m.group(1)), int(m.group(2))
    if not host:
        return None
    return {"protocol": "ss", "host": host, "port": port, "remark": unquote(frag)[:80], "network": "tcp",
            "security": method, "sni": "", "hash": _h("ss", host, port, method, password), "link": link}


def _parse_ssr(link: str) -> dict | None:
    dec = b64decode(link[len("ssr://"):])
    if not dec:
        return None
    txt = dec.decode("utf-8", "ignore")
    main = txt.split("/?", 1)[0]
    parts = main.split(":")
    if len(parts) < 6:
        return None
    host, port, proto, method, obfs, pwd_b64 = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
    host = _clean_host(host)
    if not host or not port.isdigit():
        return None
    return {"protocol": "ssr", "host": host, "port": int(port), "remark": "", "network": proto, "security": method,
            "sni": obfs, "hash": _h("ssr", host, port, proto, method, obfs, pwd_b64), "link": link}


def parse_many(links: list[str], source_id: int | None = None) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for l in links:
        p = parse_link(l)
        if not p or p["hash"] in seen:
            continue
        if p["port"] <= 0 or p["port"] > 65535:
            continue
        seen.add(p["hash"])
        p["source_id"] = source_id
        out.append(p)
    return out
