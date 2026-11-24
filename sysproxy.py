"""Включение/выключение системного прокси на Windows, macOS и Linux (GNOME/KDE)."""
from __future__ import annotations

import platform
import shutil
import subprocess

BYPASS = ["localhost", "127.*", "10.*", "172.16.*", "172.17.*", "172.18.*", "172.19.*",
          "172.2*", "172.30.*", "172.31.*", "192.168.*", "<local>"]


def _run(*cmd):
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _windows(enable: bool, http_port: int):
    import ctypes
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                         0, winreg.KEY_ALL_ACCESS)
    with key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1 if enable else 0)
        if enable:
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{http_port}")
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, ";".join(BYPASS))
    inet = ctypes.windll.wininet
    inet.InternetSetOptionW(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
    inet.InternetSetOptionW(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH


def _macos(enable: bool, http_port: int, socks_port: int):
    out = subprocess.run(["networksetup", "-listallnetworkservices"],
                         capture_output=True, text=True).stdout.splitlines()[1:]
    services = [s for s in out if s and not s.startswith("*")]
    state = "on" if enable else "off"
    for svc in services:
        if enable:
            _run("networksetup", "-setwebproxy", svc, "127.0.0.1", str(http_port))
            _run("networksetup", "-setsecurewebproxy", svc, "127.0.0.1", str(http_port))
            _run("networksetup", "-setsocksfirewallproxy", svc, "127.0.0.1", str(socks_port))
            _run("networksetup", "-setproxybypassdomains", svc, *BYPASS[:-1])
        _run("networksetup", "-setwebproxystate", svc, state)
        _run("networksetup", "-setsecurewebproxystate", svc, state)
        _run("networksetup", "-setsocksfirewallproxystate", svc, state)


def _linux(enable: bool, http_port: int, socks_port: int):
    if shutil.which("gsettings"):
        g = "org.gnome.system.proxy"
        if enable:
            for proto, port in (("http", http_port), ("https", http_port), ("socks", socks_port)):
                _run("gsettings", "set", f"{g}.{proto}", "host", "127.0.0.1")
                _run("gsettings", "set", f"{g}.{proto}", "port", str(port))
            _run("gsettings", "set", g, "ignore-hosts",
                 "['localhost', '127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']")
        _run("gsettings", "set", g, "mode", "manual" if enable else "none")
    kwrite = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    if kwrite:
        def kw(key, val):
            _run(kwrite, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", key, val)
        kw("ProxyType", "1" if enable else "0")
        if enable:
            kw("httpProxy", f"http://127.0.0.1 {http_port}")
            kw("httpsProxy", f"http://127.0.0.1 {http_port}")
            kw("socksProxy", f"socks://127.0.0.1 {socks_port}")


def set_system_proxy(enable: bool, http_port: int = 10809, socks_port: int = 10808):
    system = platform.system()
    if system == "Windows":
        _windows(enable, http_port)
    elif system == "Darwin":
        _macos(enable, http_port, socks_port)
    else:
        _linux(enable, http_port, socks_port)
