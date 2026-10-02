"""Convert share links into xray-core / sing-box outbound JSON used by the speed tester."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, unquote, urlparse

from .parser import b64decode


def _q(link: str) -> tuple:
    u = urlparse(link)
    q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
    return u, q


def _stream(q: dict, host: str, default_sec: str = "none") -> dict:
    net = q.get("type", q.get("network", "tcp")) or "tcp"
    sec = q.get("security", default_sec) or default_sec
    st: dict = {"network": net, "security": sec}
    sni = q.get("sni") or q.get("host") or host
    if sec == "tls":
        st["tlsSettings"] = {"serverName": sni, "allowInsecure": q.get("allowInsecure", "0") in ("1", "true"),
                             "fingerprint": q.get("fp", "chrome")}
        if q.get("alpn"):
            st["tlsSettings"]["alpn"] = q["alpn"].split(",")
    elif sec == "reality":
        st["realitySettings"] = {"serverName": q.get("sni", ""), "fingerprint": q.get("fp", "chrome"),
                                 "publicKey": q.get("pbk", ""), "shortId": q.get("sid", ""), "spiderX": q.get("spx", "/")}
    if net == "ws":
        st["wsSettings"] = {"path": unquote(q.get("path", "/")), "headers": {"Host": q.get("host", sni)}}
    elif net == "grpc":
        st["grpcSettings"] = {"serviceName": q.get("serviceName", ""), "multiMode": q.get("mode") == "multi"}
    elif net in ("h2", "http"):
        st["network"] = "h2"
        st["httpSettings"] = {"path": unquote(q.get("path", "/")), "host": [q.get("host", sni)]}
    elif net == "httpupgrade":
        st["httpupgradeSettings"] = {"path": unquote(q.get("path", "/")), "host": q.get("host", sni)}
    elif net in ("xhttp", "splithttp"):
        st["network"] = "xhttp"
        st["xhttpSettings"] = {"path": unquote(q.get("path", "/")), "host": q.get("host", sni), "mode": q.get("mode", "auto")}
    elif net == "tcp" and q.get("headerType") == "http":
        st["tcpSettings"] = {"header": {"type": "http", "request": {"path": [unquote(q.get("path", "/"))],
                                                                   "headers": {"Host": [q.get("host", sni)]}}}}
    elif net == "kcp":
        st["kcpSettings"] = {"header": {"type": q.get("headerType", "none")}, "seed": q.get("seed", "")}
    return st


def _ss_parts(link: str) -> tuple[str, str, str, int]:
    body = link[5:].split("#")[0].split("?")[0]
    if "@" in body:
        ui, hp = body.rsplit("@", 1)
        ui = unquote(ui) if ":" in ui else b64decode(ui).decode("utf-8", "ignore")
    else:
        ui, hp = b64decode(body).decode("utf-8", "ignore").rsplit("@", 1)
    method, pwd = ui.split(":", 1)
    h, p = hp.rstrip("/").rsplit(":", 1)
    return method, pwd, h.strip("[]"), int(p)


def xray_outbound(link: str) -> dict | None:
    scheme = link.split("://", 1)[0].lower()
    try:
        if scheme == "vmess":
            j = json.loads(b64decode(link[8:].split("#")[0]).decode("utf-8", "ignore"))
            host, port = j["add"], int(j["port"])
            q = {"type": j.get("net", "tcp"), "security": j.get("tls", "") or "none", "path": j.get("path", ""),
                 "host": j.get("host", ""), "sni": j.get("sni", "") or j.get("host", ""), "headerType": j.get("type", "none"),
                 "serviceName": j.get("path", ""), "alpn": j.get("alpn", ""), "fp": j.get("fp", "chrome")}
            return {"protocol": "vmess", "tag": "proxy",
                    "settings": {"vnext": [{"address": host, "port": port, "users": [
                        {"id": j["id"], "alterId": int(j.get("aid", 0) or 0), "security": j.get("scy", "auto") or "auto"}]}]},
                    "streamSettings": _stream(q, host)}
        u, q = _q(link)
        host, port = u.hostname, u.port
        if scheme == "vless":
            user = {"id": unquote(u.username or ""), "encryption": q.get("encryption", "none") or "none"}
            if q.get("flow"):
                user["flow"] = q["flow"]
            return {"protocol": "vless", "tag": "proxy",
                    "settings": {"vnext": [{"address": host, "port": port, "users": [user]}]},
                    "streamSettings": _stream(q, host)}
        if scheme == "trojan":
            return {"protocol": "trojan", "tag": "proxy",
                    "settings": {"servers": [{"address": host, "port": port, "password": unquote(u.username or "")}]},
                    "streamSettings": _stream(q, host, default_sec="tls")}
        if scheme == "ss":
            method, pwd, h, p = _ss_parts(link)
            return {"protocol": "shadowsocks", "tag": "proxy",
                    "settings": {"servers": [{"address": h, "port": p, "method": method, "password": pwd}]}}
        if scheme in ("socks", "socks5"):
            s = {"address": host, "port": port}
            if u.username:
                s["users"] = [{"user": unquote(u.username), "pass": unquote(u.password or "")}]
            return {"protocol": "socks", "tag": "proxy", "settings": {"servers": [s]}}
    except Exception:
        return None
    return None


def xray_config(link: str, http_port: int) -> dict | None:
    ob = xray_outbound(link)
    if not ob:
        return None
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{"tag": "in", "listen": "127.0.0.1", "port": http_port, "protocol": "http",
                      "settings": {"allowTransparent": False}}],
        "outbounds": [ob, {"protocol": "freedom", "tag": "direct"}],
    }


def singbox_outbound(link: str) -> dict | None:
    scheme = link.split("://", 1)[0].lower()
    try:
        u, q = _q(link)
        host, port = u.hostname, u.port
        sni = q.get("sni") or q.get("peer") or host
        insecure = q.get("insecure", q.get("allowInsecure", "0")) in ("1", "true")
        if scheme in ("hysteria2", "hy2"):
            ob = {"type": "hysteria2", "tag": "proxy", "server": host, "server_port": port,
                  "password": unquote(u.username or ""), "tls": {"enabled": True, "server_name": sni, "insecure": insecure}}
            if q.get("obfs"):
                ob["obfs"] = {"type": q["obfs"], "password": q.get("obfs-password", "")}
            return ob
        if scheme == "hysteria":
            return {"type": "hysteria", "tag": "proxy", "server": host, "server_port": port,
                    "auth_str": q.get("auth", unquote(u.username or "")), "up_mbps": int(q.get("upmbps", 10)),
                    "down_mbps": int(q.get("downmbps", 50)), "obfs": q.get("obfsParam", ""),
                    "tls": {"enabled": True, "server_name": sni, "insecure": insecure, "alpn": q.get("alpn", "h3").split(",")}}
        if scheme == "tuic":
            return {"type": "tuic", "tag": "proxy", "server": host, "server_port": port,
                    "uuid": unquote(u.username or ""), "password": unquote(u.password or ""),
                    "congestion_control": q.get("congestion_control", "bbr"), "udp_relay_mode": q.get("udp_relay_mode", "native"),
                    "tls": {"enabled": True, "server_name": sni, "insecure": insecure, "alpn": q.get("alpn", "h3").split(",")}}
        if scheme == "ss":
            method, pwd, h, p = _ss_parts(link)
            return {"type": "shadowsocks", "tag": "proxy", "server": h, "server_port": p, "method": method, "password": pwd}
    except Exception:
        return None
    return None


def singbox_config(link: str, http_port: int) -> dict | None:
    ob = singbox_outbound(link)
    if not ob:
        return None
    return {
        "log": {"level": "panic"},
        "inbounds": [{"type": "http", "tag": "in", "listen": "127.0.0.1", "listen_port": http_port}],
        "outbounds": [ob, {"type": "direct", "tag": "direct"}],
    }


def engine_for(protocol: str, security: str = "") -> str | None:
    if protocol == "ss" and (security or "").lower().startswith("2022-"):
        return "singbox"
    if protocol in ("vmess", "vless", "trojan", "ss", "socks"):
        return "xray"
    if protocol in ("hysteria2", "hysteria", "tuic"):
        return "singbox"
    return None
