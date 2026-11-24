"""Окно KeyConnect на tkinter."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

import links
import sysproxy
import xray
from storage import Store

NET_LABEL = {"tcp": "tcp", "raw": "tcp", "ws": "ws", "grpc": "grpc",
             "httpupgrade": "httpupgrade", "xhttp": "xhttp", "splithttp": "xhttp"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("KeyConnect")
        self.geometry("880x600")
        self.minsize(700, 450)
        icon = xray.app_dir() / "icon.png"
        if icon.exists():
            try:
                self._icon = tk.PhotoImage(file=str(icon))
                self.iconphoto(True, self._icon)
            except tk.TclError:
                pass
        self.store = Store()
        self.q: queue.Queue = queue.Queue()
        self.core: xray.XrayProcess | None = None
        self.active_id: str | None = None
        self.proxy_applied = False
        self.busy = False
        self._build()
        self._refresh()
        self.after(80, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- интерфейс ----------
    def _build(self):
        bar = ttk.Frame(self, padding=(8, 8, 8, 0))
        bar.pack(fill="x")
        for text, cmd in (("Вставить ключ (Ctrl+V)", self.paste),
                          ("Добавить подписку…", self.add_subscription),
                          ("Обновить подписки", self.update_subscriptions),
                          ("Тест задержки", self.test_delay),
                          ("Удалить", self.delete)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 6))

        cols = ("name", "proto", "addr", "net", "delay")
        frame = ttk.Frame(self, padding=8)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for c, title, w in (("name", "Название", 300), ("proto", "Протокол", 90),
                            ("addr", "Адрес", 220), ("net", "Транспорт", 120),
                            ("delay", "Задержка", 90)):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor="w" if c in ("name", "addr") else "center")
        self.tree.tag_configure("active", background="#d7f5dd")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.connect())
        self.tree.bind("<Button-3>", self._context_menu)
        self.tree.bind("<Button-2>", self._context_menu)
        self.tree.bind("<Delete>", lambda e: self.delete())

        ctl = ttk.Frame(self, padding=(8, 0, 8, 4))
        ctl.pack(fill="x")
        self.btn = ttk.Button(ctl, text="Подключить", width=16, command=self.toggle)
        self.btn.pack(side="left")
        self.status = ttk.Label(ctl, text="Отключено", foreground="#888")
        self.status.pack(side="left", padx=10)
        st = self.store.settings
        self.v_proxy = tk.BooleanVar(value=st["system_proxy"])
        self.v_ru = tk.BooleanVar(value=st["bypass_ru"])
        ttk.Checkbutton(ctl, text="Россия напрямую", variable=self.v_ru,
                        command=self._on_ru).pack(side="right")
        ttk.Checkbutton(ctl, text="Системный прокси", variable=self.v_proxy,
                        command=self._on_proxy).pack(side="right", padx=10)
        ttk.Label(ctl, text=f"SOCKS5 127.0.0.1:{st['socks_port']}  ·  HTTP 127.0.0.1:{st['http_port']}",
                  foreground="#888").pack(side="right", padx=10)

        self.log_box = ScrolledText(self, height=8, state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="x", padx=8, pady=(0, 8))

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Подключиться", command=self.connect)
        self.menu.add_command(label="Копировать ключ", command=self.copy_link)
        self.menu.add_command(label="Переименовать…", command=self.rename)
        self.menu.add_separator()
        self.menu.add_command(label="Удалить", command=self.delete)

        self.bind_all("<Control-v>", lambda e: self._paste_hotkey(e))
        self.bind_all("<Command-v>", lambda e: self._paste_hotkey(e))

    def _refresh(self):
        sel = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for s in self.store.servers:
            delay = s.get("_delay", "")
            self.tree.insert("", "end", iid=s["id"], values=(
                ("● " if s["id"] == self.active_id else "") + s["name"],
                s["protocol"], f"{s['address']}:{s['port']}",
                NET_LABEL.get(s.get("network", "tcp"), s.get("network")) +
                (f"+{s['security']}" if s.get("security") not in (None, "none") else ""),
                delay), tags=("active",) if s["id"] == self.active_id else ())
        keep = [i for i in sel if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        elif self.store.selected and self.tree.exists(self.store.selected):
            self.tree.selection_set(self.store.selected)

    def log(self, text: str):
        self.q.put(("log", text))

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", time.strftime("%H:%M:%S ") + payload + "\n")
                    lines = int(self.log_box.index("end-1c").split(".")[0])
                    if lines > 1000:
                        self.log_box.delete("1.0", f"{lines - 1000}.0")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def ui(self, fn):
        self.q.put(("call", fn))

    def bg(self, work, done=None):
        def run():
            try:
                res, err = work(), None
            except Exception as e:  # noqa: BLE001
                res, err = None, e
            if done:
                self.ui(lambda: done(res, err))
            elif err:
                self.log(f"Ошибка: {err}")
        threading.Thread(target=run, daemon=True).start()

    def _selected(self) -> list[dict]:
        return [s for i in self.tree.selection() if (s := self.store.get(i))]

    def _context_menu(self, e):
        row = self.tree.identify_row(e.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.menu.tk_popup(e.x_root, e.y_root)

    # ---------- добавление ----------
    def _paste_hotkey(self, e):
        if isinstance(e.widget, (tk.Entry, ttk.Entry)):
            return
        self.paste()
        return "break"

    def paste(self):
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if not text:
            messagebox.showinfo("KeyConnect", "Буфер обмена пуст. Скопируйте ключ vless://, vmess://, trojan:// или ss://")
            return
        if text.startswith(("http://", "https://")) and "\n" not in text:
            self._load_subscription(text)
            return
        servers, errors = links.parse_many(text)
        for e in errors:
            self.log(f"Пропущен ключ: {e}")
        if not servers:
            messagebox.showwarning("KeyConnect", "В буфере не найдено подходящих ключей.")
            return
        n = self.store.add_servers(servers)
        self.log(f"Добавлено серверов: {n}" + (f" (дубликатов: {len(servers) - n})" if len(servers) > n else ""))
        self._refresh()

    def add_subscription(self):
        url = simpledialog.askstring("Подписка", "Ссылка на подписку (https://…):", parent=self)
        if url and url.strip():
            self._load_subscription(url.strip())

    def _proxy_port(self):
        return self.store.settings["http_port"] if self.core and self.core.running else None

    def _load_subscription(self, url: str):
        self.log(f"Загружаю подписку {url}")
        port = self._proxy_port()

        def done(res, err):
            if err:
                self.log(f"Подписка не загрузилась: {err}")
                messagebox.showerror("KeyConnect", f"Не удалось загрузить подписку:\n{err}")
                return
            servers, errors = res
            for e in errors:
                self.log(f"Пропущен ключ: {e}")
            if not any(s["url"] == url for s in self.store.subscriptions):
                self.store.subscriptions.append({"url": url})
            n = self.store.replace_subscription(url, servers)
            self.log(f"Подписка: {n} серверов")
            if self.active_id and not self.store.get(self.active_id):
                self.log("Активный сервер исчез из подписки — соединение работает до отключения.")
            self._refresh()
        self.bg(lambda: links.fetch_subscription(url, port), done)

    def update_subscriptions(self):
        if not self.store.subscriptions:
            messagebox.showinfo("KeyConnect", "Подписок пока нет.")
            return
        for sub in self.store.subscriptions:
            self._load_subscription(sub["url"])

    def delete(self):
        sel = self._selected()
        if not sel:
            return
        if not messagebox.askyesno("KeyConnect", f"Удалить серверов: {len(sel)}?"):
            return
        ids = {s["id"] for s in sel}
        self.store.remove(ids)
        # подписка без серверов — удаляем и её
        subs_left = {s.get("sub") for s in self.store.servers}
        self.store.subscriptions = [s for s in self.store.subscriptions if s["url"] in subs_left]
        self.store.save()
        self._refresh()

    def copy_link(self):
        sel = self._selected()
        if sel:
            self.clipboard_clear()
            self.clipboard_append("\n".join(s["link"] for s in sel))
            self.log("Ключ скопирован.")

    def rename(self):
        sel = self._selected()
        if not sel:
            return
        s = sel[0]
        name = simpledialog.askstring("Переименовать", "Новое название:", initialvalue=s["name"], parent=self)
        if name:
            s["name"] = name.strip()
            self.store.save()
            self._refresh()

    # ---------- подключение ----------
    def toggle(self):
        if self.core and self.core.running:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        if self.busy:
            return
        sel = self._selected()
        server = sel[0] if sel else self.store.get(self.store.selected)
        if not server:
            messagebox.showinfo("KeyConnect", "Выберите сервер в списке.")
            return
        st = self.store.settings
        self.busy = True
        self.btn.configure(state="disabled")
        self.status.configure(text=f"Подключаюсь к {server['name']}…", foreground="#c80")

        def work():
            binary = xray.ensure_xray(self.log)
            if self.core:
                self.core.stop()
            for p in (st["socks_port"], st["http_port"]):
                if xray.port_busy(p):
                    raise RuntimeError(f"порт {p} занят другой программой (закройте v2rayN/Hiddify или смените порт в data.json)")
            cfg = xray.build_config(server, st["socks_port"], st["http_port"], self.v_ru.get())
            core = xray.XrayProcess(binary, self.log)
            core.start(cfg, st["http_port"])
            self.core = core
            try:
                return xray.http_delay(st["http_port"])
            except Exception as e:  # noqa: BLE001
                self.log(f"Проверка связи не прошла: {e}")
                return None

        def done(delay, err):
            self.busy = False
            self.btn.configure(state="normal")
            if err:
                self.active_id = None
                self.status.configure(text="Ошибка подключения", foreground="#c00")
                self.btn.configure(text="Подключить")
                self.log(f"Ошибка: {err}")
                self._apply_proxy(False)
                self._refresh()
                return
            self.active_id = server["id"]
            self.store.selected = server["id"]
            self.store.save()
            server["_delay"] = f"{delay} мс" if delay else "нет связи"
            if delay:
                self.status.configure(text=f"Подключено: {server['name']} · {delay} мс", foreground="#080")
            else:
                self.status.configure(text=f"Xray запущен, но сервер не отвечает", foreground="#c80")
            self.btn.configure(text="Отключить")
            self._apply_proxy(self.v_proxy.get())
            self._refresh()
        self.bg(work, done)

    def disconnect(self):
        self._apply_proxy(False)
        if self.core:
            self.core.stop()
        self.active_id = None
        self.status.configure(text="Отключено", foreground="#888")
        self.btn.configure(text="Подключить")
        self.log("Отключено.")
        self._refresh()

    def _apply_proxy(self, enable: bool):
        if enable == self.proxy_applied:
            return
        st = self.store.settings
        try:
            sysproxy.set_system_proxy(enable, st["http_port"], st["socks_port"])
            self.proxy_applied = enable
            self.log("Системный прокси " + ("включён." if enable else "выключен."))
        except Exception as e:  # noqa: BLE001
            self.log(f"Не удалось изменить системный прокси: {e}")

    def _on_proxy(self):
        self.store.settings["system_proxy"] = self.v_proxy.get()
        self.store.save()
        if self.core and self.core.running:
            self._apply_proxy(self.v_proxy.get())

    def _on_ru(self):
        self.store.settings["bypass_ru"] = self.v_ru.get()
        self.store.save()
        if self.core and self.core.running and self.active_id:
            self.tree.selection_set(self.active_id)
            self.connect()  # переподключение с новыми правилами

    # ---------- тест ----------
    def test_delay(self):
        servers = self._selected() or list(self.store.servers)
        if not servers:
            return
        for s in servers:
            s["_delay"] = "…"
        self._refresh()
        self.log(f"Тестирую серверов: {len(servers)}")

        def work():
            binary = xray.ensure_xray(self.log)

            def one(s):
                try:
                    d = xray.url_test(binary, s)
                    s["_delay"] = f"{d} мс" if d else "таймаут"
                except Exception as e:  # noqa: BLE001
                    s["_delay"] = "ошибка"
                    self.log(f"{s['name']}: {e}")
                self.ui(self._refresh)
            with ThreadPoolExecutor(max_workers=6) as ex:
                list(ex.map(one, servers))
        self.bg(work, lambda r, e: self.log("Тест завершён." if not e else f"Ошибка теста: {e}"))

    def _on_close(self):
        try:
            self._apply_proxy(False)
            if self.core:
                self.core.stop()
            self.store.save()
        finally:
            self.destroy()


def run():
    App().mainloop()
