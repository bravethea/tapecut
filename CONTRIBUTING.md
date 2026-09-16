# Contributing

Bug reports, fixes and small features are welcome.

## Getting set up

```bash
git clone https://github.com/bravethea/tapecut.git
cd tapecut
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python -m pytest tests/ -q
```

[docs/SETUP.md](docs/SETUP.md) covers the optional pieces (Drive, speaker
identification). [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains how the
code is laid out — worth ten minutes before a first change.

## Before you send a change

- **Tests pass**: `venv/bin/python -m pytest tests/ -q`
- **New logic in `core/` comes with a test.** `core/` has no UI imports and no
  network calls in tests, so it is cheap to test — please keep it that way.
- **Both UIs still start**: `venv/bin/python -m web.server` and
  `venv/bin/python main.py`
- **Touched the CSS?** Check the page at a narrow window as well as a wide one.
  Nothing should scroll sideways, and text should wrap inside its container.

## House style

- Match the surrounding code. Comments explain *why*, not *what*.
- Keep `core/` free of UI imports.
- Prefer adding to the browser UI; the desktop app is maintained, not grown.
- No new dependencies without a good reason — the install is already large.

## Reporting a bug

Please include your macOS version, `python3 --version`, `ffmpeg -version` (first
line), what you did, what happened, and what you expected. If it involves a
specific recording, its format and duration usually matter more than the file
itself — **please do not attach recordings**.

## Licensing

Tapecut is AGPL v3. By contributing you agree your contribution is licensed the
same way. Do not paste in code you do not have the right to relicense.
