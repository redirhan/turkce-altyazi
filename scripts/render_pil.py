"""Altyazıyı PIL ile çizer (ffmpeg'de libass yoksa yedek yol). drawtext KULLANMAZ.
Her hücre (karaokede her kelime durumu) bir kez saydam PNG olarak çizilir, kareye alfa ile bindirilir."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import styles as S
from layout import Measure, place


def _rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def render_state(cell: Dict, style: Dict, m: Measure, active: Optional[int] = None,
                 y_frac: Optional[float] = None) -> Tuple[Image.Image, int, int]:
    """Bir hücre durumunu RGBA olarak çizer. Dönüş: (görüntü, sol x, üst y) kare koordinatında."""
    p = place(cell, m, y_frac)
    sc = cell.get("scale", 1.0)
    px = max(8, int(round(m.px * sc)))
    font = ImageFont.truetype(m.font_path, px) if sc != 1.0 else m.font
    k = m.k * sc
    outline = int(round(style["outline"] * k))
    shadow = style["shadow"] * k
    blur = style.get("shadow_blur", 0) * k
    pad = int(outline + shadow + blur * 3 + 8)
    x0 = int(p["left"]) - pad
    y0 = int(p["top"]) - pad
    wd = int(p["right"] - p["left"]) + 2 * pad
    ht = int(p["bottom"] - p["top"]) + 2 * pad
    lh = p["line_h"]

    def word_items():
        line_of = {}
        for li, ln in enumerate(cell["lines"]):
            for j in ln:
                line_of[j] = li
        for pw in p["words"]:
            j = pw["i"]
            y_mid = p["top"] + line_of[j] * lh + lh / 2
            yield j, pw["x"] - x0, y_mid - y0

    # şekil maskesi (dolgu + kenar) -> gölge ve kenar katmanları
    full = Image.new("L", (wd, ht), 0)
    dfull = ImageDraw.Draw(full)
    for j, x, y in word_items():
        dfull.text((x, y), cell["words"][j]["w"], font=font, fill=255, anchor="lm",
                   stroke_width=outline, stroke_fill=255)
    img = Image.new("RGBA", (wd, ht), (0, 0, 0, 0))
    if style.get("shadow_alpha", 0) > 0 and shadow > 0:
        sh = Image.new("L", (wd, ht), 0)
        sh.paste(full, (0, int(round(shadow))))
        if blur > 0:
            sh = sh.filter(ImageFilter.GaussianBlur(blur))
        sh = sh.point(lambda v: int(v * style["shadow_alpha"]))
        img = Image.alpha_composite(img, Image.merge("RGBA", (*[Image.new("L", (wd, ht), 0)] * 3, sh)))
    if outline > 0 and style["outline_alpha"] > 0:
        ol = full
        if style["outline_alpha"] < 1:
            ol = full.filter(ImageFilter.GaussianBlur(max(0.6, blur / 3)))
        ol = ol.point(lambda v: int(v * style["outline_alpha"]))
        r, g, b = _rgb(style["outline_color"])
        img = Image.alpha_composite(img, Image.merge("RGBA", (Image.new("L", (wd, ht), r), Image.new("L", (wd, ht), g),
                                                              Image.new("L", (wd, ht), b), ol)))
    # dolgu: kelime kelime renk
    fill = Image.new("RGBA", (wd, ht), (0, 0, 0, 0))
    dfill = ImageDraw.Draw(fill)
    for j, x, y in word_items():
        w = cell["words"][j]
        col, alpha = style["color"], 1.0
        if style.get("karaoke") and active is not None:
            if j == active:
                col = style["active_color"]
            elif j > active:
                alpha = style.get("upcoming_alpha", 0.6)
        elif w.get("kw") and style.get("keyword_color"):
            col = style["keyword_color"]
        dfill.text((x, y), w["w"], font=font, fill=(*_rgb(col), int(255 * alpha)), anchor="lm")
    img = Image.alpha_composite(img, fill)
    return img, x0, y0


def build_states(cells: List[Dict], style: Dict, W: int, H: int, y_frac: Optional[float] = None) -> List[Dict]:
    """Zaman çizelgesi: [{t0, t1, img(RGBA), x, y, pop, fade_in, fade_out}]"""
    m = Measure(style, W, H)
    out = []
    fade = style.get("fade", 0.0)
    for c in cells:
        if style.get("karaoke"):
            ws = c["words"]
            seq = []
            for i, w in enumerate(ws):
                t0 = c["start"] if i == 0 else w["start"]
                t1 = ws[i + 1]["start"] if i + 1 < len(ws) else c["end"]
                if t1 - t0 >= 0.01:
                    seq.append((t0, t1, i))
            for si, (t0, t1, i) in enumerate(seq):
                img, x, y = render_state(c, style, m, active=i, y_frac=y_frac)
                out.append({"t0": t0, "t1": t1, "img": img, "x": x, "y": y, "pop": False,
                            "fade_in": fade if si == 0 else 0, "fade_out": fade if si == len(seq) - 1 else 0})
        else:
            img, x, y = render_state(c, style, m, y_frac=y_frac)
            out.append({"t0": c["start"], "t1": c["end"], "img": img, "x": x, "y": y,
                        "pop": bool(style.get("pop")), "fade_in": fade, "fade_out": fade})
    return out


def still(cells: List[Dict], style: Dict, background: Image.Image, t: float, y_frac: Optional[float] = None) -> Image.Image:
    """Tek kare önizleme (PNG): verilen zamandaki altyazı arka plana bindirilir."""
    W, H = background.size
    bg = background.convert("RGBA")
    for s in build_states(cells, style, W, H, y_frac):
        if s["t0"] <= t < s["t1"]:
            bg.alpha_composite(s["img"], (max(0, s["x"]), max(0, s["y"])))
    return bg.convert("RGB")
