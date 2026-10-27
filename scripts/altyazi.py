#!/usr/bin/env python3
"""Türkçe Altyazı Hattı — video/ses -> kelime zamanlı Türkçe altyazı (SRT + ASS + yakılmış MP4).

Kullanım (en sık):
    python3 altyazi.py doctor
    python3 altyazi.py run video.mp4 --stil kalin-vurgu --cikti altyazi_cikti/
    python3 altyazi.py run video.mp4 --stil hepsi                 # üç stil birden
    python3 altyazi.py run video.mp4 --srt elimdeki.srt --stil temiz   # transkript yerine SRT
Alt komutlar: doctor, transcribe, fix, trim, build, burn, run, still, demo
Hepsi yerel çalışır: yayın yok, hesap yok, ücretli API yok.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tr_text  # noqa: E402
import styles as S  # noqa: E402

VERSION = (HERE.parent / "VERSION").read_text().strip() if (HERE.parent / "VERSION").is_file() else "dev"


# ---------------------------------------------------------------- yardımcılar
def _load_words(path: str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(d, list):
        d = {"words": d}
    return d


def _save(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _size(args, src: str | None):
    if getattr(args, "boyut", None):
        w, h = args.boyut.lower().split("x")
        return int(w), int(h)
    if src:
        import burn
        info = burn.probe(src)
        if info["has_video"]:
            return info["width"], info["height"]
    return 1080, 1920


def _fix(words: list, apply_suggestions: bool, hide_fillers: bool):
    """ASR düzeltmeleri + halüsinasyon temizliği + (isteğe bağlı) dolgu gizleme."""
    import trim
    w1, rep1 = tr_text.drop_hallucinations(words)
    w2, rep2 = tr_text.fix_word_list(w1)
    if apply_suggestions:
        for r in rep2:
            if r["mod"] == "oneri" and r["tur"] == "yazim":
                for w in w2:
                    if abs(w["start"] - r["zaman"]) < 1e-6 and w["w"] == r["eski"].split()[0]:
                        toks = r["yeni"].split()
                        if len(toks) == len(r["eski"].split()) == 1:
                            w["w"] = toks[0]
                            r["mod"] = "oneri-uygulandi"
    hidden = []
    if hide_fillers:
        keep = []
        for w in w2:
            if trim.SAF.match(trim._clean(w["w"])):
                hidden.append(w["w"])
            else:
                keep.append(w)
        w2 = keep
    rep = sorted(rep1 + rep2, key=lambda r: r["zaman"])
    return w2, rep, hidden


def _report_fixes(rep: list) -> str:
    if not rep:
        return "Düzeltme yok."
    lines = []
    for r in rep:
        mark = {"oto": "düzeltildi", "oneri": "ÖNERİ", "oneri-uygulandi": "öneri uygulandı"}.get(r["mod"], r["mod"])
        note = f"  ({r['not']})" if r.get("not") else ""
        lines.append(f"  {r['zaman']:6.2f}  {r['tur']:<12} {mark:<16} {r['eski']!r} -> {r['yeni']!r}{note}")
    return "\n".join(lines)


def _contact_sheet(video: str, times: list, out: Path, W: int, H: int) -> None:
    """Çıktı videodan birkaç kare alıp yan yana önizleme yapar (gözle kontrol için)."""
    from PIL import Image
    import tempfile
    frames = []
    with tempfile.TemporaryDirectory() as td:
        for k, t in enumerate(times):
            p = os.path.join(td, f"f{k}.png")
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", p])
            if os.path.isfile(p):
                frames.append(Image.open(p).convert("RGB"))
    if not frames:
        return
    th = 640
    tw = int(frames[0].width * th / frames[0].height)
    sheet = Image.new("RGB", (tw * len(frames) + 8 * (len(frames) - 1), th), (20, 20, 20))
    for k, f in enumerate(frames):
        sheet.paste(f.resize((tw, th), Image.LANCZOS), (k * (tw + 8), 0))
    sheet.save(out, quality=88)


# ---------------------------------------------------------------- doctor
def cmd_doctor(args) -> int:
    import platform
    ok_all = True
    rows = []

    def row(state, name, msg):
        rows.append((state, name, msg))

    row("OK" if sys.version_info >= (3, 9) else "HATA", "Python", platform.python_version())
    for mod, need in (("PIL", True), ("numpy", True)):
        try:
            m = __import__(mod)
            row("OK", mod, getattr(m, "__version__", ""))
        except Exception:
            row("HATA", mod, "yok -> pip install -r requirements.txt")
            ok_all = False
    for b in ("ffmpeg", "ffprobe"):
        p = shutil.which(b)
        row("OK" if p else "HATA", b, p or "yok -> macOS: brew install ffmpeg · Linux: apt install ffmpeg")
        ok_all &= bool(p)
    if shutil.which("ffmpeg"):
        import burn
        f = burn.ffmpeg_filters()
        if f["ass"]:
            row("OK", "yakma motoru", "ass filtresi var (libass) -> ffmpeg ass filtresiyle yakılır")
        else:
            row("BİLGİ", "yakma motoru", "bu ffmpeg'de ass/subtitles filtresi (libass) yok -> PIL motoru kullanılır "
                "(aynı görünüm, biraz daha yavaş). drawtext gerekmez.")
        row("BİLGİ", "drawtext", "var" if f["drawtext"] else "yok (gerekmez)")
    import asr
    fw = asr.has_faster_whisper()
    cpp = asr.find_whisper_cpp()
    models = asr.find_whisper_cpp_models()
    row("OK" if fw else "—", "faster-whisper", "kurulu" if fw else "yok (isteğe bağlı: pip install faster-whisper)")
    row("OK" if cpp else "—", "whisper.cpp", cpp or "yok (isteğe bağlı: brew install whisper-cpp)")
    if cpp:
        row("OK" if models else "UYARI", "whisper.cpp modeli",
            os.path.basename(models[0]) if models else "model yok -> ggml-large-v3-turbo-q5_0.bin'i ~/.cache/whisper-cpp/ altına koy")
    if not fw and not (cpp and models):
        row("UYARI", "transkript", "motor yok: yalnız --srt / --kelimeler ile çalışır. Kurulum: README 'Transkript motoru'")
    # fontlar + Türkçe glif testi
    try:
        from PIL import ImageFont
        for st in S.PUBLIC:
            fp = S.FONTS / S.STYLES[st]["font"]
            if not fp.is_file():
                row("HATA", f"font {st}", f"{fp.name} yok")
                ok_all = False
                continue
            font = ImageFont.truetype(str(fp), 64)
            bad = [a + "/" + b for a, b in (("İ", "I"), ("ı", "i"), ("Ş", "S"), ("ğ", "g"), ("ç", "c"), ("ö", "o"))
                   if font.getmask(a).getbbox() == font.getmask(b).getbbox()
                   and bytes(font.getmask(a)) == bytes(font.getmask(b))]
            row("OK" if not bad else "HATA", f"font {st}", f"{fp.name} Türkçe harfler " + ("tamam" if not bad else f"eksik: {bad}"))
    except Exception as e:
        row("HATA", "font", str(e))
    bad = tr_text.self_test()
    row("OK" if not bad else "HATA", "Türkçe büyük/küçük harf", "tr_upper('istanbul') = " + tr_text.tr_upper("istanbul")
        + ("" if not bad else " | " + "; ".join(bad)))
    ok_all &= not bad
    w = max(len(r[1]) for r in rows)
    print(f"Türkçe Altyazı Hattı v{VERSION} — doctor")
    for st, name, msg in rows:
        print(f"  [{st:^5}] {name:<{w}}  {msg}")
    print("Sonuç:", "HAZIR" if ok_all else "EKSİK VAR (yukarıdaki HATA satırları)")
    return 0 if ok_all else 1


# ---------------------------------------------------------------- alt komutlar
def cmd_transcribe(args) -> int:
    import asr
    d = asr.transcribe(args.girdi, engine=args.asr, model=args.model, prompt=args.prompt)
    out = Path(args.cikti or Path(args.girdi).with_suffix(".words.json"))
    _save(out, json.dumps(d, ensure_ascii=False, indent=1))
    print(f"{len(d['words'])} kelime ({d['engine']}, {d['model']}) -> {out}")
    return 0


def cmd_fix(args) -> int:
    d = _load_words(args.kelimeler)
    words, rep, hidden = _fix(d["words"], args.oneriler_uygula, args.dolgu == "gizle")
    d["words"] = words
    out = Path(args.cikti or args.kelimeler.replace(".json", ".fixed.json"))
    _save(out, json.dumps(d, ensure_ascii=False, indent=1))
    print(_report_fixes(rep))
    print(f"-> {out}")
    return 0


def cmd_trim(args) -> int:
    import trim, burn
    d = _load_words(args.kelimeler)
    sugs = trim.suggest(d["words"], args.uzun_duraklama, args.kalan_duraklama)
    print(trim.report(sugs))
    base = Path(args.cikti or Path(args.girdi).with_suffix(""))
    _save(Path(str(base) + ".kirpma.json"), json.dumps(sugs, ensure_ascii=False, indent=1))
    if args.uygula:
        info = burn.probe(args.girdi)
        cuts = [s for s in sugs if args.guven == "orta" or s["guven"] == "yuksek"]
        keep = trim.keep_ranges(info["duration"], cuts)
        ext = ".mp4" if info["has_video"] else ".m4a"
        out = str(base) + ".kirpilmis" + ext
        trim.apply_cuts(args.girdi, keep, out, info["has_video"], info["has_audio"])
        nd = dict(d, words=trim.remap_words(d["words"], keep), source=os.path.basename(out))
        _save(Path(str(base) + ".kirpilmis.words.json"), json.dumps(nd, ensure_ascii=False, indent=1))
        print(f"kırpıldı: {info['duration']:.2f} s -> {sum(b - a for a, b in keep):.2f} s -> {out}")
    return 0


def build_outputs(words: list, style_names: list, W: int, H: int, base: Path, args, meta: dict) -> dict:
    import layout, writers
    res = {}
    kws = [k.strip() for k in (args.vurgu or "").split(",") if k.strip()]
    for st in style_names:
        style = S.get(st)
        cells = layout.build_cells(words, style, W, H, keywords=kws, auto_keywords=not args.vurgu_yok)
        ass = writers.to_ass(cells, style, W, H, args.y)
        _save(Path(f"{base}.{st}.ass"), ass)
        _save(Path(f"{base}.{st}.json"), writers.to_json(cells, style, W, H, meta, args.y))
        res[st] = {"cells": cells, "checks": layout.check_cells(cells, style, W, H, args.y), "style": style}
    # SRT her zaman "temiz" bölmesiyle (platformlara yüklemeye uygun, cümle düzeni, 2 satır)
    srt_cells = res["temiz"]["cells"] if "temiz" in res else layout.build_cells(words, S.get("temiz"), W, H)
    _save(Path(f"{base}.srt"), writers.to_srt(srt_cells))
    return res


def cmd_build(args) -> int:
    d = _load_words(args.kelimeler)
    W, H = _size(args, args.video)
    names = S.PUBLIC if args.stil == "hepsi" else [args.stil]
    base = Path(args.cikti or Path(args.kelimeler).with_suffix("")).with_suffix("")
    res = build_outputs(d["words"], names, W, H, base, args, {"source": d.get("source")})
    for st, r in res.items():
        print(f"{st}: {len(r['cells'])} hücre, {len(r['checks'])} bulgu -> {base}.{st}.ass")
    print(f"SRT -> {base}.srt")
    return 0


def _burn(src: str, st: str, cells: list, W: int, H: int, base: Path, args) -> str:
    import burn, render_pil
    out = f"{base}.{st}.mp4"
    eng = burn.pick_engine(args.motor)
    if eng == "ass":
        burn.burn_ass(src, f"{base}.{st}.ass", out, crf=args.crf)
    else:
        states = render_pil.build_states(cells, S.get(st), W, H, args.y)
        burn.burn_pil(src, states, out, crf=args.crf, size=(W, H))
    return out + f"  [{eng}]"


def cmd_burn(args) -> int:
    d = _load_words(args.kelimeler)
    W, H = _size(args, args.girdi)
    base = Path(args.cikti or Path(args.girdi).with_suffix("")).with_suffix("")
    names = S.PUBLIC if args.stil == "hepsi" else [args.stil]
    res = build_outputs(d["words"], names, W, H, base, args, {"source": os.path.basename(args.girdi)})
    for st in names:
        print("->", _burn(args.girdi, st, res[st]["cells"], W, H, base, args))
    return 0


def cmd_run(args) -> int:
    import asr, burn, trim
    src = args.girdi
    info = burn.probe(src)
    out_dir = Path(args.cikti or (Path(src).parent / "altyazi_cikti"))
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / Path(src).stem
    log = []

    def say(msg):
        print(msg, flush=True)
        log.append(msg)

    # 1) kelimeler
    if args.kelimeler:
        d = _load_words(args.kelimeler)
        say(f"1/5 kelimeler: {args.kelimeler} ({len(d['words'])} kelime)")
    elif args.srt:
        d = {"source": os.path.basename(src), "engine": "srt", "words": asr.refine_times(asr.words_from_srt(args.srt))}
        say(f"1/5 kelimeler: SRT'den yaklaşık ({len(d['words'])} kelime)")
    else:
        say("1/5 transkript çıkarılıyor (yerel whisper)...")
        d = asr.transcribe(src, engine=args.asr, model=args.model, prompt=args.prompt)
        say(f"    {len(d['words'])} kelime · {d['engine']} · {d['model']}")
    _save(Path(f"{base}.words.json"), json.dumps(d, ensure_ascii=False, indent=1))

    # 2) düzeltme
    words, rep, hidden = _fix(d["words"], args.oneriler_uygula, args.dolgu == "gizle")
    _save(Path(f"{base}.duzeltme.json"), json.dumps(rep, ensure_ascii=False, indent=1))
    say(f"2/5 Türkçe düzeltme: {sum(1 for r in rep if r['mod'] != 'oneri')} düzeltme, "
        f"{sum(1 for r in rep if r['mod'] == 'oneri')} öneri" + (f", altyazıdan gizlenen dolgu: {hidden}" if hidden else ""))
    if rep:
        say(_report_fixes(rep))

    # 3) kırpma önerileri
    sugs = trim.suggest(d["words"])
    _save(Path(f"{base}.kirpma.json"), json.dumps(sugs, ensure_ascii=False, indent=1))
    say("3/5 " + trim.report(sugs).replace("\n", "\n    "))

    # 4) SRT / ASS / JSON
    W, H = _size(args, src)
    names = S.PUBLIC if args.stil == "hepsi" else [args.stil]
    res = build_outputs(words, names, W, H, base, args, {"source": os.path.basename(src), "engine": d.get("engine")})
    say(f"4/5 altyazı dosyaları: {base}.srt + " + ", ".join(f"{base.name}.{n}.ass" for n in names))
    for st, r in res.items():
        errs = [c for c in r["checks"] if c["seviye"] == "hata"]
        warns = [c for c in r["checks"] if c["seviye"] != "hata"]
        say(f"    {st}: {len(r['cells'])} hücre · hata {len(errs)} · uyarı/bilgi {len(warns)}")
        for c in r["checks"]:
            say(f"      [{c['seviye']}] {c['zaman']:.2f}s {c['kod']}: {c['metin']}")

    # 5) yakma
    if args.yakma_yok:
        say("5/5 yakma atlandı (--yakma-yok)")
    else:
        for st in names:
            out = _burn(src, st, res[st]["cells"], W, H, base, args)
            mp4 = out.split("  [")[0]
            cells = res[st]["cells"]
            times = [(c["start"] + c["end"]) / 2 for c in cells]
            pick = [times[int(i * (len(times) - 1) / 2)] for i in range(3)] if len(times) >= 3 else times
            _contact_sheet(mp4, pick, Path(f"{base}.{st}.onizleme.jpg"), W, H)
            say(f"5/5 yakıldı: {out} · önizleme: {base}.{st}.onizleme.jpg")
    _save(Path(f"{base}.rapor.txt"), "\n".join(log) + "\n")
    return 0


def cmd_still(args) -> int:
    from PIL import Image
    import layout, render_pil, burn
    d = _load_words(args.kelimeler)
    if args.girdi and burn.probe(args.girdi)["has_video"]:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "f.png")
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", str(args.zaman), "-i", args.girdi,
                            "-frames:v", "1", p], check=True)
            bg = Image.open(p).convert("RGB")
    else:
        W, H = _size(args, None)
        bg = Image.new("RGB", (W, H), (16, 20, 24))
    words, _, _ = _fix(d["words"], args.oneriler_uygula, True)
    style = S.get(args.stil)
    cells = layout.build_cells(words, style, bg.width, bg.height,
                               keywords=[k.strip() for k in (args.vurgu or "").split(",") if k.strip()])
    render_pil.still(cells, style, bg, args.zaman, args.y).save(args.cikti)
    print("->", args.cikti)
    return 0


def cmd_demo(args) -> int:
    import demo
    return demo.main(args.cikti, args.asr)


# ---------------------------------------------------------------- argümanlar
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="altyazi.py", description="Türkçe Altyazı Hattı (yerel, ücretsiz, MIT)")
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common_asr(p):
        p.add_argument("--asr", default="auto", choices=["auto", "faster-whisper", "whisper.cpp"], help="transkript motoru")
        p.add_argument("--model", default=None, help="faster-whisper model adı (small, medium, large-v3...) ya da whisper.cpp ggml yolu")
        import asr
        p.add_argument("--prompt", default=asr.DEFAULT_PROMPT, help="whisper başlangıç metni ('' = kapalı)")

    def common_style(p, default="temiz"):
        p.add_argument("--stil", "--style", default=default, choices=S.PUBLIC + ["hepsi"])
        p.add_argument("--vurgu", default="", help="vurgulanacak kelimeler, virgülle: 'İstanbul,%%50'")
        p.add_argument("--vurgu-yok", action="store_true", help="otomatik anahtar kelime seçme")
        p.add_argument("--y", type=float, default=None, help="altyazı merkezinin yüksekliği (0-1). 9:16 varsayılan 0.67")
        p.add_argument("--boyut", default=None, help="kare boyutu, örn 1080x1920 (video verilirse ondan alınır)")

    def common_fix(p):
        p.add_argument("--oneriler-uygula", action="store_true", help="'öneri' düzeyindeki yazım düzeltmelerini de uygula")
        p.add_argument("--dolgu", default="gizle", choices=["gizle", "goster"], help="saf dolgu seslerini (ııı, eee) altyazıda gizle")

    def common_burn(p):
        p.add_argument("--motor", default="auto", choices=["auto", "ass", "pil"], help="yakma motoru")
        p.add_argument("--crf", type=int, default=18, help="x264 kalite (düşük = daha iyi)")

    p = sub.add_parser("doctor", help="kurulum kontrolü")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("transcribe", help="kelime zamanlı transkript (words.json)")
    p.add_argument("girdi")
    p.add_argument("--cikti", "--out")
    common_asr(p)
    p.set_defaults(fn=cmd_transcribe)

    p = sub.add_parser("fix", help="Türkçe büyük harf / ASR düzeltmeleri")
    p.add_argument("kelimeler")
    p.add_argument("--cikti", "--out")
    common_fix(p)
    p.set_defaults(fn=cmd_fix)

    p = sub.add_parser("trim", help="dolgu ve duraklama kırpma önerileri (--uygula ile kes)")
    p.add_argument("girdi")
    p.add_argument("--kelimeler", required=True)
    p.add_argument("--cikti", "--out")
    p.add_argument("--uygula", action="store_true")
    p.add_argument("--guven", default="yuksek", choices=["yuksek", "orta"], help="--uygula hangi güvendeki önerileri kessin")
    p.add_argument("--uzun-duraklama", type=float, default=0.6)
    p.add_argument("--kalan-duraklama", type=float, default=0.3)
    p.set_defaults(fn=cmd_trim)

    p = sub.add_parser("build", help="SRT + ASS + JSON üret")
    p.add_argument("kelimeler")
    p.add_argument("--video", default=None)
    p.add_argument("--cikti", "--out")
    common_style(p)
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("burn", help="altyazıyı videoya yak")
    p.add_argument("girdi")
    p.add_argument("--kelimeler", required=True)
    p.add_argument("--cikti", "--out")
    common_style(p)
    common_burn(p)
    p.set_defaults(fn=cmd_burn)

    p = sub.add_parser("run", help="hepsi bir arada: transkript -> düzeltme -> öneri -> SRT/ASS -> MP4")
    p.add_argument("girdi")
    p.add_argument("--cikti", "--out", help="çıktı klasörü")
    p.add_argument("--kelimeler", default=None, help="hazır words.json (transkripti atla)")
    p.add_argument("--srt", default=None, help="hazır SRT (kelime zamanı yaklaşık)")
    p.add_argument("--yakma-yok", action="store_true", help="MP4 yakma")
    common_asr(p)
    common_style(p)
    common_fix(p)
    common_burn(p)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("still", help="tek kare önizleme PNG")
    p.add_argument("--kelimeler", required=True)
    p.add_argument("--girdi", default=None)
    p.add_argument("--zaman", type=float, default=1.0)
    p.add_argument("--cikti", default="onizleme.png")
    common_style(p)
    common_fix(p)
    p.set_defaults(fn=cmd_still)

    p = sub.add_parser("demo", help="örnek videoyu üret ve altyazıla (examples/ içindeki sesle)")
    p.add_argument("--cikti", default="altyazi_demo")
    p.add_argument("--asr", default="auto", choices=["auto", "faster-whisper", "whisper.cpp", "yok"])
    p.set_defaults(fn=cmd_demo)

    args = ap.parse_args(argv)
    if getattr(args, "prompt", None) is not None and args.prompt.strip() == "":
        args.prompt = ""
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
