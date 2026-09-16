# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Tapecut edits audio and video by editing the transcript: transcribe once with
per-word timestamps, then cross words out and the media follows. Local-only,
macOS/Apple Silicon. Two front ends share one engine — a Flask browser UI (the
real app) and an older PyQt6 desktop window (maintained, not grown).

## Commands

```bash
venv/bin/python -m web.server            # browser UI on http://127.0.0.1:8756
PORT=9000 venv/bin/python -m web.server  # different port
venv/bin/python main.py                  # native desktop window

venv/bin/python -m pytest tests/ -q                          # all tests
venv/bin/python -m pytest tests/test_audio_editor.py -q      # one file
venv/bin/python -m pytest tests/test_audio_editor.py::test_name -q
venv/bin/python -m pytest tests/ -q -k pause                 # by keyword
```

Always use `venv/bin/python`, not a bare `python`. There is no linter, no build
step and no pytest config — `web/static/` is plain HTML/CSS/JS, so edit and
reload.

## Architecture

**`core/` is the engine and imports no UI.** Both front ends collect intent and
call into it. That is what makes `core/` testable without a display, and it is
worth preserving — if you find yourself importing PyQt or Flask into `core/`,
the logic belongs elsewhere.

**The word list is the timeline.** A transcript is a flat list of dicts:

```python
{"word": "hello", "start": 12.40, "end": 12.71, "probability": 0.98, "deleted": False}
```

There is no separate edit list and no timeline model. Cutting a word sets
`deleted: True`; `core/audio_editor.py:compute_kept_segments()` turns the
surviving words into time ranges, and everything downstream (preview, export,
text export, stats) consumes those ranges. **Start there when tracing how an
edit becomes media.**

> The per-word flag is **`deleted`**. `cut` is only a CSS class name and a
> library stat (`n_cut`). Do not introduce a `cut` field.

**Preview is client-side; export is server-side.** The browser plays the
*original* file through `<video>` with range requests and skips deleted regions
in JavaScript, so preview is instant and nothing is rebuilt to hear an edit. The
server only touches media at export time. Keep it that way — a server-side
preview rebuild would undo the main design win.

**Long work runs as background jobs.** `web/server.py:_start_job()` spawns a
thread and returns a job id; the client polls `GET /api/job/<id>`.
Transcription, Drive fetches, diarization and export all go through it. Anything
that can take minutes should too.

**Two persistence layers.** The browser UI writes to the library
(`core/library.py` → `~/Tapecut/transcripts`, JSON + a readable `.txt`), keyed on
**filename + size** — so renaming a file makes Tapecut treat it as a new
recording. The desktop app writes a `<file>.tapecut.json` sidecar
(`core/project.py`), which the library still reads as a legacy fallback.

The client holds transcript state and `POST /api/save` persists it; the server
does not maintain a live session model.

## Things that will bite you

**Constants are duplicated between Python and JavaScript.** The filler regex
(`core/filler_detector.py:FILLER_PATTERN` ↔ `app.js:FILLER_RE`) and the pause
constants (`PAUSE_KEEP_SEC`/`PAUSE_MIN_GAP_SEC` ↔ `PAUSE_KEEP`/
`PAUSE_MIN_GAP_DEFAULT`) exist in both. Change one and you must change the
other, or preview and export will disagree.

**`compute_kept_segments()` deliberately drops the silence around cut words.** A
run spans first-kept-word start → last-kept-word end. A variant preserving that
silence was tried and reverted because it left dead air around every cut; the
docstring says so. Don't "fix" it.

**Playback conversion is for playback only.** `core/convert.py` makes
browser-playable copies of `.wma/.aiff/.avi/.mov/.mkv` in
`~/Tapecut/cache/playback`. Transcription and export always read the user's
original file, so nothing is re-compressed and timestamps stay exact. Never
route transcription or export through a converted copy.

**Audio vs video is decided by probing streams, not extensions**
(`core/export.py:has_video_stream`). Plenty of `.mp4` files here are audio-only
containers.

**The verbatim primer must not become hotwords.** `core/transcriber.py` passes
the *user's* vocabulary as faster-whisper `hotwords` and
`VERBATIM_PRIMER + vocab` as `initial_prompt`. Boosting the primer's words would
bias the transcript toward them. The primer is why transcripts contain "um" at
all — Whisper otherwise tidies speech up, and a stumble it never writes down is
audio the user can never click on and cut.

**CSS wrapping rules are load-bearing** (`web/static/style.css`). `button` sets
`white-space: nowrap` for one-line buttons, so composite buttons (`.mode-card`,
`.menu-item`) explicitly reset it — children inherit it otherwise. Flex rows
wrap and grid tracks are `minmax(0, 1fr)`: a non-wrapping row sets a min-content
floor for the entire page and the layout ends up wider than the window. After
any CSS change, check a narrow window as well as a wide one.

Colours are all custom properties in `:root`, redeclared under
`@media (prefers-color-scheme: dark)` and `[data-theme="dark"]`. Never hardcode
a colour in a component rule.

## Project conventions

**This repository is public** (https://github.com/bravethea/tapecut). Keep the
owner's personal data out of it: Drive folders, absolute `/Users/...` paths,
tokens, references to other non-public projects, and any recordings. Shipped
defaults are neutral — `drive_folder` defaults to `""` (the remote's root), and
the HuggingFace token resolves via env var, `config.json`, or a config-named
`.env`. All user settings live in `~/Tapecut/config.json`, outside the repo.
`PLAN.md` is gitignored for this reason.

**Licence: AGPL-3.0-or-later.** New `.py` files get the three-line header the
existing ones carry. The licence's "Appropriate Legal Notices" live in the web
help sheet (`index.html`, `.legal`) and the desktop **Help → About** dialog —
don't remove them.

**Tests cover `core/` only** — no UI, no network, no model downloads. New logic
in `core/` should come with a test.

**Prefer the browser UI** for new features. The desktop app lacks the library,
Drive, speakers, text export and summarising, and that is intentional.
