"""Ücretsiz altyazı stilleri. Ölçüler 1080x1920 (9:16) referansında pikseldir; başka çözünürlükte
sqrt(W*H)/1440 oranıyla ölçeklenir. Pro stil paketi ileride ayrı olarak gelebilir; bu üç stil ücretsiz
ve MIT lisanslıdır."""
from __future__ import annotations

from pathlib import Path
from typing import Dict

FONTS = Path(__file__).resolve().parent / "fonts"

STYLES: Dict[str, Dict] = {
    # Sade, okunaklı: cümle düzeni, 2 satıra kadar, yumuşak gölge. Konuşan kafa, eğitim, vlog.
    "temiz": {
        "ad": "Temiz",
        "font": "Montserrat-SemiBold.ttf", "family": "Montserrat SemiBold",
        "size": 62, "case": "cumle",
        "color": "#FFFFFF", "outline": 3.0, "outline_color": "#000000", "outline_alpha": 0.55,
        "shadow": 3.0, "shadow_blur": 6.0, "shadow_alpha": 0.55,
        "max_lines": 2, "max_words": 8, "line_chars": 26, "keyword_color": None,
        "pop": False, "fade": 0.06, "line_gap": 0.18,
    },
    # Kalın, büyük harf (Türkçe kuralla), 1-3 kelime, anahtar kelime sarı. Enerjik reels.
    "kalin-vurgu": {
        "ad": "Kalın vurgu",
        "font": "Montserrat-Black.ttf", "family": "Montserrat Black",
        "size": 92, "case": "buyuk",
        "color": "#FFFFFF", "outline": 7.0, "outline_color": "#000000", "outline_alpha": 1.0,
        "shadow": 5.0, "shadow_blur": 4.0, "shadow_alpha": 0.6,
        "max_lines": 2, "max_words": 3, "line_chars": 14, "keyword_color": "#FFD60A",
        "pop": True, "fade": 0.0, "line_gap": 0.08,
    },
    # Karaoke: satır ekranda kalır, söylenen kelime renklenir; söylenmemiş kelimeler soluk.
    "karaoke": {
        "ad": "Karaoke vurgu",
        "font": "Montserrat-ExtraBold.ttf", "family": "Montserrat ExtraBold",
        "size": 74, "case": "buyuk",
        "color": "#FFFFFF", "outline": 6.0, "outline_color": "#000000", "outline_alpha": 1.0,
        "shadow": 4.0, "shadow_blur": 4.0, "shadow_alpha": 0.55,
        "max_lines": 2, "max_words": 6, "line_chars": 18, "keyword_color": None,
        "active_color": "#B8FF3C", "upcoming_alpha": 0.6,
        "pop": False, "fade": 0.05, "line_gap": 0.1, "karaoke": True,
    },
    # Önce/sonra karşılaştırması için "sıradan" altyazı: Python .upper() ile büyütülmüş, uzun satır,
    # kenarlıksız. Bilerek kötü; yalnız demo içindir (stil listesinde görünmez).
    "_sade-hatali": {
        "ad": "Sıradan (hatalı büyük harf)",
        "font": "Montserrat-SemiBold.ttf", "family": "Montserrat SemiBold",
        "size": 56, "case": "naive_upper",
        "color": "#FFFFFF", "outline": 0.0, "outline_color": "#000000", "outline_alpha": 0.0,
        "shadow": 2.0, "shadow_blur": 0.0, "shadow_alpha": 0.8,
        "max_lines": 2, "max_words": 12, "line_chars": 40, "keyword_color": None,
        "pop": False, "fade": 0.0, "line_gap": 0.15,
    },
}

PUBLIC = [k for k in STYLES if not k.startswith("_")]

# Platform güvenli alanı (karenin oranı). 9:16'da Reels/TikTok/Shorts arayüzü: üstte hesap adı,
# altta açıklama + müzik satırı, sağda beğen/yorum/paylaş sütunu.
SAFE_VERTICAL = {"top": 0.12, "bottom": 0.22, "left": 0.06, "right": 0.12, "y": 0.67}
SAFE_LANDSCAPE = {"top": 0.08, "bottom": 0.08, "left": 0.08, "right": 0.08, "y": 0.86}


def get(name: str) -> Dict:
    if name not in STYLES:
        raise SystemExit(f"Bilinmeyen stil: {name}. Seçenekler: {', '.join(PUBLIC)}")
    s = dict(STYLES[name])
    s["key"] = name
    return s


def safe_for(w: int, h: int) -> Dict:
    return dict(SAFE_VERTICAL if w / h < 0.8 else SAFE_LANDSCAPE)


def scale_for(w: int, h: int) -> float:
    return (w * h) ** 0.5 / 1440.0
