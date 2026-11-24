"""Сборка конфига Xray, загрузка ядра, запуск и тест задержки."""
from __future__ import annotations

import copy
import json
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from storage import data_dir

IS_WIN = platform.system() == "Windows"
EXE = "xray.exe" if IS_WIN else "xray"
NO_WINDOW = 0x08000000 if IS_WIN else 0
SUPPORTED_NETS = {"tcp", "raw", "ws", "grpc", "httpupgrade", "xhttp", "splithttp"}
TEST_URL = "http://www.gstatic.com/generate_204"
# «+local» — запросы к DoH идут напрямую, а не через сам VPN; последний — системный DNS как запасной
DOH_SERVERS = ["https+local://1.1.1.1/dns-query", "https+local://8.8.8.8/dns-query",
               "https+local://9.9.9.9/dns-query", "localhost"]


# ---------- конфиг ----------

def _stream_settings(s: dict) -> dict:
    net = (s.get("network") or "tcp").lower()
    if net == "splithttp":
        net = "xhttp"
    if net not in SUPPORTED_NETS:
        raise ValueError(f"транспорт «{net}» не поддерживается этой версией клиента")
    sec = (s.get("security") or "none").lower()
    st: dict = {"network": net, "security": sec}
    alpn = [a.strip() for a in (s.get("alpn") or "").split(",") if a.strip()]

    if net in ("ws", "httpupgrade"):
        alpn = ["http/1.1"]  # WebSocket работает только поверх HTTP/1.1, иначе CDN может выбрать h2
    if sec == "tls":
        tls = {"serverName": s.get("sni") or s.get("host") or s["address"],
               "fingerprint": s.get("fp") or "chrome"}
        if alpn:
            tls["alpn"] = alpn
        # allowInsecure удалён в Xray 26 — с ним ядро не стартует, поэтому не передаём
        if s.get("pcs"):
            tls["pinnedPeerCertSha256"] = s["pcs"]
        if s.get("vcn"):
            tls["verifyPeerCertByName"] = s["vcn"]
        st["tlsSettings"] = tls
    elif sec == "reality":
        if not s.get("pbk"):
            raise ValueError("для REALITY нужен публичный ключ (pbk)")
        st["realitySettings"] = {
            "serverName": s.get("sni") or "",
            "fingerprint": s.get("fp") or "chrome",
            "publicKey": s["pbk"],
            "shortId": s.get("sid") or "",
            "spiderX": s.get("spx") or "",
        }
        if s.get("pqv"):
            st["realitySettings"]["mldsa65Verify"] = s["pqv"]
    elif sec != "none":
        st["security"] = "none"

    path, host = s.get("path") or "/", s.get("host") or ""
    if net == "ws":
        st["wsSettings"] = {"path": path, **({"host": host} if host else {})}
    elif net == "grpc":
        st["grpcSettings"] = {"serviceName": s.get("service_name") or s.get("path") or "",
                              "multiMode": s.get("mode") == "multi"}
    elif net == "httpupgrade":
        st["httpupgradeSettings"] = {"path": path, **({"host": host} if host else {})}
    elif net == "xhttp":
        st["xhttpSettings"] = {"path": path, "mode": s.get("mode") or "auto",
                               **({"host": host} if host else {})}
        if s.get("extra"):
            try:
                st["xhttpSettings"]["extra"] = json.loads(s["extra"])
            except ValueError:
                pass
    elif net in ("tcp", "raw") and s.get("header_type") == "http":
        st["tcpSettings"] = {"header": {"type": "http", "request": {
            "path": [path],
            "headers": {"Host": [h.strip() for h in host.split(",") if h.strip()]},
        }}}
    return st


