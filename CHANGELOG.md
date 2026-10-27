# Değişiklik günlüğü

## 1.0 — 2026-10-27
İlk sürüm.
- Yerel transkript: whisper.cpp (`whisper-cli`, ggml modeli) ya da faster-whisper; kelime zamanı onarımı
  (sıfır uzunluklu kelimeler, sessizliğe düşen cümle başları), ayrık eklerin birleştirilmesi.
- Türkçe büyük/küçük harf: `tr_upper`, `tr_lower`, `tr_capitalize`, `tr_title`, I/İ onarımı (ünlü uyumu).
- ASR düzeltmeleri (`data/asr_duzeltme.tsv`), whisper uydurma satırlarının silinmesi, özel ad listesi.
- Dolgu / tekrar / duraklama kırpma önerileri; `trim --uygula` ile kesme ve zaman kaydırma.
- Türkçe satır bölme, güvenli alan kontrolü, okuma hızı ve çakışma kontrolleri.
- Çıktılar: SRT, ASS (3 stil: temiz, kalin-vurgu, karaoke), konumlu JSON, yakılmış MP4 (ffmpeg ass
  filtresi ya da PIL yedeği; drawtext yok), önizleme karesi, rapor.
- `doctor`, `demo`, örnekler (EMA-TTS ile yerelde üretilmiş anlatım + PIL arka plan).
