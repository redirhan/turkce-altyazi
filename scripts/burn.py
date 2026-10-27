"""Altyazıyı videoya yakar.
- motor "ass": ffmpeg'in ass filtresi (libass gerekir). `ffmpeg -filters | grep -E "ass|subtitles"`
- motor "pil": libass yoksa; PIL ile çizilen saydam görüntüler karelere alfa ile bindirilir.
drawtext hiçbir yolda kullanılmaz. Ses kaynaktan aynen alınır (AAC ise kopyalanır)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

import styles as S


def ffmpeg_filters() -> Dict[str, bool]:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return {"ffmpeg": False, "ass": False, "subtitles": False, "drawtext": False, "overlay": False}
    names = {ln.split()[1] for ln in out.splitlines() if len(ln.split()) > 2 and ln.startswith(" ")}
    return {"ffmpeg": True, "ass": "ass" in names, "subtitles": "subtitles" in names,
            "drawtext": "drawtext" in names, "overlay": "overlay" in names}


def pick_engine(pref: str = "auto") -> str:
    f = ffmpeg_filters()
    if pref == "ass":
        if not f["ass"]:
            raise SystemExit("Bu ffmpeg'de ass filtresi (libass) yok. --motor pil kullan ya da libass'lı ffmpeg kur.")
        return "ass"
    if pref == "pil":
        return "pil"
    return "ass" if f["ass"] else "pil"


def probe(path: str) -> Dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"Dosya okunamadı: {path}\n{r.stderr[-400:]}")
    d = json.loads(r.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    info = {"has_video": v is not None, "has_audio": a is not None,
            "duration": float(d.get("format", {}).get("duration", 0) or 0),
            "audio_codec": a.get("codec_name") if a else None}
    if v:
        w, h = int(v["width"]), int(v["height"])
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        if "rotate" in (v.get("tags") or {}):
            rot = int(v["tags"]["rotate"])
        if abs(rot) % 180 == 90:
            w, h = h, w
        num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
        fps = float(num) / float(den or 1) if float(num) > 0 else 30.0
        if fps > 120 or fps < 1:
            fps = 30.0
        info.update(width=w, height=h, fps=round(fps, 3), fps_str=f"{num}/{den}" if float(num) > 0 else "30")
    return info


def _audio_args(info: Dict) -> List[str]:
    if not info["has_audio"]:
        return []
    return ["-c:a", "copy"] if info["audio_codec"] == "aac" else ["-c:a", "aac", "-b:a", "192k"]


def _video_input(src: str, info: Dict, size=(1080, 1920), bg="#101418") -> List[str]:
    """Video yoksa (yalnız ses) düz renk arka plan üretir."""
    if info["has_video"]:
        return ["-i", src]
    w, h = size
    dur = max(0.5, info["duration"])
    return ["-f", "lavfi", "-i", f"color=c={bg.replace('#', '0x')}:s={w}x{h}:r=30:d={dur:.3f}", "-i", src]


def burn_ass(src: str, ass_path: str, out: str, crf: int = 18, preset: str = "medium") -> None:
    info = probe(src)
    fonts = str(S.FONTS)
    with tempfile.TemporaryDirectory() as td:
        shutil.copy(ass_path, os.path.join(td, "subs.ass"))
        shutil.copytree(fonts, os.path.join(td, "fonts"))
        vin = _video_input(os.path.abspath(src), info)
        amap = ["-map", "1:a:0"] if not info["has_video"] else (["-map", "0:a:0?"])
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", *vin, "-vf", "ass=subs.ass:fontsdir=fonts",
               "-map", "0:v:0", *amap, "-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p",
               *_audio_args(info), "-movflags", "+faststart", "-shortest", os.path.abspath(out)]
        subprocess.run(cmd, check=True, cwd=td)


def burn_pil(src: str, states: List[Dict], out: str, crf: int = 18, preset: str = "medium",
             size=(1080, 1920)) -> None:
    """Kareleri ffmpeg'den ham RGB olarak okur, altyazı görüntülerini numpy ile bindirir, yeniden kodlar."""
    import numpy as np
    from PIL import Image

    info = probe(src)
    if info["has_video"]:
        W, H, fps_str = info["width"], info["height"], info["fps_str"]
    else:
        W, H = size
        fps_str = "30"
    num, _, den = fps_str.partition("/")
    fps = float(num) / float(den or 1)
    if info["has_video"]:
        dec = ["ffmpeg", "-nostdin", "-v", "error", "-i", src, "-map", "0:v:0", "-fps_mode", "cfr", "-r", fps_str,
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    else:                                   # yalnız ses: düz renk arka plan
        dec = ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
               f"color=c=0x101418:s={W}x{H}:r=30:d={max(0.5, info['duration']):.3f}",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    enc = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", fps_str, "-i", "-", "-i", src, "-map", "0:v:0"]
    if info["has_audio"]:
        enc += ["-map", "1:a:0", *_audio_args(info)]
    enc += ["-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-shortest", out]

    # durumları numpy'a çevir (premultiplied değil; alfa ayrı)
    prepared = []
    for s in states:
        img = s["img"]
        variants = {1.0: img}
        if s.get("pop"):
            for f in (0.88, 0.92, 0.96):
                w2, h2 = max(1, int(img.width * f)), max(1, int(img.height * f))
                im2 = Image.new("RGBA", img.size, (0, 0, 0, 0))
                im2.paste(img.resize((w2, h2), Image.LANCZOS), ((img.width - w2) // 2, (img.height - h2) // 2))
                variants[f] = im2
        arrs = {k: np.asarray(v, dtype=np.float32) for k, v in variants.items()}
        prepared.append(dict(s, arrs=arrs))

    pd = subprocess.Popen(dec, stdout=subprocess.PIPE)
    pe = subprocess.Popen(enc, stdin=subprocess.PIPE)
    fsize = W * H * 3
    n = 0
    k0 = 0
    try:
        while True:
            buf = pd.stdout.read(fsize)
            if len(buf) < fsize:
                break
            t = n / fps
            frame = None
            while k0 < len(prepared) and prepared[k0]["t1"] <= t:
                k0 += 1
            for s in prepared[k0:k0 + 3]:
                if not (s["t0"] <= t < s["t1"]):
                    continue
                if frame is None:
                    frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
                el = t - s["t0"]
                key = 1.0
                if s.get("pop") and el < 0.09:
                    key = 0.88 if el < 0.03 else (0.92 if el < 0.06 else 0.96)
                arr = s["arrs"][key]
                a_mul = 1.0
                if s.get("fade_in") and el < s["fade_in"]:
                    a_mul = el / s["fade_in"]
                if s.get("fade_out") and s["t1"] - t < s["fade_out"]:
                    a_mul = min(a_mul, (s["t1"] - t) / s["fade_out"])
                x, y = s["x"], s["y"]
                h, w = arr.shape[:2]
                fx0, fy0, fx1, fy1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
                if fx1 <= fx0 or fy1 <= fy0:
                    continue
                src_ = arr[fy0 - y:fy1 - y, fx0 - x:fx1 - x]
                alpha = src_[..., 3:4] / 255.0 * a_mul
                dst = frame[fy0:fy1, fx0:fx1].astype(np.float32)
                frame[fy0:fy1, fx0:fx1] = (src_[..., :3] * alpha + dst * (1 - alpha)).astype(np.uint8)
            pe.stdin.write(buf if frame is None else frame.tobytes())
            n += 1
    finally:
        pe.stdin.close()
        pe.wait()
        pd.stdout.close()
        pd.wait()
    if pe.returncode != 0:
        raise SystemExit("ffmpeg kodlama hatası (PIL motoru)")
