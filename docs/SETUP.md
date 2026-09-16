# Setup

Installing Tapecut, and the two optional pieces — Google Drive and speaker
identification — that need a little configuration.

## 1. System dependencies

```bash
brew install ffmpeg portaudio
```

- **ffmpeg** does all media work: probing, conversion, export. Required.
- **portaudio** is only needed by the native desktop app's preview. The browser
  UI does not use it.

## 2. Tapecut itself

```bash
git clone https://github.com/bravethea/tapecut.git
cd tapecut
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

This pulls in whisperX and PyTorch, so it is a large install — a few GB and
several minutes.

Check it:

```bash
venv/bin/python -m pytest tests/ -q
venv/bin/python -m web.server
```

## 3. The Whisper model

Nothing to do in advance. The first time you press **Transcribe**, faster-whisper
downloads large-v3 (~1.6 GB) into the HuggingFace cache
(`~/.cache/huggingface`). After that, transcription needs no network at all.

## 4. Your settings file

Tapecut reads `~/Tapecut/config.json`, creating it on first run. Everything in
it is optional:

```json
{
  "drive_remote": "gdrive:",
  "drive_folder": "recordings/to-edit",
  "hf_token": "hf_...",
  "hf_token_env_file": "~/some-project/.env",
  "cover_image": "/Users/you/Tapecut/assets/cover.png"
}
```

| Key | What it does |
|---|---|
| `drive_remote` | the rclone remote to read from. Default `gdrive:` |
| `drive_folder` | which folder inside it to open at. Default `""` — the root |
| `hf_token` | HuggingFace token for speaker identification |
| `hf_token_env_file` | an `.env` file to read `HF_TOKEN` from, if you already keep one elsewhere |
| `cover_image` | the still image used when rendering audio to MP4 |

This file lives in your home directory, not in the repository, so it is never
committed and never shared.

---

## Optional: Google Drive

Tapecut reads Drive through [rclone](https://rclone.org), **read-only**. It can
list and download; it can never write, move or delete anything in your Drive.

### Connect your own Drive

```bash
brew install rclone
rclone config create gdrive drive scope=drive.readonly
```

That opens a browser window for you to sign in and approve read-only access. The
`scope=drive.readonly` is what makes the permission read-only — keep it.

Test it:

```bash
rclone lsd gdrive:
```

### Point Tapecut at a folder

The Drive tab opens at the root of the remote by default, and you can browse
down from there and edit the folder path in the box. To have it start somewhere
specific every time, put that path in `~/Tapecut/config.json`:

```json
{ "drive_remote": "gdrive:", "drive_folder": "recordings/to-edit" }
```

### Using a different remote

Any rclone remote works, not just Google Drive — Dropbox, OneDrive, S3, a WebDAV
server, a local directory. Create it with `rclone config`, then set
`drive_remote` to its name with a trailing colon, e.g. `"dropbox:"`.

### What gets downloaded, and where

Recordings you open are downloaded to `~/Tapecut/cache`. Only the three most
recent are kept; older ones are deleted automatically. Transcripts live
separately in `~/Tapecut/transcripts` and are never evicted, so reopening a
recording never re-transcribes it.

### If it says "not connected"

The remote is missing or its token has expired. Re-run:

```bash
rclone config create gdrive drive scope=drive.readonly
```

---

## Optional: speaker identification

Diarization ("who spoke when") uses pyannote through whisperX. The pyannote
models are gated on HuggingFace, so you need a free account and a token.

1. Make a HuggingFace account at <https://huggingface.co>.
2. Visit the pyannote speaker-diarization model page and **accept its
   conditions**. The token alone is not enough — the acceptance is per-model and
   per-account, and skipping it is the usual cause of a 401 here.
3. Create a token: **Settings → Access Tokens → New token**, `read` scope.
4. Give it to Tapecut, by any one of these:

   ```bash
   export TAPECUT_HF_TOKEN=hf_...     # or HF_TOKEN
   ```

   or in `~/Tapecut/config.json`:

   ```json
   { "hf_token": "hf_..." }
   ```

   or, if you already keep a token in another project's `.env`, point at that
   file instead of copying the secret around:

   ```json
   { "hf_token_env_file": "~/some-project/.env" }
   ```

   The file is read for a `HF_TOKEN=` line.

Tapecut looks in that order: `TAPECUT_HF_TOKEN`, `HF_TOKEN`, `hf_token`,
`hf_token_env_file`.

**Never commit a token.** `.gitignore` already excludes `.env` and `config.json`,
and `~/Tapecut/config.json` is outside the repository anyway.

Diarization runs on CPU and takes roughly as long as the recording.

---

## Optional: summarising

Summaries work with no setup at all — the built-in extraction pass needs no
model and sends nothing anywhere. If you want a better summary than
quote-extraction, Tapecut will use, in order:

1. `ANTHROPIC_API_KEY` in the environment
2. the `claude` CLI, if you have signed in with it (`claude` once in a terminal)

Both of those send transcript text to Anthropic. The panel always shows which
backend is active, so you can tell at a glance whether text is leaving the
machine.

---

## Running the server

```bash
venv/bin/python -m web.server        # http://127.0.0.1:8756
PORT=9000 venv/bin/python -m web.server
```

It binds to `127.0.0.1` only — it is not reachable from your network, and it has
no authentication because it does not need any.

Do not put it behind a public reverse proxy. It runs Flask's development server,
it executes ffmpeg on paths you give it, and the file browser will open any file
your user account can read. It is a local tool.

> If you do serve a modified Tapecut to other people over a network, the AGPL
> requires you to offer them its source. See [LICENSE](../LICENSE).
