"""Kelime zamanlı Türkçe transkript: faster-whisper ya da whisper.cpp (hangisi kuruluysa).

Her iki motor da yereldir; ücretli API, hesap, internet (model indirildikten sonra) gerekmez.
Çıktı biçimi (words.json):
    {"source": ..., "engine": "faster-whisper"|"whisper.cpp"|"srt", "model": ..., "language": "tr",
     "duration": 12.3, "words": [{"w": "İstanbul'da", "start": 0.31, "end": 0.92, "p": 0.97}, ...]}
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_PROMPT = "Eee, şey, yani... Tamam, başlıyoruz. Bugün size kısaca anlatacağım."
WHISPER_CPP_BINS = ("whisper-cli", "whisper-cpp", "whisper.cpp", "main")
MODEL_GLOBS = (
    "~/.cache/whisper-cpp/ggml-*.bin", "~/.cache/whisper/ggml-*.bin", "./models/ggml-*.bin",
    "~/whisper.cpp/models/ggml-*.bin", "/opt/homebrew/share/whisper-cpp/ggml-*.bin",
    "/usr/local/share/whisper-cpp/ggml-*.bin",
)
MODEL_PREF = ("large-v3-turbo", "large-v3", "large-v2", "medium", "small", "base", "tiny")


# ---------------------------------------------------------------- ses
def ffprobe_duration(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def decode_pcm16k(path: str):
    """Sesi 16 kHz mono float32 numpy dizisine çevirir (ffmpeg ile)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-vn", "-f", "s16le", "-ac", "1",
                          "-ar", "16000", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


# ---------------------------------------------------------------- motor bulma
def find_whisper_cpp() -> Optional[str]:
    env = os.environ.get("TA_WHISPER_CPP_BIN")
    if env and shutil.which(env):
        return shutil.which(env)
    for b in WHISPER_CPP_BINS:
        p = shutil.which(b)
        if p and (b != "main" or "whisper" in os.path.realpath(p)):
            return p
    return None


def find_whisper_cpp_models() -> List[str]:
    env = os.environ.get("TA_WHISPER_CPP_MODEL")
    found = [env] if env and os.path.isfile(env) else []
    for g in MODEL_GLOBS:
        found += sorted(glob.glob(os.path.expanduser(g)))
    found = [f for f in dict.fromkeys(found) if not re.search(r"\.en[.-]|for-tests", os.path.basename(f))]

    def rank(f):
        name = os.path.basename(f)
        return next((i for i, k in enumerate(MODEL_PREF) if k in name), 99)
    return sorted(found, key=rank)


def has_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def pick_engine(pref: str = "auto") -> str:
    if pref in ("faster-whisper", "fw"):
        return "faster-whisper"
    if pref in ("whisper.cpp", "whispercpp", "cpp"):
        return "whisper.cpp"
    # whisper.cpp + model varsa önce o (Apple Silicon'da Metal GPU ile hızlı, large-v3-turbo modeli iyi);
    # yoksa faster-whisper (CPU'da int8, Linux/Windows'ta CUDA ile).
    if find_whisper_cpp() and find_whisper_cpp_models():
        return "whisper.cpp"
    if has_faster_whisper():
        return "faster-whisper"
    raise RuntimeError("Transkript motoru yok. Kur: `pip install faster-whisper` ya da whisper.cpp "
                       "(`brew install whisper-cpp` + ggml model). Ayrıntı: `altyazi.py doctor`.")


# ---------------------------------------------------------------- motorlar
def _fw_transcribe(path: str, model: Optional[str], prompt: str) -> Tuple[List[Dict], str]:
    from faster_whisper import WhisperModel
    name = model or os.environ.get("TA_FW_MODEL", "small")
    audio = decode_pcm16k(path)          # PyAV sürüm uyumsuzluklarından kaçınmak için sesi biz çözüyoruz
    m = WhisperModel(name, device=os.environ.get("TA_FW_DEVICE", "auto"),
                     compute_type=os.environ.get("TA_FW_COMPUTE", "int8"))
    segs, _ = m.transcribe(audio, language="tr", word_timestamps=True, initial_prompt=prompt or None,
                           condition_on_previous_text=False, beam_size=5)
    words = []
    for s in segs:
        for w in (s.words or []):
            words.append({"w": w.word, "start": float(w.start), "end": float(w.end),
                          "p": round(float(w.probability), 3), "lead_space": w.word.startswith(" ")})
    return words, name


