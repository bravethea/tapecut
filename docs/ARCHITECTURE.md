# Architecture

How Tapecut is put together, for anyone changing it.

## The shape of it

```
main.py            native desktop app entry point (PyQt6)
ui/                the desktop window — older, narrower in scope
web/               the browser UI — Flask server + a single static page
core/              everything that actually does work; no UI imports
tests/             pytest, all against core/
```

**`core/` knows nothing about either UI.** Both front ends are thin: they
collect intent and call into `core`. That is what makes the browser UI and the
desktop window able to share an engine, and what makes `core` testable without a
display.

## The central data structure

A transcript is a list of **words**, each with its own timing and state:

```python
{"word": "hello", "start": 12.40, "end": 12.71, "cut": False, "speaker": "SPEAKER_00"}
```

Everything follows from per-word timestamps. "Cut a word" sets `cut: True`.
"Export" turns the surviving words into time ranges and hands those to ffmpeg or
pydub. There is no separate edit list and no separate timeline — the word array
*is* the edit.

`core/audio_editor.py:compute_kept_segments()` is the function that converts
word states into the ranges everything downstream uses. If you are looking for
where an edit becomes media, start there.

## `core/` module by module

| Module | Responsibility |
|---|---|
| `transcriber.py` | whisperX: faster-whisper large-v3 + VAD + wav2vec2 alignment. Owns `VERBATIM_PRIMER` and `SUPPORTED_FORMATS`. |
| `audio_editor.py` | Word states → kept time ranges. Pause detection and pause trimming. Builds edited audio with a 30 ms crossfade. |
| `export.py` | ffmpeg: video trim+concat, audio export, audio→MP4 over a cover image. Stream probing (`has_video_stream`). |
| `convert.py` | Browser-playable copies of formats an `<video>` cannot open. Playback only — never used for transcription or export. |
| `library.py` | `~/Tapecut` — app dirs, `config.json`, the permanent transcript store (JSON + readable `.txt`). Entries keyed on name + size. |
| `project.py` | The legacy per-file `<file>.tapecut.json` sidecar, still read as a fallback and still what the desktop app writes. |
| `drive.py` | rclone, read-only. Listing, fetching, cache pruning to the 3 newest files. |
| `diarize.py` | pyannote via whisperX. Token resolution. Attaches a speaker to each word. |
| `disfluency.py` | Repeated words and stutters, conservatively — time gap, sentence boundary and rhetorical-chain guards. |
| `filler_detector.py` | Vocalized fillers by regex, phrase fillers by list. |
| `textexport.py` | Transcript → TXT / Markdown / SRT / WebVTT, with or without cut words. |
| `summarize.py` | Summaries and extraction. Three backends: API key → `claude` CLI → rule-based local pass. |
| `player.py` | Desktop-only audio preview (sounddevice + pydub). The browser UI does not use this. |

## The browser UI

`web/server.py` is a Flask app on `127.0.0.1:8756`. `web/static/` is one HTML
page, one stylesheet and one script — no build step, no framework, no bundler.
Edit the files and reload.

**Preview is client-side.** The browser plays the *original* file through
`<video>` with HTTP range requests and skips cut regions in JavaScript. Nothing
is rebuilt server-side to hear an edit, which is why preview is instant. The
server only does real media work at export time.

**Long work runs as background jobs.** `_start_job()` spawns a thread, returns a
job id, and the client polls `GET /api/job/<id>`. Transcription, Drive fetches,
diarization and export all go through it. That is what lets the job chip survive
scrolling and let you walk away from a 35-minute export.

### Routes, grouped

| Group | Routes |
|---|---|
| Page & media | `GET /`, `GET /static/<name>`, `GET /media` (range requests) |
| Opening | `POST /api/open`, `/api/browse` (native Finder dialog), `/api/convert` |
| Drive | `GET /api/drive/status`, `/api/drive/list`; `POST /api/drive/folder`, `/api/drive/fetch` |
| Library | `GET /api/library`, `/api/library/<key>`; `POST /api/library/<key>/open`, `/api/library/<key>/export` |
| Transcript | `POST /api/transcribe`, `/api/save`, `/api/disfluencies` |
| Speakers | `GET /api/diarize/status`; `POST /api/diarize` |
| Text | `POST /api/text`, `/api/text/save` |
| Analysis | `GET /api/analyse/backend`; `POST /api/analyse` |
| Export | `POST /api/export` |
| Covers | `GET /api/cover`, `/api/cover/image/<name>`; `POST /api/cover` |
| Jobs | `GET /api/job/<job_id>` |

`/api/browse` is worth knowing about: a browser `<input type=file>` cannot give
the server a real path, so Tapecut shells out to the macOS Finder dialog and
gets the true path back. It only works because the server is on the same machine
as the browser.

## CSS conventions

`web/static/style.css` is tokens first, components second. Every colour is a
custom property declared in `:root`, redeclared under
`@media (prefers-color-scheme: dark)` and again under `[data-theme="dark"]`, so
the two themes always resolve as a complete set and the manual toggle wins in
both directions. Do not hardcode a colour in a component rule.

Two wrapping rules that are load-bearing, and easy to undo by accident:

- `button` sets `white-space: nowrap` for plain one-line buttons, so anything
  composite (`.mode-card`, `.menu-item`) must reset it — children inherit it.
- Flex rows wrap and grid tracks are `minmax(0, 1fr)`. A non-wrapping row sets a
  min-content floor for the whole page, which is how the layout ends up wider
  than the window.

## The desktop app

`main.py` + `ui/`. It predates the browser UI and has editing, filler detection
and export, but not the library, Drive, speakers, text export or summarising. It
persists to the `project.py` sidecar rather than the library.

It is kept working, not actively grown. New features go in the browser UI.

Because it links PyQt6 (GPL v3), the desktop app is the reason Tapecut is
AGPL v3 rather than something more permissive — see [COPYRIGHT](../COPYRIGHT).

## Tests

`tests/` is pytest against `core/` only — no UI, no network, no model downloads.
Anything needing whisperX at import time is skipped.

```bash
venv/bin/python -m pytest tests/ -q
```

Media-handling code is tested through generated fixtures rather than checked-in
recordings; `.gitignore` excludes every media extension so a real recording
cannot be committed by accident.
