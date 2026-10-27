"""Kelime zamanlarından altyazı hücreleri ve Türkçe satır bölme.

Kurallar (kısa video ölçümleri + Türkçe dizgi alışkanlıkları):
- Hücre kelime zamanıyla açılır/kapanır; 0,3 s ve üstü duraklamada, cümle sonunda, kesimde yeni hücre.
- 0,35 s'den kısa hücre yanıp söner: bir sonraki kelimeyi yanına alır.
- Kısa boşlukta (<= 0,25 s) hücre bir sonrakine kadar ekranda kalır (göz kırpması yok).
- Satır en fazla 2; genişlik güvenli alanın içinde (sağdaki ikon sütunu ve alttaki açıklama satırı dışı).
- Türkçe satır/hücre bölme:
    * "ve, ile, veya, ama, bir, yüzde, en, çok..." satır ya da hücre SONUNDA kalmaz (sonraki satıra geçer),
    * "de/da, ki, mi/mı/mu/mü, gibi, kadar, için" satır ya da hücre BAŞINA düşmez (önceki kelimeyle kalır),
    * sayı ile birimi/ardındaki kelime ayrılmaz ("%50 indirim", "5 dakika", "100 TL"),
    * kesme işaretli ek zaten kelimeyle tek parçadır ("İstanbul'da"),
    * iki satırda alt satır üst satırdan kısa olmasın (piramit), virgülden sonra bölmek tercih edilir.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import tr_text
from tr_text import apply_case, norm_word, tr_lower, tr_upper
import styles as S

PAUSE_BREAK = 0.30
MIN_CELL = 0.35
HOLD_GAP = 0.25
TAIL = 0.15
MAX_CPS = 20.0       # saniyede karakter; reels için üst sınır (Netflix TR yetişkin: 17)

BAD_END = {"ve", "ile", "veya", "ya", "ama", "fakat", "ancak", "çünkü", "bir", "en", "çok", "daha", "yüzde",
           "bu", "şu", "her", "hiç", "hem", "ne", "o"}
CLITIC = {"de", "da", "ki", "mi", "mı", "mu", "mü", "misin", "mısın", "musun", "müsün", "miyim", "mıyım",
          "miyiz", "mıyız", "misiniz", "mısınız", "midir", "mıdır", "mudur", "müdür", "miydi", "mıydı",
          "muydu", "müydü", "gibi", "kadar", "için", "değil"}
UNITS = {"tl", "lira", "dolar", "euro", "avro", "kuruş", "dakika", "saniye", "saat", "gün", "hafta", "ay", "yıl",
         "kilo", "kg", "gram", "gr", "metre", "km", "cm", "mm", "litre", "lt", "derece", "kişi", "adet", "bin",
         "milyon", "milyar", "kat", "puan"}
_END_PUNCT = re.compile(r"[.!?…]$")
_COMMA = re.compile(r"[,;:]$")


def _bare(w: str) -> str:
    return re.sub(r"[^\wçğıöşü%]", "", tr_lower(w))


def _stem(w: str) -> str:
    return _bare(re.split(r"['’]", w)[0])


# ---------------------------------------------------------------- ölçüm
class Measure:
    """PIL ile piksel genişliği. Stil + kare boyutuna göre font boyu."""

    def __init__(self, style: Dict, w: int, h: int, size_mul: float = 1.0):
        from PIL import ImageFont
        self.style, self.W, self.H = style, w, h
        self.k = S.scale_for(w, h) * size_mul
        self.px = max(10, int(round(style["size"] * self.k)))
        self.font_path = str(S.FONTS / style["font"])
        self.font = ImageFont.truetype(self.font_path, self.px)
        self.space = self.font.getlength(" ")
        safe = S.safe_for(w, h)
        self.safe = safe
        half = 0.5 - max(safe["left"], safe["right"])
        self.max_w = w * half * 2
        asc, desc = self.font.getmetrics()
        self.line_h = (asc + desc) * (1 + style.get("line_gap", 0.1))

    @lru_cache(maxsize=4096)
    def width(self, text: str) -> float:
        return self.font.getlength(text)

    def line_width(self, toks: Sequence[str]) -> float:
        return sum(self.width(t) for t in toks) + self.space * max(0, len(toks) - 1)


# ---------------------------------------------------------------- satır bölme
def best_split(toks: Sequence[str], m: Measure, max_lines: int, line_chars: int) -> Tuple[List[List[int]], float, bool]:
    """Kelimeleri 1-2 satıra böler. Dönüş: (satır başına kelime indeksleri, maliyet, sığdı mı)."""
    n = len(toks)
    one_w = m.line_width(toks)
    one_c = len(" ".join(toks))
    if n <= 1 or (one_w <= m.max_w and one_c <= line_chars) or max_lines < 2:
        return [list(range(n))], one_w, one_w <= m.max_w * 1.001 or n <= 1
    best = None
    for k in range(1, n):
        a, b = toks[:k], toks[k:]
        wa, wb = m.line_width(a), m.line_width(b)
        cost = max(wa, wb)
        pen = 0.0
        if _bare(a[-1]) in BAD_END:
            pen += 0.35
        if _bare(b[0]) in CLITIC:
            pen += 0.45
        if re.search(r"\d", a[-1]):        # sayı, ardındaki kelimeden (birim, isim) ayrılmaz
            pen += 0.4
        if _COMMA.search(a[-1]) or _END_PUNCT.search(a[-1]):
            pen -= 0.12
        if wa > wb:
            pen += 0.06 * (wa - wb) / max(1.0, m.max_w) * 4
        fits = wa <= m.max_w and wb <= m.max_w and len(" ".join(a)) <= line_chars * 1.25 and len(" ".join(b)) <= line_chars * 1.25
        total = cost + pen * m.max_w * 0.25 + (0 if fits else m.max_w * 10)
        if best is None or total < best[1]:
            best = ([list(range(k)), list(range(k, n))], total, fits)
    return best


# ---------------------------------------------------------------- anahtar kelime
OZEL = set(tr_text.OZEL)


def keyword_flags(words: List[Dict], phrases: Iterable[str] = (), auto: bool = True) -> List[bool]:
    """Vurgulanacak kelimeler: kullanıcı listesi + (auto) sayılar/yüzdeler/para ve özel adlar."""
    flags = [False] * len(words)
    norms = [norm_word(w["w"]) for w in words]
    for ph in phrases:
        target = [norm_word(t) for t in ph.split()]
        if not target:
            continue
        for i in range(len(norms) - len(target) + 1):
            if [re.split(r"['’]", x)[0] for x in norms[i:i + len(target)]] == [re.split(r"['’]", t)[0] for t in target] \
                    or norms[i:i + len(target)] == target:
                for j in range(i, i + len(target)):
                    flags[j] = True
    if auto:
        sent_start = True
        for i, w in enumerate(words):
            t = w["w"]
            core = re.split(r"['’]", re.sub(r"^[^\wÇĞİÖŞÜçğıöşü%]+", "", t))[0]
            stem = tr_lower(re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", core))
            if re.search(r"\d", t) or "%" in t:
                flags[i] = True
            elif stem in OZEL:
                flags[i] = True
            elif core[:1].isupper() and not sent_start and stem not in tr_text.SIK and len(stem) > 2:
                flags[i] = True
            sent_start = bool(_END_PUNCT.search(t))
    return flags


# ---------------------------------------------------------------- hücreler
def _display(w: str, case: str) -> str:
    if case == "naive_upper":
        # bilerek hatalı (demo "önce"): küçük harfli ham transkript (Vosk, whisper normalizer, "küçük harf"
        # temizliği yapan araçlar) + Türkçe bilmeyen str.upper() / toUpperCase(): istanbul -> ISTANBUL
        return tr_lower(w).upper()
    return apply_case(w, case)


def build_cells(words: List[Dict], style: Dict, W: int, H: int, keywords: Iterable[str] = (),
                auto_keywords: bool = True, size_mul: float = 1.0) -> List[Dict]:
    """Kelimeler -> hücreler [{start, end, words:[{w, raw, start, end, kw}], lines:[[i..]], scale}]."""
    m = Measure(style, W, H, size_mul)
    case = style["case"]
    kws = keyword_flags(words, keywords, auto_keywords) if style.get("keyword_color") else [False] * len(words)
    disp = [dict(w, raw=w["w"], w=_display(w["w"], case), kw=k) for w, k in zip(words, kws)]
    max_words, max_lines, lc = style["max_words"], style["max_lines"], style["line_chars"]

    def fits(group: List[Dict]) -> bool:
        if len(group) > max_words:
            return False
        lines, _, ok = best_split([g["w"] for g in group], m, max_lines, lc)
        return ok and all(len(" ".join(group[i]["w"] for i in ln)) <= lc * 1.25 or len(ln) == 1 for ln in lines)

    groups: List[List[Dict]] = []
    for w in disp:
        cur = groups[-1] if groups else None
        if cur:
            last = cur[-1]
            pause = w["start"] - last["end"]
            hard = pause >= PAUSE_BREAK or bool(_END_PUNCT.search(last["raw"])) or w.get("cut_before")
            soft_comma = bool(_COMMA.search(last["raw"])) and len(cur) >= 2 and max_words > 3
            if not hard and not soft_comma and fits(cur + [w]):
                cur.append(w)
                continue
            if not hard and _bare(w["raw"]) in CLITIC and len(cur) < max_words + 1:
                tmp = cur + [w]
                lines, _, ok = best_split([g["w"] for g in tmp], m, max_lines, lc * 2)
                if ok:                      # "de/da, ki, mi" önceki kelimeden kopmaz
                    cur.append(w)
                    continue
            if not hard and len(cur) > 1 and _bare(last["raw"]) in BAD_END:
                groups.append([cur.pop(), w])      # "ve", "bir", "yüzde" hücre sonunda kalmaz
                continue
            if not hard and len(cur) > 1 and _bare(w["raw"]) in CLITIC:
                groups.append([cur.pop(), w])
                continue
        groups.append([w])

    # çok kısa hücreleri birleştir
    merged: List[List[Dict]] = []
    for g in groups:
        dur = g[-1]["end"] - g[0]["start"]
        if merged and dur < MIN_CELL and g[0]["start"] - merged[-1][-1]["end"] < PAUSE_BREAK \
                and not _END_PUNCT.search(merged[-1][-1]["raw"]) and fits(merged[-1] + g):
            merged[-1].extend(g)
        else:
            merged.append(g)
    for i in range(len(merged) - 1):
        g, nxt = merged[i], merged[i + 1]
        if g and g[-1]["end"] - g[0]["start"] < MIN_CELL and nxt and fits(g + nxt[:1]) and len(nxt) > 1 \
                and nxt[0]["start"] - g[-1]["end"] < PAUSE_BREAK:
            g.append(nxt.pop(0))
    merged = [g for g in merged if g]

    cells = []
    for g in merged:
        toks = [x["w"] for x in g]
        lines, _, ok = best_split(toks, m, max_lines, lc)
        scale = 1.0
        widest = max(m.line_width([toks[i] for i in ln]) for ln in lines)
        if widest > m.max_w:
            scale = round(m.max_w / widest * 0.98, 3)
        cells.append({"start": g[0]["start"], "end": g[-1]["end"], "words": g, "lines": lines, "scale": scale})
    for a, b in zip(cells, cells[1:]):
        gap = b["start"] - a["end"]
        a["end"] = b["start"] if gap <= HOLD_GAP else a["end"] + min(TAIL, gap)
    if cells:
        cells[-1]["end"] += TAIL
    for c in cells:
        c["start"], c["end"] = round(c["start"], 3), round(c["end"], 3)
        c["text"] = "\n".join(" ".join(c["words"][i]["w"] for i in ln) for ln in c["lines"])
    return cells


# ---------------------------------------------------------------- yerleşim
def place(cell: Dict, m: Measure, y_frac: Optional[float] = None) -> Dict:
    """Hücrenin kare üzerindeki yerleşimi: her kelimenin sol-üst x,y'si ve blok kutusu.
    Blok yatayda ortalı; dikeyde merkezi y_frac'ta, ama güvenli alanın içinde tutulur."""
    W, H, safe = m.W, m.H, m.safe
    sc = cell.get("scale", 1.0)
    space = m.space * sc
    lh = m.line_h * sc
    n = len(cell["lines"])
    block_h = lh * n
    yc = (y_frac if y_frac is not None else safe["y"]) * H
    top = yc - block_h / 2
    top = min(top, H * (1 - safe["bottom"]) - block_h)
    top = max(top, H * safe["top"])
    words = []
    for li, ln in enumerate(cell["lines"]):
        toks = [cell["words"][i]["w"] for i in ln]
        lw = (sum(m.width(t) for t in toks) + m.space * (len(toks) - 1)) * sc
        x = (W - lw) / 2
        y = top + li * lh
        for i in ln:
            ww = m.width(cell["words"][i]["w"]) * sc
            words.append({"i": i, "x": x, "y": y, "w": ww})
            x += ww + space
    return {"words": sorted(words, key=lambda d: d["i"]), "top": top, "bottom": top + block_h,
            "left": min(d["x"] for d in words), "right": max(d["x"] + d["w"] for d in words),
            "line_h": lh, "px": m.px * sc}