def build_outbound(s: dict) -> dict:
    proto = s["protocol"]
    addr, port = s["address"], int(s["port"])
    if proto == "vless":
        user = {"id": s["id"], "encryption": s.get("encryption") or "none"}
        if s.get("flow"):
            user["flow"] = s["flow"]
        settings = {"vnext": [{"address": addr, "port": port, "users": [user]}]}
    elif proto == "vmess":
        settings = {"vnext": [{"address": addr, "port": port, "users": [{
            "id": s["id"], "alterId": int(s.get("alter_id") or 0),
            "security": s.get("cipher") or "auto"}]}]}
    elif proto == "trojan":
        srv = {"address": addr, "port": port, "password": s["password"]}
        if s.get("flow"):
            srv["flow"] = s["flow"]
        settings = {"servers": [srv]}
    elif proto == "shadowsocks":
        settings = {"servers": [{"address": addr, "port": port,
                                 "method": s["method"], "password": s["password"]}]}
    else:
        raise ValueError(f"неизвестный протокол {proto}")
    ob = {"tag": "proxy", "protocol": proto, "settings": settings,
          "streamSettings": _stream_settings(s)}
    if s.get("mux") and not s.get("flow"):  # mux несовместим с XTLS Vision
        try:
            conc = int(str(s.get("mux_concurrency") or 8).split("-")[0])
        except ValueError:
            conc = 8
        ob["mux"] = {"enabled": True, "concurrency": conc, "xudpConcurrency": conc,
                     "xudpProxyUDP443": "reject"}
    if s.get("fragment"):
        ob["streamSettings"].setdefault("sockopt", {})["dialerProxy"] = "fragment"
    return ob


def parse_fragment(value: str) -> dict:
    """«100-200,10-20,tlshello» → {"packets": "tlshello", "length": "100-200", "interval": "10-20"}."""
    parts = [x.strip() for x in value.split(",") if x.strip()]
    packets = next((x for x in parts if not x[0].isdigit()), "tlshello")
    nums = [x for x in parts if x[0].isdigit()]
    return {"packets": packets, "length": nums[0] if nums else "100-200",
            "interval": nums[1] if len(nums) > 1 else "10-20"}


