# Turkish Caption Pipeline (free Claude Code skill)

Turkish speech video or audio → word-timed captions: **SRT + styled ASS + burned-in MP4**, with
correct Turkish casing: **İSTANBUL**, not ISTANBUL.

Made by Redirhan Studio. Free, MIT licensed. Runs fully locally: no publishing, no accounts, no paid APIs.

## Why

Most caption tools and AI-written code uppercase Turkish with English rules:

```python
"istanbul".upper()   # 'ISTANBUL'   (wrong)
tr_upper("istanbul") # 'İSTANBUL'   (right)
```

The same applies to JS `toUpperCase()` and CSS `text-transform: uppercase` without `lang="tr"`.

## What it does

- **Transcription:** local whisper.cpp or faster-whisper with word timestamps. whisper.cpp tends to put
  sentence starts inside the preceding silence; the pipeline re-seats words onto speech regions found in the audio.
- **Turkish casing:** `tr_upper`, `tr_lower`, `tr_title` (conjunctions stay lowercase; TL/YouTube/iPhone kept).
- **ASR fixes:** `Istanbul → İstanbul`, `ISKELESIYDI → İSKELESİYDİ` (vowel harmony, leaves unsure words alone),
  `Işık/Irak/Isparta` kept, split suffixes merged (`İzmir` + `'e`), `50% → %50`, common misspellings
  (`herşey → her şey`), sentence-initial `Şeyh → şey` (suggestion), and Whisper's Turkish hallucinations
  ("Altyazı M.K.", "İzlediğiniz için teşekkürler") removed.
- **Trim suggestions:** filler sounds, detached discourse fillers (şey, yani, hani, işte), stutters,
  pauses over 0.6 s. `trim --uygula` cuts them and shifts caption times.
- **Line breaking for reels:** 1-2 lines inside the platform safe area; Turkish rules (no "ve/ile/bir"
  at line end, no "de/da/ki/mi" at line start, number + unit kept together).
- **Outputs:** `.srt`, styled `.ass`, positioned `.json` (for HyperFrames/Remotion), burned `.mp4`,
  a preview contact sheet and a report.

Three free styles: `temiz` (clean), `kalin-vurgu` (bold keyword), `karaoke` (karaoke highlight).
A Pro style pack may come later; these three stay free and MIT.

## Install

```bash
mkdir -p ~/.claude/skills && cp -R turkce-altyazi ~/.claude/skills/
python3 -m venv ~/.venvs/turkce-altyazi
~/.venvs/turkce-altyazi/bin/pip install -r ~/.claude/skills/turkce-altyazi/requirements.txt
brew install ffmpeg            # or: sudo apt install ffmpeg
~/.venvs/turkce-altyazi/bin/python ~/.claude/skills/turkce-altyazi/scripts/altyazi.py doctor
```

Transcription engine (one of):
- **whisper.cpp:** `brew install whisper-cpp`, put `ggml-large-v3-turbo-q5_0.bin` (from the
  ggerganov/whisper.cpp repo on Hugging Face) into `~/.cache/whisper-cpp/` or set `TA_WHISPER_CPP_MODEL`.
- **faster-whisper:** `pip install faster-whisper` (model downloads on first use; default `small`).

No engine? Bring your own SRT: `--srt file.srt`.

Burn engine: if `ffmpeg -filters | grep -E "ass|subtitles"` lists `ass` (libass), captions are burned with
ffmpeg's ass filter; otherwise a PIL renderer draws the same layout and composites it. `drawtext` is never used.

## Usage

```bash
PY=~/.venvs/turkce-altyazi/bin/python; S=~/.claude/skills/turkce-altyazi/scripts
$PY $S/altyazi.py run video.mp4 --stil kalin-vurgu      # -> altyazi_cikti/
$PY $S/altyazi.py run video.mp4 --stil hepsi            # all three styles
$PY $S/altyazi.py demo --cikti altyazi_demo             # build the bundled demo
```

`examples/demo_once_sonra.mp4` shows a self-made 11.6 s Turkish narration (synthesized locally with
EMA-TTS, not a real person) captioned with `str.upper()` on the left and this pipeline on the right.

## Limits

Whisper can mishear Turkish names and terms, so a human should do the final read. The ass burn path
needs an ffmpeg built with libass; our dev machine's ffmpeg has none, so the examples were burned with the PIL engine.

## License

MIT, Redirhan Studio. Fonts: Montserrat (SIL OFL 1.1). Demo narration generated locally with EMA-TTS (Apache-2.0).
