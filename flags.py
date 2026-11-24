"""Флаги стран (рисуются кодом, без картинок) и определение страны сервера.

Windows не показывает эмодзи-флаги (вместо 🇳🇱 пишет «NL»), поэтому флаги
рисуются попиксельно в tk.PhotoImage по упрощённым описаниям.
"""
from __future__ import annotations

import math
import re

# ---------- примитивы: работают с сеткой цветов, координаты относительные 0..1 ----------

def _H(colors, weights=None):
    weights = weights or [1] * len(colors)
    total = sum(weights)

    def f(px, py, cur):
        acc = 0
        for c, w in zip(colors, weights):
            acc += w / total
            if py < acc:
                return c
        return colors[-1]
    return f


def _V(colors, weights=None):
    h = _H(colors, weights)
    return lambda px, py, cur: h(py, px, cur)


def _F(color):
    return lambda px, py, cur: color


def _R(color, x1, y1, x2, y2):
    return lambda px, py, cur: color if x1 <= px < x2 and y1 <= py < y2 else cur


def _C(color, cx, cy, r, lower_only=False):
    """Круг; r — доля высоты флага. Аспект 3:2 учитывается."""
    def f(px, py, cur):
        dx, dy = (px - cx) * 1.5, py - cy
        if dx * dx + dy * dy <= r * r and (not lower_only or py >= cy):
            return color
        return cur
    return f


def _NORDIC(color, wide=False, x=0.36):
    t = 0.2 if wide else 0.12  # толщина креста по высоте
    tx = t / 1.5

    def f(px, py, cur):
        if abs(px - x) < tx / 2 * 1.0 or abs(py - 0.5) < t / 2:
            return color
        return cur
    return f


def _CROSS(color, t=0.16):
    tx = t / 1.5

    def f(px, py, cur):
        return color if abs(px - 0.5) < tx / 2 or abs(py - 0.5) < t / 2 else cur
    return f


def _DIAG(color, t):
    def f(px, py, cur):
        x, y = px * 1.5, py
        d1 = abs(y - x / 1.5) / math.sqrt(1 + (1 / 1.5) ** 2)
        d2 = abs(y - (1 - x / 1.5)) / math.sqrt(1 + (1 / 1.5) ** 2)
        return color if min(d1, d2) < t / 2 else cur
    return f


def _POLY(color, pts):
    def inside(x, y):
        res, n = False, len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                res = not res
        return res
    return lambda px, py, cur: color if inside(px, py) else cur


def _STRIPES(c1, c2, n):
    return _H([c1 if i % 2 == 0 else c2 for i in range(n)])


W, RD, BL = "#ffffff", "#d52b1e", "#0039a6"

