#!/bin/bash
# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
#
# Install or update Tapecut on a Mac:
#
#   curl -fsSL https://raw.githubusercontent.com/bravethea/tapecut/main/scripts/install.sh | bash
#
# Installs ffmpeg and Python 3.13 with Homebrew, puts the code in
# ~/Tapecut/app, builds its Python environment, and adds Tapecut.app to
# Applications. Running it again updates everything in place. Your
# transcripts and settings in ~/Tapecut are never touched.
#
# TAPECUT_DIR=/some/where overrides where the code goes.
set -euo pipefail

REPO="https://github.com/bravethea/tapecut.git"
DIR="${TAPECUT_DIR:-$HOME/Tapecut/app}"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "Tapecut runs on macOS only."
[ "$(uname -m)" = "arm64" ] || echo "Note: Tapecut is built for Apple Silicon; Intel Macs are untested."

# Homebrew's own installer asks for a password and confirmation, which can't
# happen inside `curl | bash`, so point at it instead of running it.
if ! command -v brew >/dev/null 2>&1; then
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        [ -x "$b" ] && eval "$("$b" shellenv)" && break
    done
fi
command -v brew >/dev/null 2>&1 || die "Tapecut needs Homebrew. Install it from https://brew.sh, then run this again."

say "Installing ffmpeg and Python 3.13 (Homebrew)…"
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
brew list python@3.13 >/dev/null 2>&1 || brew install python@3.13
PYTHON="$(brew --prefix python@3.13)/bin/python3.13"
[ -x "$PYTHON" ] || die "Couldn't find Python 3.13 at $PYTHON."

if [ -d "$DIR/.git" ]; then
    say "Updating Tapecut in $DIR…"
    git -C "$DIR" pull --ff-only || die "Couldn't update $DIR — it has local changes. Commit or discard them and try again."
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
    die "$DIR already exists and isn't a Tapecut checkout. Move it, or set TAPECUT_DIR to install elsewhere."
else
    say "Downloading Tapecut to $DIR…"
    mkdir -p "$(dirname "$DIR")"
    git clone --depth 1 "$REPO" "$DIR"
fi

say "Installing Tapecut's Python packages — a few GB, this takes several minutes…"
[ -x "$DIR/venv/bin/python" ] || "$PYTHON" -m venv "$DIR/venv"
"$DIR/venv/bin/python" -m pip install --quiet --upgrade pip
"$DIR/venv/bin/python" -m pip install --quiet -r "$DIR/requirements.txt"

say "Adding Tapecut to your Applications…"
"$DIR/scripts/make-app.sh"

say "Done."
cat <<EOF
Open Tapecut from Launchpad or Spotlight, or drag it from Applications to the
Dock. The first transcription downloads the Whisper model (~1.6 GB) once;
after that everything runs offline on this Mac.

To update later, run the same install command again.
Optional extras (Google Drive, speaker labels):
https://github.com/bravethea/tapecut/blob/main/docs/SETUP.md
EOF
