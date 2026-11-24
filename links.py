"""Разбор ключей vless:// vmess:// trojan:// ss:// и подписок."""
from __future__ import annotations

import base64
import json
import re
import urllib.parse as up
import urllib.request

SCHEMES = ("vless", "vmess", "trojan", "ss")
USER_AGENT = "v2rayN/7.0"  # многие панели отдают base64-список именно под этот UA


class LinkError(ValueError):
    pass


def b64decode(data: str) -> str:
    s = re.sub(r"\s+", "", data).replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8")


def _q(params: dict, key: str, default: str = "") -> str:
    v = params.get(key)
    return v[0] if v and v[0] != "" else default


def _split(link: str):
    u = up.urlsplit(link)
    if not u.hostname:
        raise LinkError("нет адреса сервера")
    try:
        port = u.port
    except ValueError:
        raise LinkError("неверный порт")
    if not port:
        raise LinkError("не указан порт")
    params = up.parse_qs(u.query, keep_blank_values=True)
    name = up.unquote(u.fragment) or f"{u.hostname}:{port}"
    return u, port, params, name


def _transport(p: dict, default_security: str = "none") -> dict:
    return {
        "network": _q(p, "type", "tcp"),
        "security": _q(p, "security", default_security),
        "sni": _q(p, "sni") or _q(p, "peer"),
        "fp": _q(p, "fp"),
        "alpn": _q(p, "alpn"),
        "pbk": _q(p, "pbk"),
        "sid": _q(p, "sid"),
        "spx": _q(p, "spx"),
        "path": _q(p, "path"),
        "host": _q(p, "host"),
        "service_name": _q(p, "serviceName"),
        "mode": _q(p, "mode"),
        "header_type": _q(p, "headerType"),
        "allow_insecure": _q(p, "allowInsecure", _q(p, "insecure")) in ("1", "true"),
    }


def _parse_vless(link: str) -> dict:
    u, port, p, name = _split(link)
    uid = up.unquote(u.username or "")
    if not uid:
        raise LinkError("нет UUID")
    return {
        "protocol": "vless", "name": name, "address": u.hostname, "port": port,
        "id": uid, "flow": _q(p, "flow"), "encryption": _q(p, "encryption", "none"),
        **_transport(p),
    }


def _parse_trojan(link: str) -> dict:
    u, port, p, name = _split(link)
    pwd = up.unquote(u.username or "")
    if not pwd:
        raise LinkError("нет пароля")
    return {
        "protocol": "trojan", "name": name, "address": u.hostname, "port": port,
        "password": pwd, "flow": _q(p, "flow"),
        **_transport(p, default_security="tls"),
    }


def _parse_vmess(link: str) -> dict:
    body = link[len("vmess://"):].split("#")[0]
    try:
        j = json.loads(b64decode(body))
    except Exception:
        # Встречается и URL-форма vmess://uuid@host:port?...
        u, port, p, name = _split(link)
        return {
            "protocol": "vmess", "name": name, "address": u.hostname, "port": port,
            "id": up.unquote(u.username or ""), "alter_id": 0,
            "cipher": _q(p, "encryption", "auto"), **_transport(p),
        }
    net = j.get("net") or "tcp"
    sec = j.get("tls") or "none"
    if sec not in ("tls", "reality"):
        sec = "none"
    try:
        port = int(j["port"])
        address = j["add"]
        uid = j["id"]
    except (KeyError, ValueError):
        raise LinkError("в vmess нет адреса, порта или id")
    return {
        "protocol": "vmess", "name": j.get("ps") or f"{address}:{port}",
        "address": address, "port": port, "id": uid,
        "alter_id": int(j.get("aid") or 0), "cipher": j.get("scy") or "auto",
        "network": net, "security": sec,
        "sni": j.get("sni") or "", "fp": j.get("fp") or "", "alpn": j.get("alpn") or "",
        "pbk": j.get("pbk") or "", "sid": j.get("sid") or "", "spx": j.get("spx") or "",
        "path": j.get("path") or "", "host": j.get("host") or "",
        "service_name": (j.get("path") or "") if net == "grpc" else "",
        "mode": j.get("type") if net in ("grpc", "xhttp") else "",
        "header_type": (j.get("type") or "") if net == "tcp" else "",
        "allow_insecure": str(j.get("allowInsecure", "")).lower() in ("1", "true"),
    }


def _parse_ss(link: str) -> dict:
    body, _, frag = link[len("ss://"):].partition("#")
    body, _, query = body.partition("?")
    body = body.rstrip("/")
    if "plugin" in up.parse_qs(query):
        raise LinkError("ss с плагином (obfs/v2ray-plugin) не поддерживается")
    if "@" in body:  # SIP002: ss://base64(method:pass)@host:port
        userinfo, _, hostport = body.rpartition("@")
        userinfo = up.unquote(userinfo)
        if ":" not in userinfo:
            userinfo = b64decode(userinfo)
    else:  # старый формат: ss://base64(method:pass@host:port)
        try:
            decoded = b64decode(body)
        except Exception:
            raise LinkError("не удалось декодировать ss")
        userinfo, _, hostport = decoded.rpartition("@")
    method, _, password = userinfo.partition(":")
    hp = up.urlsplit("//" + hostport)
    try:
        port = hp.port
    except ValueError:
        port = None
    if not (method and password and hp.hostname and port):
        raise LinkError("неполный ss-ключ")
    return {
        "protocol": "shadowsocks", "name": up.unquote(frag) or f"{hp.hostname}:{port}",
        "address": hp.hostname, "port": port, "method": method, "password": password,
        "network": "tcp", "security": "none",
    }


def parse_link(link: str) -> dict:
    link = link.strip()
    scheme = link.split("://", 1)[0].lower()
    parser = {"vless": _parse_vless, "vmess": _parse_vmess,
              "trojan": _parse_trojan, "ss": _parse_ss}.get(scheme)
    if not parser:
        raise LinkError(f"протокол «{scheme}» не поддерживается")
    server = parser(link)
    server["link"] = link
    return server


def parse_many(text: str) -> tuple[list[dict], list[str]]:
    """Список ключей построчно или base64-блоком (как в подписках)."""
    text = text.strip()
    if "://" not in text:
        try:
            text = b64decode(text)
        except Exception:
            pass
    servers, errors = [], []
    for line in text.splitlines():
        line = line.strip()
        if "://" not in line:
            continue
        try:
            servers.append(parse_link(line))
        except LinkError as e:
            errors.append(f"{line[:50]}… — {e}")
        except Exception as e:  # битая строка не должна ронять весь импорт
            errors.append(f"{line[:50]}… — ошибка разбора: {e}")
    return servers, errors


def fetch_text(url: str, proxy_port: int | None = None, timeout: int = 15) -> str:
    handler = urllib.request.ProxyHandler(
        {"http": f"http://127.0.0.1:{proxy_port}", "https": f"http://127.0.0.1:{proxy_port}"}
        if proxy_port else {}
    )
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_subscription(url: str, proxy_port: int | None = None) -> tuple[list[dict], list[str]]:
    """Сначала напрямую; если не вышло и есть активный прокси — через него."""
    try:
        text = fetch_text(url)
    except Exception:
        if not proxy_port:
            raise
        text = fetch_text(url, proxy_port)
    servers, errors = parse_many(text)
    if not servers and not errors:
        raise LinkError("в подписке нет ключей (возможно, формат Clash/sing-box)")
    return servers, errors