FLAGS = {
    "RU": [_H([W, BL, RD])],
    "NL": [_H(["#ae1c28", W, "#21468b"])],
    "DE": [_H(["#000000", "#dd0000", "#ffce00"])],
    "FR": [_V(["#002395", W, "#ed2939"])],
    "IT": [_V(["#009246", W, "#ce2b37"])],
    "IE": [_V(["#169b62", W, "#ff883e"])],
    "BE": [_V(["#000000", "#fdda24", "#ef3340"])],
    "RO": [_V(["#002b7f", "#fcd116", "#ce1126"])],
    "MD": [_V(["#0046ae", "#ffd200", "#cc092f"]), _C("#b07e2e", 0.5, 0.5, 0.15)],
    "PL": [_H([W, "#dc143c"])],
    "UA": [_H(["#0057b7", "#ffd700"])],
    "AM": [_H(["#d90012", "#0033a0", "#f2a800"])],
    "LT": [_H(["#fdb913", "#006a44", "#c1272d"])],
    "EE": [_H(["#0072ce", "#000000", W])],
    "LV": [_H(["#9e3039", W, "#9e3039"], [2, 1, 2])],
    "AT": [_H(["#ed2939", W, "#ed2939"])],
    "HU": [_H(["#ce2939", W, "#477050"])],
    "BG": [_H([W, "#00966e", "#d62612"])],
    "LU": [_H(["#ed2939", W, "#00a1de"])],
    "RS": [_H(["#c6363c", "#0c4076", W])],
    "HR": [_H(["#ff0000", W, "#171796"])],
    "SI": [_H([W, "#005da4", "#ed1c24"])],
    "SK": [_H([W, "#0b4ea2", "#ee1c25"]), _C("#ee1c25", 0.35, 0.5, 0.2)],
    "ES": [_H(["#aa151b", "#f1bf00", "#aa151b"], [1, 2, 1])],
    "PT": [_V(["#006600", "#ff0000"], [2, 3]), _C("#ffcc00", 0.4, 0.5, 0.2)],
    "FI": [_F(W), _NORDIC("#002f6c")],
    "SE": [_F("#006aa7"), _NORDIC("#fecc00")],
    "NO": [_F("#ba0c2f"), _NORDIC(W, wide=True), _NORDIC("#00205b")],
    "DK": [_F("#c8102e"), _NORDIC(W)],
    "IS": [_F("#02529c"), _NORDIC(W, wide=True), _NORDIC("#dc1e35")],
    "CH": [_F("#d52b1e"), _R(W, 0.43, 0.2, 0.57, 0.8), _R(W, 0.31, 0.4, 0.69, 0.6)],
    "GE": [_F(W), _CROSS("#ff0000", 0.18)],
    "GB": [_F("#012169"), _DIAG(W, 0.2), _DIAG("#c8102e", 0.07),
           _CROSS(W, 0.34), _CROSS("#c8102e", 0.2)],
    "US": [_STRIPES("#b22234", W, 13), _R("#3c3b6e", 0, 0, 0.42, 0.54)],
    "CA": [_V(["#d52b1e", W, "#d52b1e"], [1, 2, 1]), _C("#d52b1e", 0.5, 0.5, 0.22)],
    "JP": [_F(W), _C("#bc002d", 0.5, 0.5, 0.3)],
    "KR": [_F(W), _C("#cd2e3a", 0.5, 0.5, 0.25), _C("#0047a0", 0.5, 0.5, 0.25, lower_only=True)],
    "TR": [_F("#e30a17"), _C(W, 0.42, 0.5, 0.25), _C("#e30a17", 0.46, 0.5, 0.2), _C(W, 0.62, 0.5, 0.07)],
    "HK": [_F("#de2910"), _C(W, 0.5, 0.5, 0.26), _C("#de2910", 0.5, 0.5, 0.08)],
    "AL": [_F("#e41e20"), _C("#000000", 0.5, 0.5, 0.26)],
    "KZ": [_F("#00afca"), _C("#fec50c", 0.5, 0.46, 0.22)],
    "CZ": [_H([W, "#d7141a"]), _POLY("#11457e", [(0, 0), (0.5, 0.5), (0, 1)])],
    "IL": [_F(W), _R("#0038b8", 0, 0.1, 1, 0.22), _R("#0038b8", 0, 0.78, 1, 0.9),
           _C("#0038b8", 0.5, 0.5, 0.17), _C(W, 0.5, 0.5, 0.11)],
    "IN": [_H(["#ff9933", W, "#138808"]), _C("#000080", 0.5, 0.5, 0.12)],
    "BR": [_F("#009c3b"), _POLY("#ffdf00", [(0.5, 0.08), (0.93, 0.5), (0.5, 0.92), (0.07, 0.5)]),
           _C("#002776", 0.5, 0.5, 0.22)],
    "AU": [_F("#012169"), _R(W, 0, 0.2, 0.5, 0.3), _R(W, 0.2, 0, 0.3, 0.5),
           _R("#e4002b", 0, 0.22, 0.5, 0.28), _R("#e4002b", 0.22, 0, 0.28, 0.5), _C(W, 0.25, 0.77, 0.1),
           _C(W, 0.78, 0.3, 0.06), _C(W, 0.7, 0.7, 0.06)],
    "SG": [_H(["#ef3340", W]), _C(W, 0.2, 0.25, 0.13), _C("#ef3340", 0.24, 0.25, 0.12)],
    "AE": [_H(["#00732f", W, "#000000"]), _R("#ff0000", 0, 0, 0.25, 1)],
    "CN": [_F("#de2910"), _C("#ffde00", 0.18, 0.27, 0.13)],
    "TW": [_F("#fe0000"), _R("#000095", 0, 0, 0.5, 0.5), _C(W, 0.25, 0.25, 0.12)],
    "VN": [_F("#da251d"), _C("#ffff00", 0.5, 0.5, 0.24)],
    "TH": [_H(["#a51931", W, "#2d2a4a", W, "#a51931"], [1, 1, 2, 1, 1])],
    "MY": [_STRIPES("#cc0001", W, 14), _R("#010066", 0, 0, 0.5, 0.57), _C("#ffcc00", 0.22, 0.28, 0.13)],
    "ID": [_H(["#ce1126", W])],
    "MX": [_V(["#006847", W, "#ce1126"]), _C("#8c5a2b", 0.5, 0.5, 0.13)],
    "AR": [_H(["#74acdf", W, "#74acdf"]), _C("#f6b40e", 0.5, 0.5, 0.11)],
    "GR": [_STRIPES("#0d5eaf", W, 9), _R("#0d5eaf", 0, 0, 0.37, 0.56),
           _R(W, 0.15, 0, 0.22, 0.56), _R(W, 0, 0.22, 0.37, 0.33)],
    "CY": [_F(W), _C("#d57800", 0.5, 0.45, 0.18)],
    "ZA": [_H(["#e03c31", "#007749", "#001489"]), _POLY("#000000", [(0, 0.15), (0.38, 0.5), (0, 0.85)])],
    "AZ": [_H(["#00b5e2", "#ef3340", "#509e2f"]), _C(W, 0.5, 0.5, 0.12), _C("#ef3340", 0.53, 0.5, 0.1)],
    "BY": [_H(["#c8313e", "#4aa657"], [2, 1]), _R(W, 0, 0, 0.11, 1), _R("#c8313e", 0.03, 0, 0.08, 1)],
    "UZ": [_H(["#0099b5", W, "#1eb53a"]), _R("#ce1126", 0, 0.32, 1, 0.35), _R("#ce1126", 0, 0.65, 1, 0.68)],
    "KG": [_F("#e8112d"), _C("#ffef00", 0.5, 0.5, 0.25), _C("#e8112d", 0.5, 0.5, 0.13)],
    "TJ": [_H(["#cc0000", W, "#006600"], [2, 3, 2])],
    "ME": [_F("#d4af37"), _R("#c40308", 0.04, 0.06, 0.96, 0.94), _C("#d4af37", 0.5, 0.5, 0.16)],
    "EG": [_H(["#ce1126", W, "#000000"]), _C("#c09300", 0.5, 0.5, 0.1)],
    "SA": [_F("#006c35"), _R(W, 0.2, 0.62, 0.8, 0.66)],
    "QA": [_F("#8a1538"), _R(W, 0, 0, 0.3, 1)],
    "NZ": [_F("#012169"), _R(W, 0, 0.2, 0.5, 0.3), _R(W, 0.2, 0, 0.3, 0.5),
           _R("#c8102e", 0, 0.22, 0.5, 0.28), _R("#c8102e", 0.22, 0, 0.28, 0.5), _C("#c8102e", 0.78, 0.4, 0.06)],
    "PH": [_H(["#0038a8", "#ce1126"]), _POLY(W, [(0, 0), (0.43, 0.5), (0, 1)]), _C("#fcd116", 0.14, 0.5, 0.1)],
    "BA": [_F("#002395"), _POLY("#fecb00", [(0.27, 0), (0.75, 0), (0.75, 1)])],
    "MK": [_F("#d20000"), _C("#ffe600", 0.5, 0.5, 0.22)],
    "MN": [_V(["#c4272f", "#015197", "#c4272f"])],
    "NG": [_V(["#008751", W, "#008751"])],
    "CL": [_H([W, "#d52b1e"]), _R("#0039a6", 0, 0, 0.33, 0.5)],
    "CO": [_H(["#fcd116", "#003893", "#ce1126"], [2, 1, 1])],
}

