"""Demo: PIL ile çizilmiş 9:16 arka plan + examples/demo_ses.m4a (yerel TTS ile üretilmiş Türkçe anlatım)
-> üç stilde altyazılı video + önce/sonra karşılaştırması (str.upper() 'ISTANBUL' vs tr_upper() 'İSTANBUL').

    python3 altyazi.py demo --cikti altyazi_demo           # transkript motoru varsa onu kullanır
    python3 altyazi.py demo --asr yok                      # motor yoksa hazır examples/demo_kelimeler.json
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EX = HERE.parent / "examples"
W, H, FPS = 1080, 1920, 30


def make_background(audio: str, out: str) -> None:
    """Koyu gradyan + yavaş süzülen yumuşak ışıklar + sade şehir silueti; altına anlatım sesi."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio],
                               capture_output=True, text=True).stdout.strip()) + 0.3
    n = int(dur * FPS)
    y = np.linspace(0, 1, H)[:, None, None]
    top, bot = np.array([18, 32, 54]), np.array([64, 38, 72])
    base = (top * (1 - y) + bot * y).repeat(W, axis=1).astype(np.float32)
    # siluet (kubbeler + ince kuleler), alt bölgede: altyazı alanının altında kalır
    sil = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(sil)
    ground = int(H * 0.86)
    d.rectangle([0, ground, W, H], fill=255)
    for cx, r in ((300, 120), (560, 170), (800, 110)):
        d.rectangle([cx - r, ground - r * 0.55, cx + r, ground], fill=255)
        d.ellipse([cx - r * 0.8, ground - r * 1.35, cx + r * 0.8, ground - r * 0.05], fill=255)
    for x, hgt in ((150, 360), (380, 300), (720, 330), (960, 380)):
        d.rectangle([x - 9, ground - hgt, x + 9, ground], fill=255)
        d.polygon([(x - 13, ground - hgt), (x + 13, ground - hgt), (x, ground - hgt - 60)], fill=255)
    sil = np.asarray(sil.filter(ImageFilter.GaussianBlur(1.2)), np.float32)[..., None] / 255.0
    sil_col = np.array([10, 12, 22], np.float32)
    # yumuşak ışık lekeleri
    orbs = []
    for (r, col) in ((420, (255, 170, 90)), (520, (90, 160, 255)), (360, (255, 110, 160)), (300, (120, 255, 210))):
        s = Image.new("L", (r * 2, r * 2), 0)
        ImageDraw.Draw(s).ellipse([r * 0.55, r * 0.55, r * 1.45, r * 1.45], fill=255)
        s = np.asarray(s.filter(ImageFilter.GaussianBlur(r * 0.15)), np.float32)[..., None] / 255.0
        orbs.append((r, np.array(col, np.float32), s))
    enc = subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", audio, "-map", "0:v", "-map", "1:a",
                            "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out],
                           stdin=subprocess.PIPE)
    for f in range(n):
        t = f / FPS
        fr = base.copy()
        for k, (r, col, s) in enumerate(orbs):
            cx = int(W * (0.25 + 0.5 * (0.5 + 0.5 * math.sin(0.23 * t + k * 1.7))))
            cy = int(H * (0.18 + 0.12 * k + 0.05 * math.sin(0.31 * t + k)))
            x0, y0 = cx - r, cy - r
            xs0, ys0 = max(0, -x0), max(0, -y0)
            xs1, ys1 = min(2 * r, W - x0), min(2 * r, H - y0)
            if xs1 > xs0 and ys1 > ys0:
                fr[y0 + ys0:y0 + ys1, x0 + xs0:x0 + xs1] += s[ys0:ys1, xs0:xs1] * col * 0.33
        fr = fr * (1 - sil) + sil_col * sil
        enc.stdin.write(np.clip(fr, 0, 255).astype(np.uint8).tobytes())
    enc.stdin.close()
    enc.wait()