def _cpp_transcribe(path: str, model: Optional[str], prompt: str) -> Tuple[List[Dict], str]:
    exe = find_whisper_cpp()
    if not exe:
        raise RuntimeError("whisper.cpp bulunamadı (whisper-cli). `brew install whisper-cpp` ya da TA_WHISPER_CPP_BIN.")
    models = [model] if model else find_whisper_cpp_models()
    if not models or not os.path.isfile(models[0]):
        raise RuntimeError("whisper.cpp modeli yok. Örn: ggml-large-v3-turbo-q5_0.bin dosyasını ~/.cache/whisper-cpp/ "
                           "altına koy ya da --model ile yolunu ver.")
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "in.wav")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", wav], check=True)
        cmd = [exe, "-m", models[0], "-l", "tr", "-ml", "1", "-sow", "-oj", "-of", os.path.join(td, "out"), "-np"]
        if prompt:
            cmd += ["--prompt", prompt]
        cmd += ["-t", str(max(2, (os.cpu_count() or 4) - 2)), wav]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(os.path.join(td, "out.json")):
            raise RuntimeError(f"whisper.cpp hata verdi: {r.stderr[-600:]}")
        data = json.load(open(os.path.join(td, "out.json"), encoding="utf-8"))
    words = []
    for s in data.get("transcription", []):
        t = s.get("text", "")
        if not t.strip() or re.fullmatch(r"\s*\[_?[A-Z_0-9]+\]\s*", t):
            continue
        words.append({"w": t, "start": s["offsets"]["from"] / 1000, "end": s["offsets"]["to"] / 1000,
                      "lead_space": t.startswith(" ")})
    return words, os.path.basename(models[0])


# ---------------------------------------------------------------- zaman onarımı
def merge_subwords(words: List[Dict]) -> List[Dict]:
    """Boşluksuz gelen parçaları (ek, noktalama) önceki kelimeye ekler: "İzmir" + "'e"."""
    out: List[Dict] = []
    for w in words:
        t = w["w"]
        if out and (not w.get("lead_space", True) or t.strip()[:1] in "'’" or re.fullmatch(r"\s*[.,!?;:…]+\s*", t)):
            out[-1]["w"] += t.strip()
            out[-1]["end"] = max(out[-1]["end"], w["end"])
            continue
        out.append({k: v for k, v in w.items() if k != "lead_space"} | {"w": t.strip()})
    return [w for w in out if w["w"]]