# ---------- названия стран ----------

COUNTRY_RU = {
    "RU": "Россия", "NL": "Нидерланды", "DE": "Германия", "FR": "Франция", "IT": "Италия",
    "IE": "Ирландия", "BE": "Бельгия", "RO": "Румыния", "MD": "Молдова", "PL": "Польша",
    "UA": "Украина", "AM": "Армения", "LT": "Литва", "EE": "Эстония", "LV": "Латвия",
    "AT": "Австрия", "HU": "Венгрия", "BG": "Болгария", "LU": "Люксембург", "RS": "Сербия",
    "HR": "Хорватия", "SI": "Словения", "SK": "Словакия", "ES": "Испания", "PT": "Португалия",
    "FI": "Финляндия", "SE": "Швеция", "NO": "Норвегия", "DK": "Дания", "IS": "Исландия",
    "CH": "Швейцария", "GE": "Грузия", "GB": "Великобритания", "US": "США", "CA": "Канада",
    "JP": "Япония", "KR": "Южная Корея", "TR": "Турция", "HK": "Гонконг", "AL": "Албания",
    "KZ": "Казахстан", "CZ": "Чехия", "IL": "Израиль", "IN": "Индия", "BR": "Бразилия",
    "AU": "Австралия", "SG": "Сингапур", "AE": "ОАЭ", "CN": "Китай", "TW": "Тайвань",
    "VN": "Вьетнам", "TH": "Таиланд", "MY": "Малайзия", "ID": "Индонезия", "MX": "Мексика",
    "AR": "Аргентина", "GR": "Греция", "CY": "Кипр", "ZA": "ЮАР", "AZ": "Азербайджан",
    "BY": "Беларусь", "UZ": "Узбекистан", "KG": "Киргизия", "TJ": "Таджикистан",
    "ME": "Черногория", "EG": "Египет", "SA": "Саудовская Аравия", "QA": "Катар",
    "NZ": "Новая Зеландия", "PH": "Филиппины", "BA": "Босния", "MK": "Сев. Македония",
    "MN": "Монголия", "NG": "Нигерия", "CL": "Чили", "CO": "Колумбия",
}

