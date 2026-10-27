---
name: turkce-altyazi
description: Türkçe video ya da ses dosyasına kelime zamanlı altyazı yapar - yerel whisper (faster-whisper ya da whisper.cpp) ile transkript, doğru Türkçe büyük harf (İSTANBUL, ISTANBUL değil; IŞIK, İŞTE), sık ASR hatalarının düzeltilmesi (herşey→her şey, Şeyh→şey, 50%→%50, "Altyazı M.K." uydurması), dolgu/duraklama kırpma önerileri, reels için satır bölme (1-2 satır, güvenli alan) ve SRT + stilli ASS + altyazısı yakılmış MP4 çıktısı. 3 ücretsiz stil - temiz, kalın-vurgu, karaoke. Kullanıcı "altyazı ekle", "altyazı çıkar", "SRT yap", "videoya yazı göm", "reels altyazısı", "karaoke altyazı", "İ/ı bozuk çıkıyor", "dolguları/duraklamaları bul" dediğinde ya da Türkçe konuşmalı bir video/ses verdiğinde kullan. Tamamen yerel çalışır - yayın, hesap, ücretli API yok.
---

# Türkçe Altyazı Hattı

Video/ses girer → kelime zamanlı Türkçe altyazı çıkar: `.srt` + stilli `.ass` + altyazısı yakılmış `.mp4`
+ düzeltme raporu + kırpma önerileri. Her şey kullanıcının bilgisayarında çalışır.

## Kurallar (değişmez)

- **Yerel kal.** Hiçbir şeyi yayınlama, yükleme, hesaba girme; ücretli API çağırma. Model indirme
  (whisper modeli) yalnız kullanıcı onaylarsa.
- **Tarayıcı açma.** Bu iş için tarayıcı gerekmez; Chrome/Chromium hiç başlatma.
- **Kaynağı ezme.** Çıktılar ayrı klasöre gider (varsayılan `altyazi_cikti/`); kaynak video değişmez.
  `trim --uygula` da yeni dosya yazar.
- **Ekranda yalnız söylenen.** Altyazı transkripttir; içerik uydurma, "düzeltme" bahanesiyle cümle
  değiştirme. Yalnız yazım/büyük harf/ASR hatası düzeltilir ve hepsi raporda listelenir.
- **Türkçe büyük harf her yerde `tr_upper`.** Python `str.upper()`, JS `toUpperCase()` ya da CSS
  `text-transform: uppercase` (lang="tr" olmadan) Türkçeyi bozar: `istanbul → ISTANBUL`, `ilk → ILK`.
- **drawtext kullanma.** Yakma, ffmpeg'in `ass` filtresiyle (libass) ya da yoksa PIL yedeğiyle yapılır.

## Akış

