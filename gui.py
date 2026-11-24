"""Окно KeyConnect: тёмная тема, карточки серверов с флагами, круглая кнопка подключения."""
from __future__ import annotations

import json
import platform
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

import flags
import links
import sysproxy
import xray
from storage import Store

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

C = {
    "bg": "#0d1119", "panel": "#131925", "card": "#192030", "card_hover": "#1f2839",
    "card_sel": "#232e47", "border": "#2a3449", "text": "#e9edf5", "muted": "#8f99ad",
    "dim": "#5f6a80", "accent": "#7b8cff", "accent_dark": "#5b6be0", "green": "#34d399",
    "amber": "#fbbf24", "orange": "#fb923c", "red": "#f87171", "input": "#0f1420",
}
NET_LABEL = {"tcp": "TCP", "raw": "TCP", "ws": "WS", "grpc": "gRPC", "httpupgrade": "HTTPUpgrade",
             "xhttp": "XHTTP", "splithttp": "XHTTP"}
PROTO_LABEL = {"vless": "VLESS", "vmess": "VMess", "trojan": "Trojan", "shadowsocks": "Shadowsocks",
               "hysteria2": "Hysteria2", "hysteria": "Hysteria", "wireguard": "WireGuard"}


# ---------- помощники ----------

def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def blend(c1: str, c2: str, t: float) -> str:
    """Смешивание цветов: t=0 → c1, t=1 → c2."""
    a, b = _hex(c1), _hex(c2)
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def round_rect(cv: tk.Canvas, x1, y1, x2, y2, r, **kw):
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def enable_dpi_awareness():
    if not IS_WIN:
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def dark_titlebar(win: tk.Misc):
    """Тёмный заголовок окна на Windows 10/11."""
    if not IS_WIN:
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def fix_entry_paste(entry: tk.Entry):
    """Ctrl+V/C/X/A в полях ввода при русской раскладке."""
    actions = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>"}

    if not IS_WIN:  # на macOS/Linux горячие клавиши работают в любой раскладке
        return

    def on_key(e):
        if e.keysym.lower() in ("v", "c", "x", "a"):
            return None
        if e.keycode in actions:
            entry.event_generate(actions[e.keycode])
            return "break"
        if e.keycode == 65:
            entry.select_range(0, "end")
            return "break"
        return None
    entry.bind("<Control-KeyPress>", on_key)


# ---------- элементы ----------