def check_cells(cells: List[Dict], style: Dict, W: int, H: int, y_frac: Optional[float] = None) -> List[Dict]:
    """Bulgu listesi: güvenli alan taşması, 2'den fazla satır, yanıp sönen hücre, hızlı okuma, çakışma."""
    m = Measure(style, W, H)
    out = []
    for c in cells:
        p = place(c, m, y_frac)
        dur = c["end"] - c["start"]
        chars = len(c["text"].replace("\n", " "))
        if p["left"] < W * m.safe["left"] - 1 or p["right"] > W * (1 - m.safe["left"]) + 1:
            out.append({"seviye": "hata", "kod": "guvenli_alan_yatay", "zaman": c["start"], "metin": c["text"]})
        if p["bottom"] > H * (1 - m.safe["bottom"]) + 1 or p["top"] < H * m.safe["top"] - 1:
            out.append({"seviye": "hata", "kod": "guvenli_alan_dikey", "zaman": c["start"], "metin": c["text"]})
        if len(c["lines"]) > 2:
            out.append({"seviye": "hata", "kod": "ikiden_fazla_satir", "zaman": c["start"], "metin": c["text"]})
        if dur < 0.25:
            out.append({"seviye": "uyari", "kod": "yanip_sonme", "zaman": c["start"], "metin": c["text"]})
        if dur > 0 and chars / dur > MAX_CPS and chars > 12:
            out.append({"seviye": "uyari", "kod": "hizli_okuma", "zaman": c["start"],
                        "metin": f"{c['text']} ({chars / dur:.0f} karakter/sn)"})
        if c.get("scale", 1) < 1:
            out.append({"seviye": "bilgi", "kod": "kucultuldu", "zaman": c["start"], "metin": f"{c['text']} (x{c['scale']})"})
        if tr_text.has_wrong_case(c["text"]) and style["case"] != "naive_upper":
            out.append({"seviye": "hata", "kod": "turkce_buyuk_harf", "zaman": c["start"], "metin": c["text"]})
    for a, b in zip(cells, cells[1:]):
        if b["start"] < a["end"] - 1e-6:
            out.append({"seviye": "hata", "kod": "cakisma", "zaman": b["start"], "metin": b["text"]})
    return out