# Ключевые слова (подстроки, нижний регистр) → код страны
_KEYWORDS = {
    "NL": ["нидерланд", "голланд", "netherland", "holland", "amsterdam", "амстердам"],
    "DE": ["герман", "germany", "deutschland", "frankfurt", "франкфурт", "berlin", "берлин", "nuremberg", "falkenstein"],
    "FI": ["финлянд", "finland", "helsinki", "хельсинки"],
    "LV": ["латви", "latvia", "riga", "рига"],
    "EE": ["эстони", "estonia", "tallinn", "таллин"],
    "LT": ["литв", "lithuania", "vilnius", "вильнюс"],
    "PL": ["польш", "poland", "warsaw", "варшав"],
    "FR": ["франци", "france", "paris", "париж", "gravelines", "roubaix"],
    "SE": ["швеци", "sweden", "stockholm", "стокгольм"],
    "NO": ["норвег", "norway", "oslo"],
    "DK": ["дания", "дании", "denmark", "copenhagen"],
    "CH": ["швейцар", "switzerland", "zurich", "цюрих"],
    "AT": ["австри", "austria", "vienna", "вена"],
    "CZ": ["чехи", "czech", "prague", "праг"],
    "GB": ["британ", "англи", "united kingdom", "england", "london", "лондон", "britain"],
    "US": ["сша", "америк", "united states", "america", "new york", "нью-йорк", "los angeles",
           "california", "miami", "chicago", "dallas", "seattle", "virginia"],
    "CA": ["канад", "canada", "toronto", "торонто", "montreal"],
    "TR": ["турци", "turkey", "türkiye", "turkiye", "istanbul", "стамбул"],
    "KZ": ["казахстан", "kazakhstan", "almaty", "алматы", "astana", "астана"],
    "AM": ["армени", "armenia", "yerevan", "ереван"],
    "GE": ["грузия", "грузии", "georgia", "tbilisi", "тбилиси"],
    "MD": ["молдов", "moldova", "chisinau", "кишин"],
    "RU": ["росси", "russia", "moscow", "москв", "петербург", "petersburg"],
    "UA": ["украин", "ukraine", "kyiv", "киев"],
    "JP": ["япони", "japan", "tokyo", "токио", "osaka"],
    "HK": ["гонконг", "hong kong", "hong-kong", "hongkong"],
    "SG": ["сингапур", "singapore"],
    "KR": ["корея", "корей", "korea", "seoul", "сеул"],
    "IN": ["индия", "индии", "india", "mumbai", "мумбаи"],
    "AE": ["оаэ", "эмират", "emirates", "dubai", "дубай"],
    "IL": ["израил", "israel", "tel aviv"],
    "ES": ["испани", "spain", "madrid", "мадрид"],
    "IT": ["итали", "italy", "milan", "милан", "roma"],
    "BE": ["бельги", "belgium", "brussels"],
    "IE": ["ирланд", "ireland", "dublin"],
    "BG": ["болгар", "bulgaria", "sofia"],
    "RO": ["румын", "romania", "bucharest"],
    "HU": ["венгр", "hungary", "budapest"],
    "RS": ["серби", "serbia", "belgrade", "белград"],
    "AL": ["албан", "albania", "tirana"],
    "AU": ["австрали", "australia", "sydney", "сидней"],
    "BR": ["бразил", "brazil", "sao paulo"],
    "AR": ["аргентин", "argentina"],
    "LU": ["люксембург", "luxembourg"],
    "PT": ["португал", "portugal", "lisbon", "лиссабон"],
    "GR": ["греци", "greece", "athens"],
    "CY": ["кипр", "cyprus"],
    "IS": ["исланд", "iceland"],
    "MX": ["мексик", "mexico"],
    "CN": ["китай", "china"],
    "TW": ["тайван", "taiwan"],
    "VN": ["вьетнам", "vietnam"],
    "TH": ["таиланд", "тайланд", "thailand", "bangkok"],
    "MY": ["малайзи", "malaysia"],
    "ID": ["индонез", "indonesia", "jakarta"],
    "ZA": ["юар", "south africa"],
    "AZ": ["азербайдж", "azerbaijan", "baku", "баку"],
    "BY": ["беларус", "белорус", "belarus", "minsk", "минск"],
    "UZ": ["узбекист", "uzbekistan", "tashkent"],
    "KG": ["киргиз", "кыргыз", "kyrgyz", "bishkek"],
    "SK": ["словаки", "slovakia"],
    "SI": ["словени", "slovenia"],
    "HR": ["хорвати", "croatia"],
    "ME": ["черногор", "montenegro"],
    "EG": ["египет", "egypt"],
    "SA": ["саудов", "saudi"],
    "QA": ["катар", "qatar"],
    "NZ": ["новая зеланд", "new zealand"],
}
# Короткие коды, которые ищем только как отдельные слова (иначе ложные совпадения)
_SHORT = {"usa": "US", "uk": "GB", "uae": "AE", "nyc": "US"}