def build_config(server: dict, socks_port: int | None = 10808, http_port: int | None = 10809,
                 bypass_ru: bool = False, loglevel: str = "warning") -> dict:
    sniff = {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": True}
    inbounds = []
    if socks_port:
        inbounds.append({"tag": "socks", "listen": "127.0.0.1", "port": socks_port,
                         "protocol": "socks", "settings": {"udp": True}, "sniffing": sniff})
    if http_port:
        inbounds.append({"tag": "http", "listen": "127.0.0.1", "port": http_port,
                         "protocol": "http", "sniffing": sniff})
    if server.get("outbounds"):  # сервер из JSON-подписки: берём его outbounds как есть
        outbounds = copy.deepcopy(server["outbounds"])
        main_tag = server.get("main_tag") or "proxy"
        for o in outbounds:
            if o.get("tag") == main_tag:
                o["tag"] = "proxy"
            sockopt = (o.get("streamSettings") or {}).get("sockopt") or {}
            if sockopt.get("dialerProxy") == main_tag:
                sockopt["dialerProxy"] = "proxy"
        outbounds.sort(key=lambda o: o.get("tag") != "proxy")
        tags = {o.get("tag") for o in outbounds}
        if "direct" not in tags:
            outbounds.append({"tag": "direct", "protocol": "freedom"})
        if "block" not in tags:
            outbounds.append({"tag": "block", "protocol": "blackhole"})
    else:
        outbounds = [build_outbound(server),
                     {"tag": "direct", "protocol": "freedom"},
                     {"tag": "block", "protocol": "blackhole"}]
        if server.get("fragment"):  # дробление TLS ClientHello против DPI
            outbounds.append({"tag": "fragment", "protocol": "freedom",
                              "settings": {"fragment": parse_fragment(server["fragment"])},
                              "streamSettings": {"sockopt": {"tcpNoDelay": True}}})
    # Адрес VPN-сервера узнаём через защищённый DNS (DoH) в обход DNS провайдера:
    # провайдеры подменяют ответы для доменов VPN-сервисов, и соединение сразу рвётся.
    for o in outbounds:
        if o.get("tag") == "proxy":
            o.setdefault("streamSettings", {}).setdefault("sockopt", {}).setdefault("domainStrategy", "UseIPv4")
        if o.get("tag") == "fragment":
            o.setdefault("settings", {}).setdefault("domainStrategy", "UseIPv4")
    rules = [{"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}]
    if bypass_ru:
        rules += [
            {"type": "field", "domain": ["geosite:category-ru", "domain:ru", "domain:su",
                                         "domain:xn--p1ai"], "outboundTag": "direct"},
            {"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"},
        ]
    return {
        "log": {"loglevel": loglevel},
        "dns": {"servers": DOH_SERVERS, "queryStrategy": "UseIPv4"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"domainStrategy": "IPIfNonMatch" if bypass_ru else "AsIs", "rules": rules},
    }


# ---------- ядро ----------

def _asset_name() -> str:
    system = platform.system()
    arm = platform.machine().lower() in ("arm64", "aarch64")
    suffix = "arm64-v8a" if arm else "64"
    os_name = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(system)
    if not os_name:
        raise RuntimeError(f"ОС {system} не поддерживается")
    return f"Xray-{os_name}-{suffix}.zip"


def app_dir() -> Path:
    """Папка с ресурсами: внутри собранного .exe/.app или рядом с исходниками."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def find_xray() -> Path | None:
    bundled = app_dir() / "xray" / EXE  # встроен в установщик
    if bundled.exists():
        return bundled
    local = data_dir() / "xray" / EXE   # скачан при первом запуске
    if local.exists():
        return local
    w = shutil.which("xray")
    return Path(w) if w else None


def ensure_xray(log=print) -> Path:
    found = find_xray()
    if found:
        return found
    asset = _asset_name()
    url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{asset}"
    dest = data_dir() / "xray"
    dest.mkdir(parents=True, exist_ok=True)
    zpath = dest / asset
    log(f"Скачиваю Xray-core: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "KeyConnect"})
    with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, -10
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            done += len(chunk)
            pct = done * 100 // total if total else 0
            if pct - last >= 10:
                log(f"  {pct}% ({done // 1024 // 1024} МБ)")
                last = pct
    with zipfile.ZipFile(zpath) as z:
        z.extractall(dest)
    zpath.unlink(missing_ok=True)
    exe = dest / EXE
    if not IS_WIN:
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    log("Xray-core установлен.")
    return exe


def _env(binary: Path) -> dict:
    env = os.environ.copy()
    env["XRAY_LOCATION_ASSET"] = str(binary.parent)  # geoip.dat / geosite.dat
    return env


def _wait_port(port: int, proc: subprocess.Popen, timeout: float = 6) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


class XrayProcess:
    def __init__(self, binary: Path, on_log=print):
        self.binary = binary
        self.on_log = on_log
        self.proc: subprocess.Popen | None = None
        self.cfg_path = data_dir() / "running-config.json"

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, config: dict, wait_port: int):
        self.stop()
        self.cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), "utf-8")
        self.proc = subprocess.Popen(
            [str(self.binary), "run", "-c", str(self.cfg_path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", env=_env(self.binary),
            cwd=str(self.binary.parent), creationflags=NO_WINDOW,
        )
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()
        if not _wait_port(wait_port, self.proc):
            self.stop()
            raise RuntimeError("Xray не запустился — подробности в логе")

    def _pump(self, proc: subprocess.Popen):
        for line in proc.stdout:
            self.on_log(line.rstrip())

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def http_delay(proxy_port: int, timeout: float = 8) -> int:
    handler = urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{proxy_port}",
                                           "https": f"http://127.0.0.1:{proxy_port}"})
    opener = urllib.request.build_opener(handler)
    t0 = time.perf_counter()
    with opener.open(TEST_URL, timeout=timeout) as r:
        r.read()
    return int((time.perf_counter() - t0) * 1000)


def url_test(binary: Path, server: dict, timeout: float = 8) -> int | None:
    """Реальная задержка: временный Xray на свободном порту + запрос generate_204."""
    port = free_port()
    cfg = build_config(server, socks_port=None, http_port=port, loglevel="none")
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    proc = subprocess.Popen([str(binary), "run", "-c", path], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env=_env(binary),
                            cwd=str(binary.parent), creationflags=NO_WINDOW)
    try:
        if not _wait_port(port, proc, 5):
            return None
        try:
            http_delay(port, timeout)  # первый запрос прогревает TLS-сессию
        except Exception:
            return None
        try:
            return http_delay(port, timeout)
        except Exception:
            return None
    finally:
        proc.kill()
        proc.wait()
        os.unlink(path)
