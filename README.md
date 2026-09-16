# Tapecut

**Edit audio and video by editing the transcript.** Delete a word from the text
and it disappears from the recording. A local, private, Descript-style editor
for macOS on Apple Silicon.

It was built for cleaning up guided-meditation recordings before publishing to
YouTube — transcribe once, click the words you want gone, preview, export — but
nothing about it is specific to that. It works on interviews, lectures,
podcasts, lesson recordings and anything else made mostly of speech.

**Everything runs on your machine.** Transcription is whisperX (faster-whisper
large-v3 + voice-activity detection + wav2vec2 word alignment). No audio, no
text and no metadata is uploaded anywhere. The first run downloads the Whisper
model (~1.6 GB); after that it works with the network off.

---

## What you can do with it

| | |
|---|---|
| **✂️ Edit a recording** | Click words to cut them. Cut fillers, repeats, stutters and over-long pauses. Preview the edit instantly. Export edited audio, or a YouTube-ready MP4. |
| **📝 Transcribe & get the text** | Read the transcript, correct mishearings, label who spoke, export TXT / Markdown / SRT / WebVTT. |
| **🧠 Summarise & extract** | Meeting notes, decisions, action items, key points. |

All three share one transcript, so you can switch between them at any time, and
everything you do is saved against the recording — a transcript you summarise
today can be edited a year from now.

---

## Requirements

- macOS on Apple Silicon (Intel Macs are untested)
- Python 3.11 or newer (3.13 is what it is developed against)
- `ffmpeg` — `brew install ffmpeg`
- `portaudio` — `brew install portaudio` (only for the desktop app's preview)
- About 3 GB of disk for the Whisper model and its dependencies

Optional:

- `rclone` — `brew install rclone`, only if you want to pull recordings from
  Google Drive
- A HuggingFace token — only if you want speaker identification

## Install

```bash
git clone https://github.com/bravethea/tapecut.git
cd tapecut
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## Run

The browser UI is the one to use — it is the complete app:

```bash
venv/bin/python -m web.server
```

Then open **<http://127.0.0.1:8756>**. It listens on localhost only; nothing is
exposed to your network.

There is also an older native desktop window, which does editing and export but
none of the library, Drive, speaker or summarising features:

```bash
venv/bin/python main.py
```

## Your first edit

1. Open the browser UI and pick **Edit a recording**.
2. In the rail on the left choose **This Mac → 📂 Choose a file…** and pick a
   recording.
3. Press **Transcribe**. A 30-minute recording takes a few minutes.
4. Click any word to cut it. Click it again to bring it back.
5. Press **▶ Preview** to hear the edit with the cuts skipped.
6. Choose a format and press **Export**.

Nothing needs saving — edits save themselves as you make them (watch the green
dot, bottom right).

---

## Documentation

- **[docs/MANUAL.md](docs/MANUAL.md)** — the full manual. Every feature, what it
  does and when to reach for it.
- **[docs/SETUP.md](docs/SETUP.md)** — installation in detail, plus connecting
  Google Drive and enabling speaker identification.
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the code is laid out,
  for anyone changing it.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — running the tests, sending a change.

## Where your files live

Tapecut keeps everything it makes in `~/Tapecut`, outside this repository:

```
~/Tapecut/
  config.json      your settings — Drive remote, folder, token, cover image
  transcripts/     every transcript and edit, permanently (JSON + readable .txt)
  cache/           recordings temporarily downloaded from Drive (auto-pruned)
  exports/         exported audio and video
  assets/          cover images for rendering audio to MP4
```

Your recordings are never copied into the repository and never leave your
machine.

## Tests

```bash
venv/bin/python -m pytest tests/ -q
```

## Licence

Copyright © 2025–2026 Teodora Vuković (Teodora Vukovic).

Tapecut is free software under the **GNU Affero General Public License v3 or
later**. You may use, study, share and modify it; if you distribute it, or run a
modified version as a network service, you must offer the same freedoms and the
source to whoever uses it. See [LICENSE](LICENSE), and [COPYRIGHT](COPYRIGHT)
for the third-party components Tapecut builds on.

It comes with no warranty of any kind.
