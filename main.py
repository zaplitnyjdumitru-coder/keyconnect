"""KeyConnect — подключалка VPN-ключей (vless / vmess / trojan / ss) на базе Xray-core.

Запуск с окном:      python main.py
Консольный режим:    python main.py "vless://..." [--sysproxy] [--ru-direct]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import links  # noqa: E402
import sysproxy  # noqa: E402
import xray  # noqa: E402


def cli(argv):
    ap = argparse.ArgumentParser(description="Подключение по VPN-ключу через Xray-core")
    ap.add_argument("link", help="ключ vless:// vmess:// trojan:// ss:// или ссылка на подписку")
    ap.add_argument("--socks", type=int, default=10808)
    ap.add_argument("--http", type=int, default=10809)
    ap.add_argument("--sysproxy", action="store_true", help="включить системный прокси")
    ap.add_argument("--ru-direct", action="store_true", help="российские сайты напрямую")
    ap.add_argument("-n", type=int, default=1, help="номер сервера в подписке (с 1)")
    a = ap.parse_args(argv)

    if a.link.startswith(("http://", "https://")):
        servers, _ = links.fetch_subscription(a.link)
        for i, s in enumerate(servers, 1):
            print(f"{i:>3}. {s['name']}")
        server = servers[a.n - 1]
    else:
        server = links.parse_link(a.link)
    print(f"Сервер: {server['name']} ({server['protocol']} {server['address']}:{server['port']})")

    binary = xray.ensure_xray()
    core = xray.XrayProcess(binary, print)
    core.start(xray.build_config(server, a.socks, a.http, a.ru_direct), a.http)
    try:
        print(f"Задержка: {xray.http_delay(a.http)} мс")
    except Exception as e:  # noqa: BLE001
        print(f"Проверка связи не прошла: {e}")
    if a.sysproxy:
        sysproxy.set_system_proxy(True, a.http, a.socks)
    print(f"Работает: SOCKS5 127.0.0.1:{a.socks}, HTTP 127.0.0.1:{a.http}. Ctrl+C — выход.")
    try:
        while core.running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if a.sysproxy:
            sysproxy.set_system_proxy(False, a.http, a.socks)
        core.stop()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cli(sys.argv[1:])
    else:
        import gui
        gui.run()