def speech_mask(path: str, hop: float = 0.01):
    """10 ms'lik pencerelerde konuşma var/yok (enerji eşiği). (mask, hop) döner."""
    import numpy as np
    a = decode_pcm16k(path)
    n = int(16000 * hop)
    if len(a) < n:
        return np.zeros(0, bool), hop
    frames = a[: len(a) // n * n].reshape(-1, n)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    floor = np.percentile(db, 10)
    thr = max(floor + 12, db.max() - 38)
    m = db > thr
    # 120 ms'den kısa sessizlikleri doldur (kelime içi kapanmalar)
    gap = int(0.12 / hop)
    idx = np.flatnonzero(m)
    for a0, b0 in zip(idx[:-1], idx[1:]):
        if 1 < b0 - a0 <= gap:
            m[a0:b0] = True
    return m, hop


def _spread_zero(ws: List[Dict]) -> None:
    """Sıfır/çok kısa kelime dizilerini (whisper.cpp) sonraki kelimeyle birlikte karakter oranına göre paylaştırır."""
    i = 0
    while i < len(ws):
        if ws[i]["end"] - ws[i]["start"] >= 0.04:
            i += 1
            continue
        j = i
        while j < len(ws) and ws[j]["end"] - ws[j]["start"] < 0.04:
            j += 1
        a = ws[i]["start"]
        if j < len(ws):
            group, b = ws[i:j + 1], ws[j]["end"]
        else:
            group, b = ws[i:j], ws[i]["start"] + 0.3 * (j - i)
        total = sum(len(g["w"]) + 1 for g in group)
        t0 = a
        for g in group:
            t1 = t0 + (b - a) * (len(g["w"]) + 1) / total
            g["start"], g["end"] = t0, t1
            t0 = t1
        i = j + 1


def speech_regions(path: str, min_gap: float = 0.25) -> List[Tuple[float, float]]:
    import numpy as np
    m, hop = speech_mask(path)
    if not len(m) or m.all() or not m.any():
        return []
    d = np.diff(np.r_[0, m.astype(int), 0])
    ons, offs = np.flatnonzero(d == 1) * hop, np.flatnonzero(d == -1) * hop
    regs: List[List[float]] = []
    for a, b in zip(ons, offs):
        if regs and a - regs[-1][1] < min_gap:
            regs[-1][1] = float(b)
        elif b - a >= 0.06:
            regs.append([float(a), float(b)])
    return [(a, b) for a, b in regs]


def refine_times(words: List[Dict], path: Optional[str] = None) -> List[Dict]:
    """Kelime zamanlarını onarır:
    1) sıfır uzunluklu kelimeleri (whisper.cpp) karakter oranına göre paylaştırır,
    2) ses verilirse: kelimeleri konuşma bölgelerine (enerjiyle bulunan) oturtur. whisper.cpp bir
       cümlenin başını çoğu zaman önceki cümlenin bittiği yere, yani sessizliğe koyar; o cümlenin
       kelimeleri ait oldukları konuşma bölgesine doğrusal olarak taşınır,
    3) üst üste binmeleri giderir."""
    ws = [dict(w) for w in words]
    for w in ws:
        w["start"], w["end"] = float(w["start"]), float(max(w["end"], w["start"]))
    _spread_zero(ws)
    regs: List[Tuple[float, float]] = []
    if path:
        try:
            regs = speech_regions(path)
        except Exception:
            regs = []
    if regs and ws:
        def overlap(w, r):
            return max(0.0, min(w["end"], r[1]) - max(w["start"], r[0]))
        assign: List[Optional[int]] = []
        for w in ws:
            dur = max(1e-3, w["end"] - w["start"])
            k = max(range(len(regs)), key=lambda k: overlap(w, regs[k]))
            assign.append(k if overlap(w, regs[k]) >= 0.5 * dur else None)
        for i in range(len(ws)):          # yerleşmeyen kelime: bir sonraki yerleşen kelimenin bölgesine
            if assign[i] is None:
                nxt = next((assign[j] for j in range(i + 1, len(ws)) if assign[j] is not None), None)
                prv = next((assign[j] for j in range(i - 1, -1, -1) if assign[j] is not None), None)
                mid = (ws[i]["start"] + ws[i]["end"]) / 2
                if nxt is not None and (prv is None or regs[nxt][0] - mid <= mid - regs[prv][1] + 1.5):
                    assign[i] = nxt
                else:
                    assign[i] = prv if prv is not None else 0
        for i in range(1, len(assign)):    # sıra bozulmasın
            assign[i] = max(assign[i], assign[i - 1])
        for k, (on, off) in enumerate(regs):
            idx = [i for i, a in enumerate(assign) if a == k]
            if not idx:
                continue
            s, e = ws[idx[0]]["start"], ws[idx[-1]]["end"]
            ns = on - 0.02 if s < on - 0.05 or s > on + 0.6 else s
            ne = off + 0.06 if e > off + 0.15 or e < off - 0.6 else e
            if (ns, ne) != (s, e) and e > s and ne > ns:
                f = (ne - ns) / (e - s)
                for i in idx:
                    ws[i]["start"] = ns + (ws[i]["start"] - s) * f
                    ws[i]["end"] = ns + (ws[i]["end"] - s) * f
    for a, b in zip(ws, ws[1:]):
        if b["start"] < a["end"]:
            mid = (a["end"] + b["start"]) / 2 if b["start"] > a["start"] else a["end"]
            a["end"], b["start"] = mid, max(mid, b["start"])
    for w in ws:
        w["start"], w["end"] = round(w["start"], 3), round(max(w["end"], w["start"] + 0.05), 3)
    return ws


# ---------------------------------------------------------------- SRT'den kelime
def _srt_t(s: str) -> float:
    h, m, rest = s.strip().replace(".", ",").split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def words_from_srt(path: str) -> List[Dict]:
    """Elindeki SRT'den yaklaşık kelime zamanları (her satırın süresi karakter oranına göre paylaştırılır)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    words = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        k = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if k is None:
            continue
        a, b = [_srt_t(x) for x in lines[k].split("-->")]
        toks = re.sub(r"<[^>]+>|\{[^}]+\}", "", " ".join(lines[k + 1:])).split()
        total = sum(len(t) + 1 for t in toks) or 1
        t0 = a
        for t in toks:
            t1 = t0 + (b - a) * (len(t) + 1) / total
            words.append({"w": t, "start": round(t0, 3), "end": round(t1, 3)})
            t0 = t1
    return words


# ---------------------------------------------------------------- giriş noktası
def transcribe(path: str, engine: str = "auto", model: Optional[str] = None, prompt: str = DEFAULT_PROMPT,
               refine: bool = True) -> Dict:
    eng = pick_engine(engine)
    if eng == "faster-whisper":
        raw, mname = _fw_transcribe(path, model, prompt)
    else:
        raw, mname = _cpp_transcribe(path, model, prompt)
    words = merge_subwords(raw)
    if refine:
        words = refine_times(words, path)
    return {"source": os.path.basename(path), "engine": eng, "model": mname, "language": "tr",
            "duration": round(ffprobe_duration(path), 3), "words": words}
