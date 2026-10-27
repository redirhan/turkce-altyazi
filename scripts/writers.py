"""SRT, ASS (stilli) ve JSON çıktıları. ASS, PIL yerleşimiyle aynı satır bölmeyi ve konumları kullanır;
böylece ffmpeg'in ass filtresiyle yakılan video ile PIL yedeğiyle yakılan video aynı düzende olur."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

import styles as S
from layout import Measure, place


def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000:d}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def to_srt(cells: List[Dict], use_raw: bool = True) -> str:
    """SRT: platformlara (YouTube, Instagram altyazı dosyası) yüklenecek metin. Varsayılan olarak
    stilin büyük harfi değil, düzeltilmiş cümle düzeni kullanılır; satır bölme aynıdır."""
    out = []
    for i, c in enumerate(cells, 1):
        key = "raw" if use_raw else "w"
        text = "\n".join(" ".join(c["words"][j][key] for j in ln) for ln in c["lines"])
        out.append(f"{i}\n{_srt_time(c['start'])} --> {_srt_time(c['end'])}\n{text}\n")
    return "\n".join(out)


def _bgr(hex_color: str, alpha: float = 1.0) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = int(round((1 - alpha) * 255))
    return f"&H{a:02X}{b}{g}{r}".upper().replace("&H", "&H")


def _color_tag(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _esc(t: str) -> str:
    return t.replace("\\", "/").replace("{", "(").replace("}", ")")


def to_ass(cells: List[Dict], style: Dict, W: int, H: int, y_frac: Optional[float] = None) -> str:
    m = Measure(style, W, H)
    asc, desc = m.font.getmetrics()
    fs = asc + desc                      # ASS yazı boyu = satır yüksekliği (VSFilter/libass anlamı)
    k = m.k
    name = style["key"]
    prim = _bgr(style["color"])
    outl = _bgr(style["outline_color"], style["outline_alpha"]) if style["outline"] else _bgr("#000000", 0)
    back = _bgr("#000000", style.get("shadow_alpha", 0.5))
    head = [
        "[Script Info]",
        "; turkce-altyazi (Redirhan Studio, MIT) ile üretildi",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: {name},{style['family']},{fs},{prim},{prim},{outl},{back},0,0,0,0,100,100,0,0,1,"
        f"{style['outline'] * k:.1f},{style['shadow'] * k:.1f},5,0,0,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    ev = []
    fade = int(style.get("fade", 0) * 1000)
    blur = style.get("shadow_blur", 0) * k
    for c in cells:
        p = place(c, m, y_frac)
        sc = int(round(c.get("scale", 1.0) * 100))
        states = []
        if style.get("karaoke"):
            ws = c["words"]
            for i, w in enumerate(ws):
                t0 = c["start"] if i == 0 else w["start"]
                t1 = ws[i + 1]["start"] if i + 1 < len(ws) else c["end"]
                if t1 - t0 >= 0.01:
                    states.append((t0, t1, i))
        else:
            states.append((c["start"], c["end"], None))
        for si, (t0, t1, active) in enumerate(states):
            for li, ln in enumerate(c["lines"]):
                y = p["top"] + li * p["line_h"] + p["line_h"] / 2
                tags = [f"\\an5\\pos({W / 2:.0f},{y:.0f})"]
                if sc != 100:
                    tags.append(f"\\fscx{sc}\\fscy{sc}")
                if blur:
                    tags.append(f"\\blur{min(blur, 4):.1f}" if style["outline_alpha"] < 1 else "\\blur0.6")
                if fade and not style.get("karaoke"):
                    tags.append(f"\\fad({fade},{fade})")
                elif fade and style.get("karaoke"):
                    fi = fade if si == 0 else 0
                    fo = fade if si == len(states) - 1 else 0
                    if fi or fo:
                        tags.append(f"\\fad({fi},{fo})")
                if style.get("pop"):
                    tags.append(f"\\fscx{int(sc * 0.88)}\\fscy{int(sc * 0.88)}\\t(0,90,\\fscx{sc}\\fscy{sc})")
                parts = []
                for j in ln:
                    w = c["words"][j]
                    txt = _esc(w["w"])
                    if style.get("karaoke") and active is not None:
                        if j == active:
                            parts.append(f"{{\\c{_color_tag(style['active_color'])}\\1a&H00&}}{txt}")
                        elif j > active:
                            a = int(round((1 - style.get("upcoming_alpha", 0.6)) * 255))
                            parts.append(f"{{\\c{_color_tag(style['color'])}\\1a&H{a:02X}&}}{txt}")
                        else:
                            parts.append(f"{{\\c{_color_tag(style['color'])}\\1a&H00&}}{txt}")
                    elif w.get("kw") and style.get("keyword_color"):
                        parts.append(f"{{\\c{_color_tag(style['keyword_color'])}}}{txt}{{\\c{_color_tag(style['color'])}}}")
                    else:
                        parts.append(txt)
                ev.append(f"Dialogue: 0,{_ass_time(t0)},{_ass_time(t1)},{name},,0,0,0,,{{{''.join(tags)}}}{' '.join(parts)}")
    return "\n".join(head + ev) + "\n"


def to_json(cells: List[Dict], style: Dict, W: int, H: int, meta: Dict, y_frac: Optional[float] = None) -> str:
    """HyperFrames / Remotion / kendi oynatıcın için: hücreler, kelimeler, satırlar ve piksel konumları."""
    m = Measure(style, W, H)
    out = []
    for c in cells:
        p = place(c, m, y_frac)
        out.append({
            "start": c["start"], "end": c["end"], "text": c["text"], "scale": c.get("scale", 1.0),
            "lines": c["lines"],
            "words": [{"w": w["w"], "raw": w["raw"], "start": w["start"], "end": w["end"], "kw": bool(w.get("kw")),
                       "x": round(pw["x"], 1), "y": round(pw["y"], 1), "width": round(pw["w"], 1)}
                      for w, pw in zip(c["words"], p["words"])],
            "box": {k: round(p[k], 1) for k in ("left", "top", "right", "bottom")},
        })
    return json.dumps({"style": style["key"], "frame": [W, H], "font": style["font"], "font_px": m.px,
                       "meta": meta, "cells": out}, ensure_ascii=False, indent=1)