def compare(before: str, after: str, out: str) -> None:
    """Önce/sonra yan yana, 9:16 tek video (etiketler PIL ile, birleştirme ffmpeg overlay ile)."""
    from PIL import Image, ImageDraw, ImageFont
    fonts = HERE / "fonts"
    big = ImageFont.truetype(str(fonts / "Montserrat-ExtraBold.ttf"), 64)
    small = ImageFont.truetype(str(fonts / "Montserrat-SemiBold.ttf"), 30)
    pw, ph, gap = 516, 917, 16
    x1, x2, py = (W - 2 * pw - gap) // 2, (W - 2 * pw - gap) // 2 + pw + gap, 400
    lab = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lab)
    for x, title, sub, col in ((x1, "ÖNCE", "str.upper()  ·  ham transkript", (255, 107, 107)),
                               (x2, "SONRA", "tr_upper()  ·  düzeltme  ·  stil", (184, 255, 60))):
        d.text((x + pw / 2, 250), title, font=big, fill=col, anchor="mm")
        d.text((x + pw / 2, 322), sub, font=small, fill=(200, 205, 215), anchor="mm")
    d.text((W / 2, py + ph + 120), "ISTANBUL  →  İSTANBUL", font=big, fill=(255, 255, 255), anchor="mm")
    d.text((W / 2, py + ph + 200), "Türkçe Altyazı Hattı  ·  ücretsiz Claude Code skill'i", font=small,
           fill=(170, 175, 190), anchor="mm")
    tmp = str(Path(out).with_suffix(".labels.png"))
    lab.save(tmp)
    fc = (f"color=c=0x0E0F12:s={W}x{H}:r={FPS}[bg];"
          f"[0:v]scale={pw}:{ph}:flags=lanczos[a];[1:v]scale={pw}:{ph}:flags=lanczos[b];"
          f"[bg][a]overlay={x1}:{py}:shortest=1[t1];[t1][b]overlay={x2}:{py}[t2];[t2][2:v]overlay=0:0[v]")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", before, "-i", after, "-loop", "1", "-i", tmp,
                    "-filter_complex", fc, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-crf", "20",
                    "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest",
                    "-movflags", "+faststart", out], check=True)
    os.remove(tmp)


def main(out_dir: str = "altyazi_demo", asr_pref: str = "auto") -> int:
    sys.path.insert(0, str(HERE))
    import altyazi, asr, layout, render_pil, burn, styles as S
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    audio = str(EX / "demo_ses.m4a")
    src = str(out / "demo.mp4")
    print("1) arka plan videosu çiziliyor (PIL) ...", flush=True)
    make_background(audio, src)

    words_path = EX / "demo_kelimeler.json"
    use_asr = asr_pref != "yok"
    if use_asr:
        try:
            asr.pick_engine(asr_pref)
        except RuntimeError as e:
            print(f"   transkript motoru yok, hazır kelimeler kullanılıyor ({e})")
            use_asr = False
    args = ["run", src, "--cikti", str(out), "--stil", "hepsi", "--oneriler-uygula"]
    if use_asr:
        args += ["--asr", asr_pref]
    else:
        args += ["--kelimeler", str(words_path)]
    print("2) üç stil üretiliyor:", " ".join(args[2:]), flush=True)
    rc = altyazi.main(args)
    if rc:
        return rc

    print("3) 'önce' videosu: ham transkript + Python str.upper() ...", flush=True)
    d = json.loads((out / "demo.words.json").read_text(encoding="utf-8"))
    style = S.get("_sade-hatali")
    cells = layout.build_cells(d["words"], style, W, H, auto_keywords=False)
    burn.burn_pil(src, render_pil.build_states(cells, style, W, H), str(out / "demo_once.mp4"))
    shutil.copy(out / "demo.kalin-vurgu.mp4", out / "demo_sonra.mp4")
    print("4) önce/sonra karşılaştırması ...", flush=True)
    compare(str(out / "demo_once.mp4"), str(out / "demo_sonra.mp4"), str(out / "demo_once_sonra.mp4"))
    print(f"Bitti -> {out}/demo_once_sonra.mp4 (+ demo.temiz/kalin-vurgu/karaoke.mp4, .srt, .ass)")
    return 0


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:2] or ["altyazi_demo"])))