_FLAG_RE = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


def detect_country(name: str, address: str = "") -> str | None:
    m = _FLAG_RE.search(name or "")
    if m:
        code = "".join(chr(ord(c) - 0x1F1E6 + 65) for c in m.group())
        return "GB" if code == "UK" else code
    text = f"{name} {address}".lower().replace(".", " ").replace("-", " ").replace("_", " ")
    for code, words in _KEYWORDS.items():
        if any(w in text for w in words):
            return code
    for word, code in _SHORT.items():
        if re.search(rf"\b{word}\b", text):
            return code
    # «Latvia LV», «[NL] Amsterdam», «DE-1» — двухбуквенный код отдельным словом в имени
    for tok in re.findall(r"\b([A-Z]{2})\b", name or ""):
        if tok in COUNTRY_RU:
            return tok
    return None


def country_name(code: str | None) -> str:
    return COUNTRY_RU.get(code or "", "")


def clean_name(name: str) -> str:
    """Убираем эмодзи (Tk на Windows рисует их квадратиками) и лишние пробелы."""
    s = _FLAG_RE.sub("", name or "")
    s = "".join(ch for ch in s if ord(ch) <= 0xFFFF and ch not in "️‍⃣")
    s = re.sub(r"\[\s+", "[", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -|·•")
    return s


# ---------- отрисовка ----------

_cache: dict = {}


def image(master, code: str | None, w: int, h: int):
    """tk.PhotoImage с флагом или None, если флага нет в таблице."""
    if not code or code not in FLAGS:
        return None
    key = (code, w, h)
    if key in _cache:
        return _cache[key]
    import tkinter as tk
    ops = FLAGS[code]
    rows = []
    for y in range(h):
        py = (y + 0.5) / h
        row = []
        for x in range(w):
            px = (x + 0.5) / w
            c = "#808080"
            for op in ops:
                c = op(px, py, c)
            row.append(c)
        rows.append("{" + " ".join(row) + "}")
    img = tk.PhotoImage(master=master, width=w, height=h)
    img.put(" ".join(rows))
    _cache[key] = img
    return img


def render_grid(code: str, w: int, h: int) -> list[list[str]]:
    """То же, но в виде сетки цветов (для превью и тестов)."""
    ops = FLAGS[code]
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            c = "#808080"
            for op in ops:
                c = op((x + 0.5) / w, (y + 0.5) / h, c)
            row.append(c)
        out.append(row)
    return out
