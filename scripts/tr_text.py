"""Türkçe metin kuralları: büyük/küçük harf (İ/ı, I/i), başlık düzeni ve sık ASR hataları.

Python'un str.upper() / str.lower() fonksiyonları Türkçe değildir:
    "istanbul".upper()  -> "ISTANBUL"   (yanlış, doğrusu İSTANBUL)
    "IŞIK".lower()      -> "işik"       (yanlış, doğrusu ışık)
    "İ".lower()         -> "i̇"          (i + birleşik nokta, görünmez hata)
Bu modüldeki tr_upper / tr_lower / tr_capitalize / tr_title bunları düzeltir.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

DATA = Path(__file__).resolve().parent / "data"
APOS = "'’"
LETTERS = "A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû"
WORD_RE = re.compile(rf"[{LETTERS}0-9]+(?:[{APOS}][{LETTERS}]+)?")


# ---------------------------------------------------------------- büyük / küçük harf
def tr_lower(s: str) -> str:
    """Türkçe küçük harf: I -> ı, İ -> i (birleşik nokta bırakmaz)."""
    return s.replace("I", "ı").replace("İ", "i").lower().replace("i̇", "i")


def tr_upper(s: str) -> str:
    """Türkçe büyük harf: i -> İ, ı -> I.  tr_upper("istanbul'da ışık") == "İSTANBUL'DA IŞIK"."""
    return s.replace("i", "İ").replace("ı", "I").upper()


def _load_lines(name: str) -> List[str]:
    p = DATA / name
    if not p.is_file():
        return []
    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


KORU = {tr_lower(w): w for w in _load_lines("koru.txt")}          # yazılışı korunan: TL, NASA, YouTube, iPhone...
SIK = set(tr_lower(w) for w in _load_lines("sik_kelimeler.txt"))   # cümle ortasında küçük yazılan sık kelimeler
# I ile başlayan (noktasız) Türkçe sözcük kökleri: Irak, Isparta, Iğdır, ılık, ırmak, ısı, ışık...
I_NOKTASIZ = tuple(tr_lower(w) for w in _load_lines("noktasiz_i.txt"))
OZEL = {tr_lower(w): w for w in _load_lines("ozel_adlar.txt")}     # il, ülke, semt adları

KUCUK_KALIR = {"ve", "ile", "veya", "ya", "da", "de", "ki", "mi", "mı", "mu", "mü", "ama", "fakat", "için"}


def _split_suffix(word: str) -> Tuple[str, str]:
    """"İstanbul'da" -> ("İstanbul", "'da")."""
    for i, ch in enumerate(word):
        if ch in APOS:
            return word[:i], word[i:]
    return word, ""


def tr_capitalize(word: str) -> str:
    """İlk harfi Türkçe büyük, gerisi küçük; KORU listesindeki yazılış (TL, YouTube) korunur.
    Baştaki noktalama (", (, %) atlanır. "istanbul'da" -> "İstanbul'da", "tl'ye" -> "TL'ye"."""
    m = re.match(rf"^([^{LETTERS}0-9]*)(.*)$", word, re.S)
    lead, rest = m.group(1), m.group(2)
    if not rest:
        return word
    stem, suf = _split_suffix(rest)
    core = re.sub(r"[^\w]+$", "", stem)
    tail = stem[len(core):]
    if tr_lower(core) in KORU:
        return lead + KORU[tr_lower(core)] + tail + tr_lower(suf)
    low = tr_lower(rest)
    return lead + tr_upper(low[0]) + low[1:]


def tr_title(text: str) -> str:
    """Başlık düzeni: her sözcük büyük harfle, bağlaçlar (ve, ile, de/da, ki, mi...) küçük kalır
    (ilk sözcük hariç). "istanbul ve izmir'de bir gün" -> "İstanbul ve İzmir'de Bir Gün"."""
    out = []
    for i, tok in enumerate(text.split(" ")):
        bare = tr_lower(re.sub(rf"[^{LETTERS}]", "", tok))
        out.append(tok if not tok else (tr_lower(tok) if i and bare in KUCUK_KALIR else tr_capitalize(tok)))
    return " ".join(out)


def sentence_case(text: str) -> str:
    """Cümle düzeni: her cümlenin ilk harfi büyük (Türkçe kuralla), gerisine dokunmaz."""
    chars = list(text)
    start = True
    for i, ch in enumerate(chars):
        if start and ch.isalpha():
            chars[i] = tr_upper(ch)
            start = False
        elif ch in ".!?…":
            start = True
    return "".join(chars)


def apply_case(text: str, mode: str) -> str:
    if mode in ("buyuk", "upper"):
        return tr_upper(text)
    if mode in ("kucuk", "lower"):
        return tr_lower(text)
    if mode in ("baslik", "title"):
        return tr_title(text)
    return text


def has_wrong_case(text: str) -> bool:
    """Metinde yabancı-dil büyük harf izi var mı? (ISTANBUL, Izmir, i̇ birleşik nokta)."""
    return bool(fix_dotted_capitals(text)[1]) or "i̇" in text


# ---------------------------------------------------------------- I / İ onarımı
def _is_noktasiz(low: str) -> bool:
    return any(low.startswith(p) for p in I_NOKTASIZ)


_FRONT, _BACK = "EİÖÜ", "AIOU"


def _last_vowel(s: str) -> str:
    v = [c for c in s if c in _FRONT + _BACK]
    return v[-1] if v else ""


def _fix_caps(stem: str) -> str:
    """Tamamı büyük harfli sözcükte (ISKELESIYDI) her I'nın İ mi I mı olduğunu ünlü uyumuyla bulur.
    Emin olunamayan I'ya dokunmaz (KIZ, SIMIT gibi ilk ünlüsü belirsiz sözcükler aynen kalır)."""
    ch = list(stem)
    prev = None                      # önceki ünlünün sınıfı: 'f' (ince) / 'b' (kalın)
    for i, c in enumerate(ch):
        if c not in _FRONT + _BACK:
            continue
        if c != "I":
            prev = "f" if c in _FRONT else "b"
            continue
        if prev is None:
            if i == 0:
                prev = "b" if _is_noktasiz(tr_lower(stem)) else "f"
            else:
                nxt = next((x for x in ch[i + 1:] if x in _FRONT + _BACK and x != "I"), "")
                prev = "f" if nxt in _FRONT and nxt else ("b" if nxt in "AOU" and nxt else None)
                if prev is None:
                    continue
        else:
            pass
        ch[i] = "İ" if prev == "f" else "I"
    return "".join(ch)


def fix_dotted_capitals(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """İngilizce kurallarla büyütülmüş sözcükleri onarır.
      "Istanbul'da" -> "İstanbul'da", "Ilk" -> "İlk", "ISTANBUL" -> "İSTANBUL",
      ama "Işık", "Irak", "Isparta", "IŞIK" ve KORU listesindekiler (Instagram, iPhone) olduğu gibi kalır.
    Dönüş: (yeni metin, [(eski, yeni), ...])."""
    changes: List[Tuple[str, str]] = []

    def fix(m: re.Match) -> str:
        w = m.group(0)
        stem, suf = _split_suffix(w)
        low_stem = tr_lower(stem)
        if low_stem in KORU or tr_lower(stem.replace("I", "i")) in KORU:
            return w
        new = w
        if len(stem) >= 2 and stem[0] == "I" and stem[1:].islower():
            if not _is_noktasiz("ı" + tr_lower(stem[1:])):
                new = "İ" + stem[1:] + suf
        elif len(stem) >= 2 and stem.isupper() and "I" in stem:
            fixed = _fix_caps(stem)
            if fixed != stem:
                new = fixed + suf.replace("I", "İ" if fixed[-1:] in "EİÖÜ" or _last_vowel(fixed) in "EİÖÜ" else "I")
        if new != w:
            changes.append((w, new))
        return new

    return WORD_RE.sub(fix, text), changes


# ---------------------------------------------------------------- ASR düzeltmeleri
HALUSINASYON = [re.compile(p, re.I) for p in (
    r"^\s*alt\s*yaz[ıi]\s*[:\-]?\s*m\.?\s*k\.?\s*$",
    r"altyaz[ıi]\s+m\.?\s*k\.",
    r"izledi[ğg]iniz\s+i[çc]in\s+te[şs]ekk[üu]r",
    r"abone\s+ol(may[ıi]|mayı)?\s+unutmay[ıi]n",
    r"bir\s+sonraki\s+videoda\s+g[öo]r[üu][şs]mek\s+[üu]zere",
    r"^\s*sesli\s+betimleme",
    r"^\s*\[?\s*(m[üu]zik|alk[ıi][şs]|g[üu]l[üu][şs]meler)\s*\]?\s*$",
)]


def load_fixes() -> List[Dict[str, str]]:
    """data/asr_duzeltme.tsv: desen <TAB> yerine <TAB> mod (oto|oneri) <TAB> not."""
    rows = []
    p = DATA / "asr_duzeltme.tsv"
    if not p.is_file():
        return rows
    with p.open(encoding="utf-8") as fh:
        for r in csv.reader(fh, delimiter="\t"):
            if not r or r[0].startswith("#") or len(r) < 3:
                continue
            rows.append({"desen": r[0], "yerine": r[1], "mod": r[2].strip(), "not": r[3] if len(r) > 3 else ""})
    return rows


_FIXES: Optional[List[Tuple[re.Pattern, str, str, str]]] = None


def _fixes():
    global _FIXES
    if _FIXES is None:
        _FIXES = []
        for r in load_fixes():
            pat = r["desen"]
            if not pat.startswith("re:"):
                pat = r"(?<![\wçğıöşüÇĞİÖŞÜ])" + re.escape(pat) + r"(?![\wçğıöşüÇĞİÖŞÜ])"
            else:
                pat = pat[3:]
            _FIXES.append((re.compile(pat), r["yerine"], r["mod"], r["not"]))
    return _FIXES


def _match_case(src: str, repl: str) -> str:
    if src[:1].isupper() and repl[:1].islower():
        return tr_upper(repl[:1]) + repl[1:]
    return repl


def fix_word_list(words: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Kelime listesine (w/start/end) ASR düzeltmelerini uygular.
    Dönüş: (düzeltilmiş kelimeler, rapor). Rapor öğeleri: {tur, zaman, eski, yeni, mod}.
      - I/İ onarımı (Istanbul -> İstanbul)
      - ayrık ek birleştirme ("İzmir" + "'e" -> "İzmir'e")
      - yazım düzeltmeleri (herşey -> her şey, tabi ki -> tabii ki) [data/asr_duzeltme.tsv]
      - "50%" -> "%50"
      - cümle ortasında yanlışlıkla büyük yazılmış sık kelime (Sabah -> sabah)
    """
    rep: List[Dict] = []
    # 1) ayrık ekleri ve tek başına noktalamayı önceki kelimeye bağla
    merged: List[Dict] = []
    for w in words:
        t = w["w"].strip()
        if not t:
            continue
        if merged and (t[0] in APOS or re.fullmatch(r"[.,!?;:…)\]»\"]+", t)):
            merged[-1] = dict(merged[-1], w=merged[-1]["w"] + t, end=max(merged[-1]["end"], w["end"]))
            rep.append({"tur": "ek-birlesti", "zaman": w["start"], "eski": t, "yeni": merged[-1]["w"], "mod": "oto"})
            continue
        merged.append(dict(w, w=t))
    words = merged

    # 2) metin üzerinde çok-kelimeli düzeltmeler: kelimeleri boşlukla birleştirip eşleşmeleri geri dağıt
    text = " ".join(w["w"] for w in words)
    spans = []
    pos = 0
    for w in words:
        spans.append((pos, pos + len(w["w"])))
        pos += len(w["w"]) + 1

    def word_at(ch: int) -> int:
        for i, (a, b) in enumerate(spans):
            if ch <= b:
                return i
        return len(spans) - 1

    edits = []  # (i0, i1, new_text, mod, note)
    for pat, repl, mod, note in _fixes():
        for m in pat.finditer(text):
            i0, i1 = word_at(m.start()), word_at(max(m.start(), m.end() - 1))
            a, b = spans[i0][0], spans[i1][1]
            seg = text[a:b]
            new_seg = seg[:m.start() - a] + _match_case(m.group(0), m.expand(repl)) + seg[m.end() - a:]
            if new_seg != seg:
                edits.append((i0, i1, new_seg, mod, note))
    chosen, taken = [], set()
    for e in sorted(edits, key=lambda e: e[0]):
        if not any(i in taken for i in range(e[0], e[1] + 1)):
            chosen.append(e)
            if e[3] == "oto":
                taken.update(range(e[0], e[1] + 1))
    for i0, i1, new_seg, mod, note in sorted(chosen, key=lambda e: -e[0]):   # sondan başa: indeksler bozulmaz
        old = " ".join(w["w"] for w in words[i0:i1 + 1])
        rep.append({"tur": "yazim", "zaman": words[i0]["start"], "eski": old, "yeni": new_seg, "mod": mod, "not": note})
        if mod != "oto":
            continue
        toks = new_seg.split()
        if len(toks) == i1 - i0 + 1:
            for k, tok in enumerate(toks):
                words[i0 + k] = dict(words[i0 + k], w=tok)
        else:   # kelime sayısı değişti (herşey -> her şey): zamanı karakter oranına göre paylaştır
            a, b = words[i0]["start"], words[i1]["end"]
            total = sum(len(t) for t in toks) or 1
            new_ws, t0 = [], a
            for tok in toks:
                t1 = t0 + (b - a) * len(tok) / total
                new_ws.append({"w": tok, "start": round(t0, 3), "end": round(t1, 3), "p": words[i0].get("p")})
                t0 = t1
            words[i0:i1 + 1] = new_ws
    rep.sort(key=lambda r: r["zaman"])

    # 3) kelime bazlı onarımlar
    out = []
    sent_start = True
    for w in words:
        t = w["w"]
        t2, ch = fix_dotted_capitals(t)
        if ch:
            rep.append({"tur": "i-noktasi", "zaman": w["start"], "eski": t, "yeni": t2, "mod": "oto"})
        t = t2
        m = re.fullmatch(r"(\d+(?:[.,]\d+)?)%([.,!?]*)", t)
        if m:
            t = f"%{m.group(1)}{m.group(2)}"
            rep.append({"tur": "yuzde", "zaman": w["start"], "eski": w["w"], "yeni": t, "mod": "oto"})
        core = re.sub(rf"[^{LETTERS}]", "", _split_suffix(t)[0])
        if not sent_start and core[:1].isupper() and core[1:].islower() and tr_lower(core) in SIK:
            new = tr_lower(t[0]) + t[1:]
            rep.append({"tur": "buyuk-harf", "zaman": w["start"], "eski": t, "yeni": new, "mod": "oto"})
            t = new
        stem_t, suf_t = _split_suffix(t)
        core2 = re.sub(rf"[^{LETTERS}]+$", "", stem_t)
        if core2 and core2.islower() and core2 in OZEL and core2 != OZEL[core2]:
            new = OZEL[core2] + stem_t[len(core2):] + suf_t
            rep.append({"tur": "ozel-ad", "zaman": w["start"], "eski": t, "yeni": new, "mod": "oto"})
            t = new
        out.append(dict(w, w=t))
        sent_start = bool(re.search(r"[.!?…]$", t))
    return out, rep


def drop_hallucinations(words: List[Dict], segments: Optional[List[Tuple[float, float, str]]] = None) -> Tuple[List[Dict], List[Dict]]:
    """Whisper'ın Türkçede sık uydurduğu satırları (\"Altyazı M.K.\", \"İzlediğiniz için teşekkürler\",
    \"Abone olmayı unutmayın\") kelime listesinden çıkarır. Cümle bazında bakar."""
    rep = []
    sentences: List[List[int]] = [[]]
    for i, w in enumerate(words):
        sentences[-1].append(i)
        if re.search(r"[.!?…]$", w["w"]):
            sentences.append([])
    drop = set()
    for idx in sentences:
        if not idx:
            continue
        text = " ".join(words[i]["w"] for i in idx)
        if any(p.search(text) for p in HALUSINASYON):
            drop.update(idx)
            rep.append({"tur": "halusinasyon", "zaman": words[idx[0]]["start"], "eski": text, "yeni": "", "mod": "oto"})
    return [w for i, w in enumerate(words) if i not in drop], rep


def norm_word(w: str) -> str:
    """Karşılaştırma için: küçük harf, noktalama yok, ek dahil."""
    return re.sub(rf"[^{LETTERS}0-9{APOS}%]", "", tr_lower(w))


def is_number_token(w: str) -> bool:
    return bool(re.search(r"\d", w))


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


SELF_TESTS = [
    (tr_upper, "istanbul'da ışıklar", "İSTANBUL'DA IŞIKLAR"),
    (tr_upper, "iyi günler, izmir", "İYİ GÜNLER, İZMİR"),
    (tr_lower, "IŞIK İSTANBUL", "ışık istanbul"),
    (tr_lower, "İ", "i"),
    (tr_title, "istanbul ve izmir'de bir gün", "İstanbul ve İzmir'de Bir Gün"),
    (tr_title, "100 tl'ye iphone aldım", "100 TL'ye iPhone Aldım"),
    (lambda s: fix_dotted_capitals(s)[0], "Istanbul'da Ilk gün, Işıklar ve Isparta", "İstanbul'da İlk gün, Işıklar ve Isparta"),
    (lambda s: fix_dotted_capitals(s)[0], "ISTANBUL VE IZMIR", "İSTANBUL VE İZMİR"),
    (lambda s: fix_dotted_capitals(s)[0], "Instagram", "Instagram"),
    (lambda s: fix_dotted_capitals(s)[0], "ISKELESIYDI IŞIKLAR YANIYORDU KADIKÖY ELLI ILIK", "İSKELESİYDİ IŞIKLAR YANIYORDU KADIKÖY ELLİ ILIK"),
    (lambda s: " ".join(w["w"] for w in fix_word_list([{"w": x, "start": i, "end": i + 1} for i, x in
                                                        enumerate(s.split())])[0]),
     "izmir'e herşey 50% Istanbul", "İzmir'e her şey %50 İstanbul"),
]


def self_test() -> List[str]:
    bad = []
    for fn, inp, exp in SELF_TESTS:
        got = fn(inp)
        if got != exp:
            bad.append(f"{inp!r} -> {got!r} (beklenen {exp!r})")
    return bad


if __name__ == "__main__":
    errs = self_test()
    print("\n".join(errs) if errs else f"tr_text: {len(SELF_TESTS)} test OK")