class Switch(tk.Canvas):
    def __init__(self, master, app, value: bool, command):
        self.app = app
        self.w, self.h = app.px(42), app.px(24)
        super().__init__(master, width=self.w, height=self.h, bg=master["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self.value = value
        self.command = command
        self.bind("<Button-1>", self._toggle)
        self.draw()

    def _toggle(self, _=None):
        self.value = not self.value
        self.draw()
        self.command(self.value)

    def draw(self):
        self.delete("all")
        w, h = self.w, self.h
        col = C["accent"] if self.value else C["border"]
        round_rect(self, 1, 1, w - 1, h - 1, h / 2, fill=col, outline=col)
        r = h / 2 - self.app.px(3)
        cx = w - h / 2 if self.value else h / 2
        self.create_oval(cx - r, h / 2 - r, cx + r, h / 2 + r,
                         fill="#ffffff" if self.value else C["muted"], outline="")


class PowerButton(tk.Canvas):
    COLORS = {"off": "accent", "connecting": "amber", "on": "green", "warn": "amber"}

    def __init__(self, master, app, command):
        self.app = app
        self.size = app.px(176)
        super().__init__(master, width=self.size, height=self.size, bg=master["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self.command = command
        self.state = "off"
        self.angle = 0
        self.hover = False
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.draw()

    def _set_hover(self, v):
        self.hover = v
        self.draw()

    def set_state(self, state: str):
        self.state = state
        self.draw()
        if state == "connecting":
            self._spin()

    def _spin(self):
        if self.state != "connecting":
            return
        self.angle = (self.angle - 14) % 360
        self.draw()
        self.after(40, self._spin)

    def draw(self):
        self.delete("all")
        p, s = self.app.px, self.size
        c = s / 2
        bg = self["bg"]
        col = C[self.COLORS.get(self.state, "accent")]
        if self.state == "off" and not self.hover:
            col = blend(C["accent"], C["muted"], 0.35)
        # мягкое свечение — концентрические кольца с убывающей яркостью
        glow = 0.55 if self.state in ("on", "connecting") or self.hover else 0.3
        for i in range(10, 0, -1):
            r = p(58) + i * p(2.6)
            t = 1 - glow * (1 - i / 10) ** 2
            self.create_oval(c - r, c - r, c + r, c + r, outline=blend(col, bg, t), width=p(2.6) + 2)
        R = p(60)
        self.create_oval(c - R, c - R, c + R, c + R, fill=blend(col, C["panel"], 0.84),
                         outline=col, width=p(2.5))
        if self.state == "connecting":
            rr = R + p(9)
            self.create_arc(c - rr, c - rr, c + rr, c + rr, start=self.angle, extent=100,
                            style="arc", outline=col, width=p(3))
        # значок питания
        r = p(21)
        self.create_arc(c - r, c - r + p(3), c + r, c + r + p(3), start=125, extent=290,
                        style="arc", outline=col, width=p(4.5))
        self.create_line(c, c - r - p(1), c, c - p(2), fill=col, width=p(4.5), capstyle="round")


# ---------- окно ----------

class App(tk.Tk):
    ROW = 60
    GAP = 8

    def __init__(self):
        enable_dpi_awareness()
        super().__init__()
        self.s = max(1.0, (self.winfo_fpixels("1i") or 96) / 96)
        self.title("KeyConnect")
        self.configure(bg=C["bg"])
        self.geometry(f"{self.px(1000)}x{self.px(680)}")
        self.minsize(self.px(860), self.px(560))
        icon = xray.app_dir() / "icon.png"
        self._icon_img = None
        if icon.exists():
            try:
                self._icon_img = tk.PhotoImage(file=str(icon))
                self.iconphoto(True, self._icon_img)
            except tk.TclError:
                pass

        self.store = Store()
        for s in self.store.servers:  # старые версии хранили задержку строкой
            if isinstance(s.get("_delay"), str):
                s["_delay"] = None
            s.pop("_testing", None)
        self.q: queue.Queue = queue.Queue()
        self.core: xray.XrayProcess | None = None
        self.active_id: str | None = None
        self.sel_id: str | None = self.store.selected
        self.hover_idx: int | None = None
        self.visible: list[dict] = []
        self.proxy_applied = False
        self.busy = False
        self.conn_state = "off"
        self.conn_delay: int | None = None
        self.logs: list[str] = []
        self.log_win: tk.Toplevel | None = None
        self.log_text: tk.Text | None = None

        self._fonts()
        self._styles()
        self._build()
        self._set_state("off")
        self._redraw()
        dark_titlebar(self)
        self.after(80, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def px(self, n: float) -> int:
        return int(round(n * self.s))

    # ---------- оформление ----------
    def _fonts(self):
        fam = "Segoe UI" if IS_WIN else ("Helvetica Neue" if IS_MAC else "DejaVu Sans")
        semi = "Segoe UI Semibold" if IS_WIN else fam
        F = tkfont.Font
        self.f_logo = F(family=semi, size=15, weight="bold")
        self.f_h = F(family=semi, size=13, weight="bold")
        self.f_status = F(family=semi, size=15, weight="bold")
        self.f_name = F(family=semi, size=10, weight="bold")
        self.f_body = F(family=fam, size=10)
        self.f_small = F(family=fam, size=9)
        self.f_tiny = F(family=fam, size=8)
        self.f_mono = F(family="Consolas" if IS_WIN else ("Menlo" if IS_MAC else "DejaVu Sans Mono"), size=9)

    def _styles(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        pad = (self.px(14), self.px(7))
        st.configure("Pill.TButton", background=C["card"], foreground=C["text"],
                     bordercolor=C["border"], lightcolor=C["card"], darkcolor=C["card"],
                     focuscolor=C["card"], borderwidth=1, relief="flat", padding=pad, font=self.f_body)
        st.map("Pill.TButton",
               background=[("pressed", C["card_sel"]), ("active", C["card_hover"])],
               bordercolor=[("active", C["accent"])],
               lightcolor=[("active", C["card_hover"])], darkcolor=[("active", C["card_hover"])])
        st.configure("Accent.TButton", background=C["accent"], foreground="#0b1020",
                     bordercolor=C["accent"], lightcolor=C["accent"], darkcolor=C["accent"],
                     focuscolor=C["accent"], borderwidth=1, relief="flat", padding=pad, font=self.f_name)
        hov = blend(C["accent"], "#ffffff", 0.15)
        st.map("Accent.TButton",
               background=[("pressed", C["accent_dark"]), ("active", hov)],
               lightcolor=[("active", hov)], darkcolor=[("active", hov)], bordercolor=[("active", hov)])
        st.configure("Dark.Vertical.TScrollbar", background=C["card"], troughcolor=C["bg"],
                     bordercolor=C["bg"], lightcolor=C["card"], darkcolor=C["card"],
                     arrowcolor=C["muted"], gripcount=0, arrowsize=self.px(12))
        st.map("Dark.Vertical.TScrollbar", background=[("active", C["card_hover"])])

    def _menu(self) -> tk.Menu:
        return tk.Menu(self, tearoff=0, bg=C["card"], fg=C["text"], activebackground=C["accent"],
                       activeforeground="#0b1020", disabledforeground=C["dim"], bd=0,
                       relief="flat", font=self.f_body)

    # ---------- компоновка ----------
    def _build(self):
        p = self.px
        left = tk.Frame(self, bg=C["panel"], width=p(340))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Frame(self, bg=C["border"], width=1).pack(side="left", fill="y")
        right = tk.Frame(self, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)

        # --- левая панель
        head = tk.Frame(left, bg=C["panel"])
        head.pack(fill="x", padx=p(22), pady=(p(20), 0))
        if self._icon_img is not None:
            k = max(1, round(256 / p(30)))
            self._logo = self._icon_img.subsample(k, k)
            tk.Label(head, image=self._logo, bg=C["panel"]).pack(side="left", padx=(0, p(10)))
        tk.Label(head, text="KeyConnect", font=self.f_logo, bg=C["panel"], fg=C["text"]).pack(side="left")

        self.power = PowerButton(left, self, self.toggle)
        self.power.pack(pady=(p(26), p(6)))
        self.lbl_status = tk.Label(left, font=self.f_status, bg=C["panel"], fg=C["muted"])
        self.lbl_status.pack()
        self.lbl_hint = tk.Label(left, font=self.f_small, bg=C["panel"], fg=C["dim"],
                                 wraplength=p(290), justify="center")
        self.lbl_hint.pack(pady=(p(4), p(18)))

        self.cur = tk.Canvas(left, height=p(66), bg=C["panel"], highlightthickness=0, bd=0, cursor="hand2")
        self.cur.pack(fill="x", padx=p(18))
        self.cur.bind("<Configure>", lambda e: self._draw_current())
        self.cur.bind("<Button-1>", lambda e: self._scroll_to_selected())

        opts = tk.Frame(left, bg=C["panel"])
        opts.pack(fill="x", padx=p(22), pady=(p(22), 0))
        st = self.store.settings
        self.sw_proxy = self._option(opts, "Системный прокси", "Браузер и программы идут через VPN",
                                     st["system_proxy"], self._on_proxy)
        self.sw_ru = self._option(opts, "Россия напрямую", "Российские сайты открываются без VPN",
                                  st["bypass_ru"], self._on_ru)

        foot = tk.Frame(left, bg=C["panel"])
        foot.pack(side="bottom", fill="x", padx=p(22), pady=p(18))
        ttk.Button(foot, text="Журнал", style="Pill.TButton", command=self.show_log).pack(side="left")
        tk.Label(foot, text=f"SOCKS {st['socks_port']}  ·  HTTP {st['http_port']}",
                 font=self.f_tiny, bg=C["panel"], fg=C["dim"]).pack(side="right")

        # --- правая панель
        top = tk.Frame(right, bg=C["bg"])
        top.pack(fill="x", padx=p(22), pady=(p(20), p(12)))
        tk.Label(top, text="Серверы", font=self.f_h, bg=C["bg"], fg=C["text"]).pack(side="left")
        self.lbl_count = tk.Label(top, font=self.f_small, bg=C["bg"], fg=C["dim"])
        self.lbl_count.pack(side="left", padx=(p(8), 0), pady=(p(3), 0))
        self.btn_more = ttk.Button(top, text="Ещё ▾", style="Pill.TButton", command=self._more_menu)
        self.btn_more.pack(side="right")
        ttk.Button(top, text="Тест", style="Pill.TButton", command=self.test_delay).pack(side="right", padx=(0, p(8)))
        ttk.Button(top, text="Обновить", style="Pill.TButton",
                   command=self.update_subscriptions).pack(side="right", padx=(0, p(8)))
        self.btn_add = ttk.Button(top, text="+  Добавить", style="Accent.TButton", command=self._add_menu)
        self.btn_add.pack(side="right", padx=(0, p(8)))

        sbox = tk.Frame(right, bg=C["input"], highlightthickness=1, highlightbackground=C["border"],
                        highlightcolor=C["accent"])
        sbox.pack(fill="x", padx=p(22), pady=(0, p(12)))
        tk.Label(sbox, text="Поиск", font=self.f_small, bg=C["input"], fg=C["dim"]).pack(side="left", padx=(p(12), p(6)))
        self.v_search = tk.StringVar()
        self.v_search.trace_add("write", lambda *a: self._redraw())
        e = tk.Entry(sbox, textvariable=self.v_search, bg=C["input"], fg=C["text"], relief="flat", bd=0,
                     insertbackground=C["text"], font=self.f_body, highlightthickness=0)
        e.pack(side="left", fill="x", expand=True, ipady=p(7))
        fix_entry_paste(e)
        e.bind("<Escape>", lambda ev: self.v_search.set(""))

        box = tk.Frame(right, bg=C["bg"])
        box.pack(fill="both", expand=True, padx=(p(22), p(8)), pady=(0, p(14)))
        self.cv = tk.Canvas(box, bg=C["bg"], highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(box, orient="vertical", style="Dark.Vertical.TScrollbar", command=self.cv.yview)
        self.cv.configure(yscrollcommand=self.sb.set)
        self.sb.pack(side="right", fill="y", padx=(p(6), 0))
        self.cv.pack(side="left", fill="both", expand=True)

        cv = self.cv
        cv.bind("<Configure>", lambda e: self._redraw())
        cv.bind("<Motion>", self._on_motion)
        cv.bind("<Leave>", lambda e: self._set_hover(None))
        cv.bind("<Button-1>", self._on_click)
        cv.bind("<Double-Button-1>", lambda e: self.connect())
        cv.bind("<Button-3>", self._on_right_click)
        if IS_MAC:
            cv.bind("<Button-2>", self._on_right_click)
        # колесо ловим глобально: на Windows событие приходит окну с фокусом, а не под курсором
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind_all("<Button-4>", lambda e: self._on_wheel(e, -120))
        self.bind_all("<Button-5>", lambda e: self._on_wheel(e, 120))
        self.cv.configure(yscrollincrement=self.px(20))

        self.bind_all("<Control-KeyPress>", self._paste_hotkey)
        if IS_MAC:
            self.bind_all("<Command-KeyPress>", self._paste_hotkey)
        self.bind("<Up>", lambda e: self._move_sel(-1))
        self.bind("<Prior>", lambda e: self.cv.yview_scroll(-1, "pages"))
        self.bind("<Next>", lambda e: self.cv.yview_scroll(1, "pages"))
        self.bind("<Down>", lambda e: self._move_sel(1))
        self.bind("<Return>", lambda e: None if self._typing() else self.connect())
        self.bind("<Delete>", lambda e: None if self._typing() else self.delete_selected())

    def _option(self, parent, title, desc, value, command) -> Switch:
        p = self.px
        row = tk.Frame(parent, bg=C["panel"])
        row.pack(fill="x", pady=(0, p(14)))
        sw = Switch(row, self, value, command)
        sw.pack(side="right")
        txt = tk.Frame(row, bg=C["panel"])
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=title, font=self.f_name, bg=C["panel"], fg=C["text"], anchor="w").pack(fill="x")
        tk.Label(txt, text=desc, font=self.f_small, bg=C["panel"], fg=C["dim"], anchor="w").pack(fill="x")
        return sw

    # ---------- данные для отрисовки ----------
    def _country(self, s: dict) -> str | None:
        if "_cc" not in s:
            s["_cc"] = flags.detect_country(s.get("name", ""), s.get("address", ""))
        return s["_cc"]

    def _subtitle(self, s: dict) -> str:
        parts = [flags.country_name(self._country(s)),
                 PROTO_LABEL.get(s.get("protocol", ""), (s.get("protocol") or "").upper())]
        net = NET_LABEL.get(s.get("network") or "tcp", (s.get("network") or "tcp").upper())
        sec = s.get("security") or "none"
        parts.append(net + (f" · {sec.upper() if sec == 'tls' else sec.capitalize()}" if sec != "none" else ""))
        return "  ·  ".join(x for x in parts if x)

    def _delay_view(self, s: dict):
        if s.get("_testing"):
            return "проверка…", C["muted"]
        d = s.get("_delay")
        if not isinstance(d, int):
            return None, None
        if d < 0:
            return "нет связи", C["red"]
        return f"{d} мс", C["green"] if d < 300 else C["amber"] if d < 800 else C["orange"]

    def _ellipsize(self, text: str, font: tkfont.Font, width: int) -> str:
        if width <= 0 or font.measure(text) <= width:
            return text
        while text and font.measure(text + "…") > width:
            text = text[:-1]
        return text + "…"

    def _draw_flag(self, cv: tk.Canvas, s: dict, x, cy):
        p = self.px
        w, h = p(30), p(20)
        code = self._country(s)
        img = flags.image(self, code, w, h)
        if img is not None:
            cv.create_image(x, cy, image=img, anchor="w")
            cv.create_rectangle(x, cy - h / 2, x + w - 1, cy + h / 2 - 1, outline=blend(C["text"], C["card"], 0.8))
        else:
            name = flags.clean_name(s.get("name", ""))
            label = "A" if name.lower().startswith("auto") else (code or next((ch for ch in name if ch.isalnum()), "?"))
            round_rect(cv, x, cy - h / 2, x + w, cy + h / 2, p(5), fill=C["border"], outline=C["border"])
            cv.create_text(x + w / 2, cy, text=label[:2].upper(), fill=C["muted"], font=self.f_tiny)

    # ---------- список ----------
    def _filtered(self) -> list[dict]:
        q = self.v_search.get().strip().lower() if hasattr(self, "v_search") else ""
        if not q:
            return list(self.store.servers)
        out = []
        for s in self.store.servers:
            hay = " ".join([s.get("name", ""), s.get("address", ""), self._subtitle(s)]).lower()
            if q in hay:
                out.append(s)
        return out

    def _row_box(self, i: int, w: int):
        p = self.px
        y1 = p(2) + i * p(self.ROW + self.GAP)
        return p(2), y1, w - p(4), y1 + p(self.ROW)

    def _redraw(self):
        cv = self.cv
        cv.delete("all")
        p = self.px
        w = cv.winfo_width()
        h = cv.winfo_height()
        if w < 50:
            w, h = p(600), p(500)
        self.visible = self._filtered()
        n_all = len(self.store.servers)
        self.lbl_count.configure(text=(f"{len(self.visible)} из {n_all}" if len(self.visible) != n_all else str(n_all)) if n_all else "")

        if not self.visible:
            cx, cy = w / 2, max(p(140), h / 2 - p(40))
            if n_all:
                cv.create_text(cx, cy, text="Ничего не найдено", fill=C["muted"], font=self.f_h)
            else:
                cv.create_text(cx, cy - p(14), text="Серверов пока нет", fill=C["text"], font=self.f_h)
                cv.create_text(cx, cy + p(16), fill=C["muted"], font=self.f_body, justify="center",
                               text="Скопируйте ключ (vless://, vmess://, trojan://, ss://)\n"
                                    "или ссылку на подписку и нажмите Ctrl+V")
            cv.configure(scrollregion=(0, 0, w, h))
            return

        for i, s in enumerate(self.visible):
            x1, y1, x2, y2 = self._row_box(i, w)
            cy = (y1 + y2) / 2
            sel = s["id"] == self.sel_id
            act = s["id"] == self.active_id
            fill = C["card_sel"] if sel else C["card_hover"] if i == self.hover_idx else C["card"]
            outline = C["green"] if act else C["accent"] if sel else fill
            round_rect(cv, x1, y1, x2, y2, p(12), fill=fill, outline=outline, width=1)
            if act:
                round_rect(cv, x1 + p(1), y1 + p(14), x1 + p(4), y2 - p(14), p(2), fill=C["green"], outline=C["green"])

            fx = x1 + p(16)
            self._draw_flag(cv, s, fx, cy)

            # справа: плашка задержки и метка «подключено»
            right = x2 - p(14)
            text, col = self._delay_view(s)
            if text:
                tw = self.f_small.measure(text) + p(20)
                bgc = blend(col, fill, 0.82)
                round_rect(cv, right - tw, cy - p(12), right, cy + p(12), p(12), fill=bgc, outline=bgc)
                cv.create_text(right - tw / 2, cy, text=text, fill=col, font=self.f_small)
                right -= tw + p(10)
            if act:
                lbl = "ПОДКЛЮЧЕНО"
                cv.create_text(right, cy, text=lbl, fill=C["green"], font=self.f_tiny, anchor="e")
                right -= self.f_tiny.measure(lbl) + p(12)

            tx = fx + p(30) + p(14)
            avail = int(right - tx - p(6))
            name = flags.clean_name(s.get("name", "")) or f"{s['address']}:{s['port']}"
            cv.create_text(tx, cy - p(9), text=self._ellipsize(name, self.f_name, avail),
                           anchor="w", fill=C["text"], font=self.f_name)
            cv.create_text(tx, cy + p(10), text=self._ellipsize(self._subtitle(s), self.f_small, avail),
                           anchor="w", fill=C["muted"], font=self.f_small)

        total = self._row_box(len(self.visible), w)[1]
        cv.configure(scrollregion=(0, 0, w, max(total, h)))
        self._draw_current()

    def _draw_current(self):
        cv = self.cur
        cv.delete("all")
        p = self.px
        w = cv.winfo_width()
        if w < 50:
            w = p(300)
        h = p(66)
        s = self.store.get(self.active_id) or self.store.get(self.sel_id)
        round_rect(cv, 1, 1, w - 1, h - 1, p(14), fill=C["card"], outline=C["border"])
        if not s:
            cv.create_text(w / 2, h / 2, text="Сервер не выбран", fill=C["dim"], font=self.f_body)
            return
        cy = h / 2
        self._draw_flag(cv, s, p(16), cy)
        tx = p(16 + 30 + 14)
        right = w - p(14)
        text, col = self._delay_view(s)
        if text:
            tw = self.f_small.measure(text) + p(20)
            bgc = blend(col, C["card"], 0.82)
            round_rect(cv, right - tw, cy - p(12), right, cy + p(12), p(12), fill=bgc, outline=bgc)
            cv.create_text(right - tw / 2, cy, text=text, fill=col, font=self.f_small)
            right -= tw + p(8)
        avail = int(right - tx)
        name = flags.clean_name(s.get("name", "")) or s["address"]
        cv.create_text(tx, cy - p(9), text=self._ellipsize(name, self.f_name, avail), anchor="w",
                       fill=C["text"], font=self.f_name)
        cv.create_text(tx, cy + p(10), text=self._ellipsize(self._subtitle(s), self.f_small, avail),
                       anchor="w", fill=C["muted"], font=self.f_small)

    def _hit(self, y) -> int | None:
        p = self.px
        cy = self.cv.canvasy(y) - p(2)
        step = p(self.ROW + self.GAP)
        i = int(cy // step)
        if cy < 0 or i >= len(self.visible) or cy - i * step > p(self.ROW):
            return None
        return i

    def _set_hover(self, idx):
        if idx != self.hover_idx:
            self.hover_idx = idx
            self._redraw()

    def _on_motion(self, e):
        idx = self._hit(e.y)
        self.cv.configure(cursor="hand2" if idx is not None else "")
        self._set_hover(idx)

    def _on_click(self, e):
        self.cv.focus_set()
        idx = self._hit(e.y)
        if idx is not None:
            self._select(self.visible[idx]["id"])

    def _on_right_click(self, e):
        idx = self._hit(e.y)
        if idx is None:
            return
        self._select(self.visible[idx]["id"])
        m = self._menu()
        m.add_command(label="Подключиться", command=self.connect)
        m.add_command(label="Проверить задержку", command=lambda: self.test_delay(only_selected=True))
        m.add_command(label="Копировать ключ", command=self.copy_link)
        m.add_command(label="Переименовать…", command=self.rename)
        m.add_separator()
        m.add_command(label="Удалить", command=self.delete_selected)
        m.tk_popup(e.x_root, e.y_root)

    def _on_wheel(self, e, delta=None):
        try:
            over = self.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            return
        if over not in (self.cv, self.sb):
            return
        if delta is not None:  # Linux: Button-4/5
            self.cv.yview_scroll(1 if delta > 0 else -1, "units")
        elif IS_MAC:
            self.cv.yview_scroll(-e.delta, "units")
        else:
            self.cv.yview_scroll(int(-e.delta / 40) or (-1 if e.delta > 0 else 1), "units")

    def _select(self, sid: str | None):
        self.sel_id = sid
        if not (self.core and self.core.running):
            self.store.selected = sid
        self._redraw()

    def _move_sel(self, d: int):
        if self._typing() or not self.visible:
            return
        ids = [s["id"] for s in self.visible]
        i = ids.index(self.sel_id) if self.sel_id in ids else -1
        i = max(0, min(len(ids) - 1, i + d))
        self._select(ids[i])
        self._scroll_to_selected()

    def _scroll_to_selected(self):
        ids = [s["id"] for s in self.visible]
        if self.sel_id not in ids:
            return
        i = ids.index(self.sel_id)
        _, y1, _, y2 = self._row_box(i, self.cv.winfo_width())
        top, bottom = self.cv.canvasy(0), self.cv.canvasy(self.cv.winfo_height())
        total = self._row_box(len(self.visible), 0)[1] or 1
        if y1 < top:
            self.cv.yview_moveto(max(0, y1 - self.px(4)) / total)
        elif y2 > bottom:
            self.cv.yview_moveto(max(0, y2 - self.cv.winfo_height() + self.px(4)) / total)

    def _typing(self) -> bool:
        return isinstance(self.focus_get(), (tk.Entry, ttk.Entry, tk.Text))

    # ---------- журнал и поток событий ----------
    def log(self, text: str):
        self.q.put(("log", text))

    def ui(self, fn):
        self.q.put(("call", fn))

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    line = time.strftime("%H:%M:%S  ") + payload
                    self.logs.append(line)
                    if len(self.logs) > 2000:
                        del self.logs[:500]
                    if self.log_text is not None and self.log_win and self.log_win.winfo_exists():
                        t = self.log_text
                        t.configure(state="normal")
                        t.insert("end", line + "\n")
                        t.see("end")
                        t.configure(state="disabled")
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def show_log(self):
        if self.log_win is not None and self.log_win.winfo_exists():
            self.log_win.deiconify()
            self.log_win.lift()
            return
        p = self.px
        w = tk.Toplevel(self, bg=C["bg"])
        w.title("Журнал — KeyConnect")
        w.geometry(f"{p(820)}x{p(420)}")
        bar = tk.Frame(w, bg=C["bg"])
        bar.pack(fill="x", padx=p(14), pady=p(10))
        tk.Label(bar, text="Журнал", font=self.f_h, bg=C["bg"], fg=C["text"]).pack(side="left")

        def copy_all():
            self.clipboard_clear()
            self.clipboard_append("\n".join(self.logs))

        def clear():
            self.logs.clear()
            t.configure(state="normal")
            t.delete("1.0", "end")
            t.configure(state="disabled")
        ttk.Button(bar, text="Очистить", style="Pill.TButton", command=clear).pack(side="right")
        ttk.Button(bar, text="Копировать всё", style="Pill.TButton", command=copy_all).pack(side="right", padx=(0, p(8)))
        frame = tk.Frame(w, bg=C["panel"])
        frame.pack(fill="both", expand=True, padx=p(14), pady=(0, p(14)))
        t = tk.Text(frame, bg=C["panel"], fg="#c9d1e0", font=self.f_mono, relief="flat", bd=0,
                    padx=p(12), pady=p(10), wrap="word", insertbackground=C["text"],
                    selectbackground=C["card_sel"], highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient="vertical", style="Dark.Vertical.TScrollbar", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        t.insert("end", "\n".join(self.logs) + ("\n" if self.logs else ""))
        t.configure(state="disabled")
        t.see("end")
        self.log_win, self.log_text = w, t
        dark_titlebar(w)

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

    # ---------- диалоги ----------
    def ask(self, title: str, prompt: str, initial: str = "") -> str | None:
        p = self.px
        d = tk.Toplevel(self, bg=C["panel"])
        d.title(title)
        d.transient(self)
        d.resizable(False, False)
        tk.Label(d, text=prompt, font=self.f_name, bg=C["panel"], fg=C["text"]).pack(
            anchor="w", padx=p(20), pady=(p(18), p(8)))
        v = tk.StringVar(value=initial)
        e = tk.Entry(d, textvariable=v, width=52, bg=C["input"], fg=C["text"], insertbackground=C["text"],
                     relief="flat", font=self.f_body, highlightthickness=1,
                     highlightbackground=C["border"], highlightcolor=C["accent"])
        e.pack(padx=p(20), fill="x", ipady=p(7))
        fix_entry_paste(e)
        res = {"v": None}

        def ok(*_):
            res["v"] = v.get().strip()
            d.destroy()
        bar = tk.Frame(d, bg=C["panel"])
        bar.pack(fill="x", padx=p(20), pady=p(16))
        ttk.Button(bar, text="Готово", style="Accent.TButton", command=ok).pack(side="right")
        ttk.Button(bar, text="Отмена", style="Pill.TButton", command=d.destroy).pack(side="right", padx=(0, p(8)))
        d.bind("<Return>", ok)
        d.bind("<Escape>", lambda ev: d.destroy())
        d.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - d.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - d.winfo_height()) // 3
        d.geometry(f"+{max(0, x)}+{max(0, y)}")
        dark_titlebar(d)
        e.focus_set()
        e.select_range(0, "end")
        try:
            d.wait_visibility()
            d.grab_set()
        except tk.TclError:
            pass
        self.wait_window(d)
        return res["v"] or None

    # ---------- меню ----------
    def _add_menu(self):
        m = self._menu()
        m.add_command(label="Вставить ключ из буфера", accelerator="Ctrl+V", command=self.paste)
        m.add_command(label="Добавить подписку…", command=self.add_subscription)
        b = self.btn_add
        m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height() + self.px(4))

    def _more_menu(self):
        m = self._menu()
        has = bool(self.store.servers)
        st = "normal" if has else "disabled"
        m.add_command(label="Сортировать по задержке", command=self.sort_by_delay, state=st)
        m.add_command(label="Проверить выбранный", command=lambda: self.test_delay(only_selected=True), state=st)
        m.add_separator()
        m.add_command(label="Удалить выбранный", command=self.delete_selected,
                      state="normal" if self.store.get(self.sel_id) else "disabled")
        if self.store.subscriptions:
            sub = self._menu()
            for s in self.store.subscriptions:
                url = s["url"]
                n = sum(1 for x in self.store.servers if x.get("sub") == url)
                host = urlsplit(url).hostname or url
                sub.add_command(label=f"{host}  ({n})", command=lambda u=url: self.delete_subscription(u))
            m.add_cascade(label="Удалить подписку", menu=sub)
        m.add_command(label="Удалить все серверы…", command=self.delete_all, state=st)
        m.add_separator()
        m.add_command(label="Открыть журнал", command=self.show_log)
        b = self.btn_more
        m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height() + self.px(4))

    # ---------- добавление ----------
    def _paste_hotkey(self, e):
        if not (e.keycode == 86 or e.keysym.lower() in ("v", "cyrillic_em")):
            return None
        if isinstance(e.widget, (tk.Entry, ttk.Entry, tk.Text)):
            return None
        self.paste()
        return "break"

    def paste(self):
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if not text:
            messagebox.showinfo("KeyConnect", "Буфер обмена пуст.\nСкопируйте ключ (vless://, vmess://, "
                                              "trojan://, ss://) или ссылку на подписку.", parent=self)
            return
        if text.startswith(("http://", "https://")) and "\n" not in text:
            self._load_subscription(text)
            return
        servers, errors = links.parse_many(text)
        for e in errors:
            self.log(f"Пропущен ключ: {e}")
        if not servers:
            messagebox.showwarning("KeyConnect", "Не удалось распознать ключ.\n\n" +
                                   ("\n".join(errors[:3]) if errors else "Поддерживаются vless, vmess, "
                                    "trojan, ss и ссылки на подписки."), parent=self)
            return
        n = self.store.add_servers(servers)
        self.log(f"Добавлено серверов: {n}" + (f" (повторов: {len(servers) - n})" if len(servers) > n else ""))
        if n and servers:
            last = next((s for s in reversed(self.store.servers) if s["link"] == servers[-1]["link"]), None)
            if last:
                self._select(last["id"])
        self._redraw()
        if not n:
            messagebox.showinfo("KeyConnect", "Этот ключ уже есть в списке.", parent=self)

    def add_subscription(self):
        url = self.ask("Подписка", "Ссылка на подписку")
        if url:
            self._load_subscription(url)

    def _proxy_port(self):
        return self.store.settings["http_port"] if self.core and self.core.running else None

    def _load_subscription(self, url: str, quiet: bool = False):
        self.log(f"Загружаю подписку {url}")
        self.lbl_count.configure(text="загрузка подписки…")
        port = self._proxy_port()

        def done(res, err):
            if err:
                self.log(f"Подписка не загрузилась: {err}")
                self._redraw()
                if not quiet:
                    messagebox.showerror("KeyConnect", f"Не удалось загрузить подписку.\n\n{err}", parent=self)
                return
            servers, errors = res
            for e in errors:
                self.log(f"Пропущен ключ: {e}")
            if not any(s["url"] == url for s in self.store.subscriptions):
                self.store.subscriptions.append({"url": url})
            n = self.store.replace_subscription(url, servers)
            self.log(f"Подписка {urlsplit(url).hostname}: {n} серверов")
            if not self.store.get(self.sel_id) and self.store.servers:
                self.sel_id = self.store.servers[0]["id"]
            self._redraw()
        self.bg(lambda: links.fetch_subscription(url, port), done)

    def update_subscriptions(self):
        if not self.store.subscriptions:
            messagebox.showinfo("KeyConnect", "Подписок пока нет.\nНажмите «Добавить» → «Добавить подписку».",
                                parent=self)
            return
        for sub in self.store.subscriptions:
            self._load_subscription(sub["url"])

    # ---------- удаление и правка ----------
    def _after_delete(self):
        subs_left = {s.get("sub") for s in self.store.servers}
        self.store.subscriptions = [s for s in self.store.subscriptions if s["url"] in subs_left]
        if not self.store.get(self.sel_id):
            self.sel_id = self.store.servers[0]["id"] if self.store.servers else None
            self.store.selected = self.sel_id
        self.store.save()
        self._redraw()

    def delete_selected(self):
        s = self.store.get(self.sel_id)
        if not s:
            return
        name = flags.clean_name(s["name"])
        if not messagebox.askyesno("KeyConnect", f"Удалить сервер «{name}»?", parent=self):
            return
        self.store.remove({s["id"]})
        self._after_delete()

    def delete_all(self):
        n = len(self.store.servers)
        if not n:
            return
        msg = f"Удалить все серверы ({n})"
        if self.store.subscriptions:
            msg += f" и подписки ({len(self.store.subscriptions)})"
        if not messagebox.askyesno("KeyConnect", msg + "?\n\nЭто действие нельзя отменить.",
                                   icon="warning", parent=self):
            return
        self.store.servers = []
        self.store.subscriptions = []
        self._after_delete()
        self.log(f"Удалено серверов: {n}")

    def delete_subscription(self, url: str):
        n = sum(1 for x in self.store.servers if x.get("sub") == url)
        host = urlsplit(url).hostname or url
        if not messagebox.askyesno("KeyConnect", f"Удалить подписку {host} и её серверы ({n})?", parent=self):
            return
        self.store.servers = [s for s in self.store.servers if s.get("sub") != url]
        self.store.subscriptions = [s for s in self.store.subscriptions if s["url"] != url]
        self._after_delete()

    def copy_link(self):
        s = self.store.get(self.sel_id)
        if not s:
            return
        self.clipboard_clear()
        self.clipboard_append(json.dumps({"remarks": s["name"], "outbounds": s["outbounds"]}, ensure_ascii=False)
                              if s.get("outbounds") else s["link"])
        self.log("Ключ скопирован.")

    def rename(self):
        s = self.store.get(self.sel_id)
        if not s:
            return
        name = self.ask("Переименовать", "Новое название", flags.clean_name(s["name"]))
        if name:
            s["name"] = name
            s.pop("_cc", None)
            self.store.save()
            self._redraw()

    def sort_by_delay(self):
        def key(s):
            d = s.get("_delay")
            return (not isinstance(d, int) or d < 0, d if isinstance(d, int) else 0)
        self.store.servers.sort(key=key)
        self.store.save()
        self.cv.yview_moveto(0)
        self._redraw()

    # ---------- подключение ----------
    def _set_state(self, state: str, hint: str | None = None):
        self.conn_state = state
        self.power.set_state(state)
        st = self.store.settings
        texts = {
            "off": ("Не подключено", C["muted"], "Выберите сервер и нажмите на кнопку"),
            "connecting": ("Подключение…", C["amber"], "Запускаю Xray и проверяю связь"),
            "on": ("Подключено", C["green"],
                   (f"{self.conn_delay} мс  ·  " if self.conn_delay else "") +
                   ("системный прокси включён" if self.sw_proxy.value else
                    f"прокси 127.0.0.1:{st['http_port']}")),
            "warn": ("Сервер не отвечает", C["amber"], "Xray запущен, но связи нет — причина в журнале"),
        }
        title, col, default_hint = texts[state]
        self.lbl_status.configure(text=title, fg=col)
        self.lbl_hint.configure(text=hint or default_hint)
        self._draw_current()

    def toggle(self):
        if self.busy:
            return
        if self.core and self.core.running:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        if self.busy:
            return
        server = self.store.get(self.sel_id)
        if not server:
            self._set_state("off", "Сначала добавьте и выберите сервер в списке справа")
            return
        st = self.store.settings
        self.busy = True
        self._set_state("connecting")
        bypass = self.sw_ru.value

        def work():
            binary = xray.ensure_xray(self.log)
            if self.core:
                self.core.stop()
            for port in (st["socks_port"], st["http_port"]):
                if xray.port_busy(port):
                    raise RuntimeError(f"порт {port} занят — закройте другие VPN-клиенты (v2rayN, Hiddify)")
            cfg = xray.build_config(server, st["socks_port"], st["http_port"], bypass, loglevel="info")
            core = xray.XrayProcess(binary, self._core_log)
            self.log(f"Подключаюсь: {flags.clean_name(server['name'])} ({server['address']}:{server['port']})")
            core.start(cfg, st["http_port"])
            self.core = core
            try:
                return xray.http_delay(st["http_port"])
            except Exception as e:  # noqa: BLE001
                self.log(f"Проверка связи не прошла: {e}")
                return None

        def done(delay, err):
            self.busy = False
            if err:
                self.active_id = None
                self.log(f"Ошибка: {err}")
                self._apply_proxy(False)
                self._set_state("off", f"Ошибка: {err}")
                self._redraw()
                return
            self.active_id = server["id"]
            self.store.selected = server["id"]
            server["_delay"] = delay if delay else -1
            self.store.save()
            self.conn_delay = delay
            self._apply_proxy(self.sw_proxy.value)
            self._set_state("on" if delay else "warn")
            self._redraw()
        self.bg(work, done)

    def _core_log(self, line: str):
        """Из подробного лога Xray показываем только ошибки, без потока «accepted»."""
        low = line.lower()
        if "accepted" in low:
            return
        if "[info]" in low and not any(k in low for k in (
                "fail", "error", "timeout", "refused", "reset", "eof", "reject", "closed")):
            return
        self.log(line[27:] if line[:4].isdigit() else line)

    def disconnect(self):
        self._apply_proxy(False)
        if self.core:
            self.core.stop()
        self.active_id = None
        self.conn_delay = None
        self.log("Отключено.")
        self._set_state("off")
        self._redraw()

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

    def _on_proxy(self, value: bool):
        self.store.settings["system_proxy"] = value
        self.store.save()
        if self.core and self.core.running:
            self._apply_proxy(value)
            if self.conn_state == "on":
                self._set_state("on")

    def _on_ru(self, value: bool):
        self.store.settings["bypass_ru"] = value
        self.store.save()
        if self.core and self.core.running and self.active_id and not self.busy:
            self.sel_id = self.active_id
            self.connect()  # переподключение с новыми правилами

    # ---------- тест задержки ----------
    def test_delay(self, only_selected: bool = False):
        if only_selected:
            s = self.store.get(self.sel_id)
            servers = [s] if s else []
        else:
            servers = self._filtered()
        servers = [s for s in servers if not s.get("_testing")]
        if not servers:
            return
        for s in servers:
            s["_testing"] = True
        self._redraw()
        self.log(f"Проверяю задержку: {len(servers)} серв.")

        def work():
            binary = xray.ensure_xray(self.log)

            def one(s):
                try:
                    d = xray.url_test(binary, s)
                    s["_delay"] = d if d else -1
                except Exception as e:  # noqa: BLE001
                    s["_delay"] = -1
                    self.log(f"{flags.clean_name(s['name'])}: {e}")
                s.pop("_testing", None)
                self.ui(self._redraw)
            with ThreadPoolExecutor(max_workers=6) as ex:
                list(ex.map(one, servers))

        def done(_, err):
            for s in servers:
                s.pop("_testing", None)
            self.store.save()
            self._redraw()
            ok = sum(1 for s in servers if isinstance(s.get("_delay"), int) and s["_delay"] > 0)
            self.log(f"Проверка завершена: отвечают {ok} из {len(servers)}." if not err else f"Ошибка теста: {err}")
        self.bg(work, done)

    def _on_close(self):
        try:
            self._apply_proxy(False)
            if self.core:
                self.core.stop()
            for s in self.store.servers:
                s.pop("_testing", None)
                s.pop("_cc", None)
            self.store.save()
        finally:
            self.destroy()


def run():
    App().mainloop()
