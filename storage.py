"""Хранение серверов, подписок и настроек в JSON."""
from __future__ import annotations

import json
import os
import platform
import uuid
from pathlib import Path

APP = "KeyConnect"

DEFAULT_SETTINGS = {
    "socks_port": 10808,
    "http_port": 10809,
    "system_proxy": True,
    "bypass_ru": True,
}


def data_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / APP
    d.mkdir(parents=True, exist_ok=True)
    return d


class Store:
    def __init__(self):
        self.path = data_dir() / "data.json"
        self.servers: list[dict] = []
        self.subscriptions: list[dict] = []
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self.selected: str | None = None
        self.load()

    def load(self):
        if not self.path.exists():
            return
        try:
            d = json.loads(self.path.read_text("utf-8"))
        except Exception:
            self.path.rename(self.path.with_suffix(".broken.json"))
            return
        self.servers = d.get("servers", [])
        self.subscriptions = d.get("subscriptions", [])
        self.settings.update(d.get("settings", {}))
        self.selected = d.get("selected")

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "servers": self.servers, "subscriptions": self.subscriptions,
            "settings": self.settings, "selected": self.selected,
        }, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.path)

    def add_servers(self, servers: list[dict], sub: str | None = None) -> int:
        known = {s["link"] for s in self.servers}
        added = 0
        for s in servers:
            if s["link"] in known:
                continue
            s["id"] = uuid.uuid4().hex
            if sub:
                s["sub"] = sub
            self.servers.append(s)
            known.add(s["link"])
            added += 1
        self.save()
        return added

    def replace_subscription(self, url: str, servers: list[dict]) -> int:
        self.servers = [s for s in self.servers if s.get("sub") != url]
        return self.add_servers(servers, sub=url)

    def get(self, sid: str | None) -> dict | None:
        return next((s for s in self.servers if s["id"] == sid), None)

    def remove(self, ids: set[str]):
        self.servers = [s for s in self.servers if s["id"] not in ids]
        self.save()
