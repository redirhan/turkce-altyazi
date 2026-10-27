"""Dolgu sözcüğü ve duraklama kırpma ÖNERİLERİ. Varsayılan olarak hiçbir şey kesilmez; öneriler
rapor olarak yazılır. `trim --uygula` önerilen aralıkları gerçekten çıkarır ve kelime zamanlarını
yeni videoya göre kaydırır (altyazı kayması olmaz)."""
from __future__ import annotations

import re
import subprocess
from typing import Dict, List, Tuple

from tr_text import norm_word, tr_lower

# saf dolgu: her zaman önerilir (yüksek güven)
SAF = re.compile(r"^(ı+h*|ıı+m*|ı+mm*|e{2,}h*|eh+|ee+m*|ö{2,}|a{2,}h*|hı+m+|h+m+|mm+|ı+hı+|e+hm*|hmm+)$")
# söylem dolgusu: yalnız virgülle/duraklamayla ayrılmışsa önerilir (orta güven)
SOYLEM = {"yani", "şey", "şeyh", "hani", "işte", "falan", "filan", "açıkçası", "yaa", "ee", "e", "ha"}
LONG_PAUSE = 0.60      # s: bundan uzun boşluk kısaltılmak üzere önerilir
KEEP_PAUSE = 0.30      # s: kısaltılan boşluğun kalacak uzunluğu
PAD = 0.04             # s: kesim kenarında nefes payı


def _clean(w: str) -> str:
    return norm_word(w).strip("'’")


def suggest(words: List[Dict], long_pause: float = LONG_PAUSE, keep_pause: float = KEEP_PAUSE) -> List[Dict]:
    """Öneriler: [{tur, start, end, metin, neden, guven}] (zaman sırasıyla)."""
    out: List[Dict] = []
    n = len(words)
    for i, w in enumerate(words):
        c = _clean(w["w"])
        prev_gap = w["start"] - words[i - 1]["end"] if i else 1.0
        next_gap = words[i + 1]["start"] - w["end"] if i + 1 < n else 1.0
        sent_start = i == 0 or bool(re.search(r"[.!?…]$", words[i - 1]["w"]))
        if SAF.match(c):
            out.append({"tur": "dolgu", "start": w["start"], "end": w["end"], "metin": w["w"],
                        "neden": "saf dolgu sesi", "guven": "yuksek"})
        elif c in SOYLEM and (w["w"].rstrip().endswith(",") or next_gap >= 0.25 or prev_gap >= 0.25
                              or (sent_start and c in ("şey", "şeyh", "yani", "işte", "hani"))):
            out.append({"tur": "dolgu", "start": w["start"], "end": w["end"], "metin": w["w"],
                        "neden": "söylem dolgusu (ayrık)" + (" — ASR 'şey'i 'Şeyh' yazmış olabilir" if c == "şeyh" else ""),
                        "guven": "orta"})
        if i + 1 < n:
            a, b = _clean(w["w"]), _clean(words[i + 1]["w"])
            if a and a == b and not re.search(r"\d", a) and len(a) > 1:
                out.append({"tur": "tekrar", "start": w["start"], "end": words[i + 1]["start"], "metin": f"{w['w']} {words[i + 1]['w']}",
                            "neden": "aynı kelime art arda (kekeleme)", "guven": "orta"})
            gap = words[i + 1]["start"] - w["end"]
            if gap > long_pause:
                cut0 = w["end"] + keep_pause / 2
                cut1 = words[i + 1]["start"] - keep_pause / 2
                out.append({"tur": "duraklama", "start": round(cut0, 3), "end": round(cut1, 3),
                            "metin": f"{gap:.2f} s boşluk", "neden": f"{long_pause:.2f} s'den uzun duraklama -> {keep_pause:.2f} s",
                            "guven": "yuksek"})
    out.sort(key=lambda s: s["start"])
    return out


def keep_ranges(duration: float, cuts: List[Dict]) -> List[Tuple[float, float]]:
    """Kesilecek aralıklardan (dolgu kelimesi kendi süresi + PAD) kalacak aralıkları çıkarır."""
    spans = []
    for c in cuts:
        a, b = c["start"], c["end"]
        if c["tur"] in ("dolgu", "tekrar"):
            a, b = a - PAD / 2, b + PAD / 2
        spans.append((max(0.0, a), min(duration, b)))
    spans.sort()
    merged: List[List[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 0.02:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    keep, t = [], 0.0
    for a, b in merged:
        if a - t > 0.05:
            keep.append((round(t, 3), round(a, 3)))
        t = max(t, b)
    if duration - t > 0.05:
        keep.append((round(t, 3), round(duration, 3)))
    return keep


def remap_words(words: List[Dict], keep: List[Tuple[float, float]]) -> List[Dict]:
    """Kelimeleri kesilmiş zaman çizelgesine taşır; kesilen aralıktaki kelimeler düşer."""
    out, offset_list, acc = [], [], 0.0
    for a, b in keep:
        offset_list.append((a, b, acc))
        acc += b - a
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        seg = next(((a, b, o) for a, b, o in offset_list if a <= mid < b), None)
        if seg is None:
            continue
        a, b, o = seg
        out.append(dict(w, start=round(max(a, w["start"]) - a + o, 3), end=round(min(b, w["end"]) - a + o, 3)))
    return out


def apply_cuts(src: str, keep: List[Tuple[float, float]], out: str, has_video: bool, has_audio: bool) -> None:
    """Kalan aralıkları birleştirir (her kesimde 10 ms ses yumuşatma: tık sesi olmaz)."""
    parts, labels = [], []
    for k, (a, b) in enumerate(keep):
        lab = ""
        if has_video:
            parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{k}]")
            lab += f"[v{k}]"
        if has_audio:
            d = b - a
            parts.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,"
                         f"afade=t=in:d=0.01,afade=t=out:st={max(0, d - 0.01):.3f}:d=0.01[a{k}]")
            lab += f"[a{k}]"
        labels.append(lab)
    v, a = int(has_video), int(has_audio)
    outs = ("[v]" if has_video else "") + ("[a]" if has_audio else "")
    fc = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(keep)}:v={v}:a={a}{outs}"
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src, "-filter_complex", fc]
    if has_video:
        cmd += ["-map", "[v]", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]
    if has_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)


def report(sugs: List[Dict]) -> str:
    if not sugs:
        return "Kırpma önerisi yok."
    tot = sum(s["end"] - s["start"] for s in sugs)
    lines = [f"{len(sugs)} kırpma önerisi (toplam ~{tot:.1f} s):"]
    for s in sugs:
        lines.append(f"  {s['start']:6.2f}-{s['end']:6.2f}  {s['tur']:<9} {s['guven']:<6} {s['metin']}  ({s['neden']})")
    return "\n".join(lines)