`S=~/.claude/skills/turkce-altyazi/scripts` ve Pillow+numpy kurulu bir Python (`PY`, README'deki venv).

1. **Kontrol:** `$PY $S/altyazi.py doctor` → eksik varsa kullanıcıya tek satırla söyle (ffmpeg, Pillow,
   transkript motoru). Transkript motoru yoksa kullanıcı SRT verebilir (`--srt`).
2. **Hepsi bir arada:**
   ```bash
   $PY $S/altyazi.py run VIDEO.mp4 --stil kalin-vurgu --cikti altyazi_cikti/
   # --stil temiz | kalin-vurgu | karaoke | hepsi
   # --vurgu "İstanbul,%50"      kalın-vurgu stilinde sarı yapılacak kelimeler (yoksa sayılar + özel adlar)
   # --oneriler-uygula           "öneri" düzeyindeki düzeltmeleri de uygula (ör. Şeyh -> Şey)
   # --srt elimdeki.srt          transkript yerine hazır SRT
   # --kelimeler x.words.json    önceki transkripti yeniden kullan (hızlı yeniden stil)
   # --yakma-yok                 yalnız SRT/ASS/JSON
   # --motor pil|ass             yakma motorunu zorla (varsayılan: libass varsa ass)
   # --y 0.67                    altyazı yüksekliği (9:16'da 0,67 = çene altı, güvenli alan içinde)
   ```
3. **Raporu oku ve kullanıcıya özetle** (`<ad>.rapor.txt`): kaç düzeltme yapıldı, hangi **öneriler**
   onay bekliyor, kırpma önerileri (dolgu "şey/yani/ııı", tekrar, 0,6 s üstü duraklama), kontrol bulguları
   (güvenli alan, hızlı okuma, çakışma, Türkçe büyük harf).
4. **Gözle bak.** `<ad>.<stil>.onizleme.jpg` (çıktıdan 3 kare) dosyasını aç ve kontrol et: Türkçe
   harfler doğru mu, altyazı yüzü/özneyi kapatıyor mu, alt açıklama satırına ya da sağdaki ikonlara
   giriyor mu. Konuşan kafada altyazı yüzü kapatıyorsa `--y` ile aşağı al (en fazla ~0,74).
5. **Kırpma isterse:** `$PY $S/altyazi.py trim VIDEO.mp4 --kelimeler <ad>.words.json --uygula`
   (`--guven orta` ile söylem dolguları da kesilir) → `<ad>.kirpilmis.mp4` + kaydırılmış kelime
   zamanları; sonra `run <ad>.kirpilmis.mp4 --kelimeler <ad>.kirpilmis.words.json`.

## Alt komutlar

| Komut | İş |
|---|---|
| `doctor` | kurulum + Türkçe glif + tr_upper testi |
| `transcribe IN` | `words.json` (faster-whisper ya da whisper.cpp, kelime zamanı onarımlı) |
| `fix WORDS` | Türkçe büyük harf + ASR düzeltmeleri, rapor |
| `trim IN --kelimeler W` | dolgu/duraklama önerileri; `--uygula` ile kes |
| `build WORDS --stil S` | SRT + ASS + JSON (HyperFrames/Remotion için konumlu) |
| `burn IN --kelimeler W` | yakılmış MP4 |
| `run IN` | hepsi |
| `still --kelimeler W --zaman 3.2` | tek kare önizleme PNG |
| `demo` | örnek videoyu üretip altyazılar |

## Türkçe kurallar (kodda uygulananlar)

- `tr_upper / tr_lower / tr_title`: i↔İ, ı↔I; başlıkta "ve, ile, de/da, ki, mi" küçük; `TL, YouTube,
  iPhone` gibi yazılışlar korunur (`data/koru.txt`).
- ASR onarımı: `Istanbul → İstanbul`, `ISKELESIYDI → İSKELESİYDİ` (ünlü uyumuyla, emin değilse dokunmaz),
  `Işık/Irak/Isparta` korunur (`data/noktasiz_i.txt`), ayrık ek birleşir (`İzmir` + `'e`), `50% → %50`,
  cümle ortasında yanlış büyük harf (`Sabah → sabah`), küçük yazılmış il/ülke adı (`izmir → İzmir`),
  yazım (`data/asr_duzeltme.tsv`: herşey, birşey, tabi ki, malesef, yada...), whisper uydurmaları
  ("Altyazı M.K.", "İzlediğiniz için teşekkürler", "Abone olmayı unutmayın") silinir.
- Satır bölme: en fazla 2 satır, genişlik güvenli alanda; "ve/ile/bir/yüzde" satır ya da hücre sonunda
  kalmaz; "de/da, ki, mi, gibi, kadar, için" satır başına düşmez; sayı ile birimi ayrılmaz; alt satır
  üstten kısa olmaz.
- Zamanlama: hücre kelime zamanıyla açılır; 0,3 s duraklamada/cümle sonunda yeni hücre; 0,35 s'den kısa
  hücre yanıp sönmez; 0,25 s'ye kadar boşlukta ekranda kalır; saniyede 20 karakter üstü uyarı.

## Stiller

`temiz` (cümle düzeni, 2 satır, yumuşak gölge) · `kalin-vurgu` (büyük harf, 1-3 kelime, sayı ve özel
ad sarı, küçük "pop") · `karaoke` (satır ekranda, söylenen kelime yeşil, sıradakiler soluk).
Fontlar: Montserrat (OFL, pakette). Daha fazla stil içeren bir Pro paketi ileride ayrıca gelebilir;
bu üç stil ücretsiz ve MIT lisanslı kalır.

## Sorun giderme

- `doctor` "libass yok" diyorsa sorun değil: PIL motoru aynı düzeni çizer.
- Kelime zamanları kaymışsa: whisper.cpp cümle başlarını erken koyabilir; hat bunu sesteki konuşma
  bölgelerine göre onarır. Yine kötü ise `--asr faster-whisper --model medium` dene.
- Altyazı yanlış yerdeyse `--y`; yazı çok büyük/küçükse stilin `size` değeri `scripts/styles.py`.
