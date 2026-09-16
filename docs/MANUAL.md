# Tapecut — the manual

Everything Tapecut does, what each thing is for, and when to reach for it.

New here? [The README](../README.md) gets you installed and through a first
edit; [SETUP.md](SETUP.md) covers Google Drive and speaker identification.

**Contents**

1. [The idea](#1-the-idea)
2. [The workspace](#2-the-workspace)
3. [Opening a recording](#3-opening-a-recording)
4. [Transcribing](#4-transcribing)
5. [Editing the transcript](#5-editing-the-transcript)
6. [Cleaning up speech](#6-cleaning-up-speech) — fillers, repeats, pauses
7. [Speakers](#7-speakers)
8. [Exporting media](#8-exporting-media)
9. [Exporting text](#9-exporting-text)
10. [Summarise & extract](#10-summarise--extract)
11. [The transcript library](#11-the-transcript-library)
12. [Keyboard & mouse](#12-keyboard--mouse)
13. [When things go wrong](#13-when-things-go-wrong)
14. [The desktop app](#14-the-desktop-app)

---

## 1. The idea

Tapecut transcribes your recording once, with a timestamp on every single word.
From then on the transcript *is* the timeline. Cross a word out and the audio
under that word is gone from the export. There is no waveform to aim at and no
region to drag — you edit the words and the media follows.

Because every word carries its own start and end time, cuts are exact: what you
hear in the preview is what lands in the exported file.

Three tasks share that one transcript:

- **✂️ Edit a recording** — cut, then export media
- **📝 Transcribe & get the text** — read, correct, label, export text
- **🧠 Summarise & extract** — notes and action items

Pick one at the start; switch whenever you like with **Change task** in the top
bar, or link straight to one with `#edit`, `#text` or `#notes` on the URL.
Nothing is lost when you switch.

## 2. The workspace

**The rail** on the left holds your sources, in three tabs — **Drive**,
**Library** and **This Mac** — each filterable by name.

**The transcript** takes the main column and starts at the top of the page. The
player and the editing tools stay pinned above it while you scroll.

**The top bar** carries a job chip. Long jobs — transcription, speaker
identification, export — report into it, it survives scrolling, and it stays put
when the job finishes. Start a 35-minute job and walk away.

**‹ Back** in the top bar closes the recording and returns you to the source
list, keeping the task you are in. **esc** does the same. (**Change task** is a
different thing: it switches between editing, text and notes.)

**◐** in the top bar cycles light → dark → follow-the-system. **?** (or **⌘/**)
shows the shortcut list.

**Saving** happens by itself. The green dot at the bottom right turns amber
while a save is in flight and green when it lands. There is no save button
because there is nothing to remember to press.

## 3. Opening a recording

**From this Mac.** *This Mac → 📂 Choose a file…* opens the real macOS Finder
dialog. (A browser `<input type=file>` cannot tell the server where a file is on
disk, so Tapecut asks macOS directly — which works only because the server is
running on your own machine.) You can also paste a path.

**From Google Drive.** If you have set up an rclone remote — see
[SETUP.md](SETUP.md) — the Drive tab lists your recordings. **Fetch & open**
downloads one; **🎲 Random recording** picks one for you, preferring recordings
you have not transcribed yet. Files land in `~/Tapecut/cache`, only the three
most recent are kept, and nothing is ever written back to Drive.

**From the library.** Anything you have transcribed before reopens instantly,
with every edit intact. See [§11](#11-the-transcript-library).

A recording with no transcript yet still opens fully: you get the player, so you
can listen before deciding to transcribe. The transcript area stays empty and
the tools that need words are switched off until you press **Transcribe**.

### Formats

Most formats need no conversion — **mp3, wav, m4a, mp4, flac, opus, ogg** and
**webm** play, seek and transcribe directly.

For the few a browser genuinely cannot play — **.wma, .aiff, .avi, .mov, .mkv**
— Tapecut makes a browser-playable copy when you open the file, showing
"Converting for playback…". That is a one-time step per file, cached in
`~/Tapecut/cache/playback`, and it is used **only for the preview player**:
transcription and export always read your original file, so nothing is
re-compressed and timestamps stay exact. Files whose codecs are already fine (an
H.264/AAC `.mov`, say) are remuxed rather than re-encoded — about a second.

### Audio or video?

Tapecut decides by **probing the file's streams**, not by its extension. Plenty
of `.mp4` files are audio-only containers with no picture track; those get the
compact player and MP4-over-cover-image export. The label under the player tells
you which kind you have.

## 4. Transcribing

Press **Transcribe**. The first run ever downloads the Whisper model (~1.6 GB);
after that everything is offline. A 30-minute recording takes a few minutes on
Apple Silicon.

**Vocabulary hint.** Names, jargon, Pali or Sanskrit terms, place names —
anything unusual. The hint is passed to faster-whisper as `hotwords`, which
meaningfully improves how often those words come out right.

**Language.** Set it if you know it. Auto-detect works but costs a little
accuracy, and it can go wrong on a recording that opens with silence or music.

### Why the transcript includes "um"

Whisper tidies speech up by default. That is a problem here: a stumble it never
writes down is audio you can never cut, because there is no word on screen to
click.

So transcription is primed with a hesitant, stumbling prompt (`VERBATIM_PRIMER`
in `core/transcriber.py`) that makes it write what was actually said. Measured
on a 90-second sample: 165 → 174 words, and every added word was an "um" or "uh"
that had previously been dropped.

Transcripts made before this behaviour existed are not verbatim. Re-transcribe
if you want their disfluencies back.

### Silence

Voice-activity detection runs before transcription, so silent stretches produce
no text at all. This matters on recordings that are mostly silence — a guided
meditation, a long pause for reflection — where Whisper without VAD will happily
hallucinate sentences into the gap.

## 5. Editing the transcript

| Action | Effect |
|---|---|
| **Click** a word | cut it — or restore it if it was cut |
| **Drag** across words | cut the whole range |
| **⌥-click**, **⌥-drag** | restore only, never cut |
| **Right-click** a word | correct its text (**↵** saves, **esc** cancels) |
| **Double-click** | move the playhead there |
| **Space** | play / pause the preview |
| **⌘Z** | undo |

Cut words stay on screen, struck through — nothing is ever hidden from you, and
everything is reversible.

**Correcting text** is for when Whisper mishears a name or an unusual term. The
correction changes the word in the transcript and in every text export; it does
not change the audio, which is still the audio of whatever was actually said.

**▶ Preview** plays the edited result with cut regions skipped, highlighting the
current word as it goes. Untick **skip cuts** to hear the original.

In the audio preview, cuts are joined with a 30 ms crossfade so joins do not
click.

## 6. Cleaning up speech

### Fillers

**Clean up → Find fillers** marks disfluencies with a wavy underline — it marks
them, it does not delete them. Read through, **⌥-click** any you want to keep,
then confirm **Delete them**.

Vocalized fillers are matched by pattern, so elongated spellings count too:
um / umm / ummm, uh / uhh / uhhh, uhm, ah / ahh / ahm, er / erm, eh, hm / hmm,
mm / mhm. Phrase fillers are matched too: *you know, kind of, sort of, I mean,
like, so, basically, actually*, and others.

Phrase fillers are the ones to read carefully. "Like" is a filler in "it was
like, really long" and not in "a mind like water".

### Repeats and stutters

Right after transcription, repeated words ("the the", "how how's") and stutters
("wh- what") are **crossed out for you**. They stay visible, struck through, and
⌥-click or ⌘Z brings any of them back. **Clean up → Cross out repeats &
stutters** runs the same pass again whenever you want it.

Deliberate repetition is left alone. Repeats more than 0.8 s apart, repeats
across a sentence boundary ("settling in. In fact"), and rhetorical chains
("more and more and more") are all preserved.

### Pauses

Every silence at or above the threshold — default **1 s**, set it in
**Clean up → pauses over `[1]` s** — appears as a marker in the transcript: a
faint vertical bar in the flow of the text, taller for a longer pause. They stay
quiet while you read and lift when you move the pointer into the transcript,
which is when you are looking for them.

**Click a marker** to trim that pause to about half a second (0.25 s of air is
kept on each side, so the join breathes). Click again to restore it.
**Trim pauses (N)** does all of them at once, and flips to **Restore pauses**
when everything is trimmed.

Untouched pauses stay exactly as recorded. Nothing is trimmed unless you say so.

> **On a guided meditation, "trim all" is rarely what you want.** A 35-minute
> session can be 25 minutes of deliberate silence. Trimming individual markers
> around the talking sections is usually the right move.

**Lower thresholds catch disfluencies Whisper never transcribed.** An
untranscribed "ahhh" sits inside the gap between two words — there is no word to
click, but trimming the gap removes the sound. If you can hear something you
cannot see, drop the threshold to 0.4 s or so and look there.

## 7. Speakers

Press **🗣 Identify speakers** to run diarization (pyannote, via whisperX). Set
the speaker count if you know it, or leave it on **auto**. Expect it to take
roughly as long as the recording itself.

Labels then appear as coloured headings throughout the transcript, in the
library, and in every text export. **Click any name to rename it** —
`SPEAKER_00` → `Teodora` — and the new name is used everywhere.

Diarization needs a HuggingFace token; [SETUP.md](SETUP.md) explains how to get
one and where to put it. Without a token the button tells you so and nothing
else changes.

## 8. Exporting media

Pick a format next to **Export**.

**Video in → video out.** Every cut you make — words, ranges, trimmed pauses —
is applied to the picture too, frame-accurately, via ffmpeg trim + concat
(H.264 CRF 18 + AAC). Verified end to end: cutting 0–10 s and 40–50 s produced a
file that jumps from source t=9 s straight to t=42 s, with audio still in sync
to within 8 ms.

**Audio in → audio out.** MP3 or WAV.

**Audio in → MP4 for YouTube.** The edited audio is rendered over a still cover
image at 1920×1080 (H.264 + AAC 192k, faststart) — exactly what YouTube wants.
Encoding runs about 10× faster than realtime, so a 35-minute session takes a few
minutes and lands around 40 MB.

Manage cover images in the **MP4 cover image** panel at the bottom of the rail:
click a thumbnail to make it the default, or add one by local path or Drive path
(`gdrive:…/cover.png`). Covers live in `~/Tapecut/assets`; the default is
remembered in `~/Tapecut/config.json`.

Exports of recordings that came from Drive land in `~/Tapecut/exports`.

## 9. Exporting text

The **Transcript text** panel previews the transcript as **plain text**,
**Markdown**, **SRT** or **WebVTT**, with **Copy** and **Save file** (into
`~/Tapecut/exports`).

Tick **include cut words** for a verbatim record — removed words appear in
[brackets], so the file shows both what was said and what you took out.

Speaker names, if you have set them, appear in every format.

## 10. Summarise & extract

Four things, from the **Summarise & extract** tab:

- **Meeting notes** — summary, decisions, action items, open questions
- **Summary**
- **Action items** — as a checklist
- **Key points**

Results are saved with the transcript and can be copied or saved as Markdown.

Tapecut uses whichever backend it can find, best first:

1. `ANTHROPIC_API_KEY`, if it is set in the environment
2. the `claude` CLI, if you are signed in (run `claude` once in a terminal)
3. a built-in extraction pass that needs no model at all — it quotes action
   items, decisions and questions straight from the transcript, and says that it
   is doing so

The panel tells you which one is active. Only backends 1 and 2 send text off
your machine; the built-in pass does not.

## 11. The transcript library

Every transcript and every edit is stored permanently in `~/Tapecut/transcripts`
— as JSON, and as a readable `.txt` with cut words in brackets that you can
search with Spotlight or grep like any other file.

The **Library** tab lists them all. Each row has:

- **View** — read it. Tick two checkboxes to compare two transcripts side by
  side.
- **Edit** — reopen the recording in the editor with every saved edit intact:
  word cuts, corrected words, trimmed pauses. Carry on where you left off.
- **a format picker + Export** — re-export a saved edit at any time, without
  redoing the work. Months later is fine.

Transcripts survive cache eviction, so reopening a Drive recording never
re-transcribes it. If the media is no longer cached it is re-downloaded from
Drive automatically, and if the file has moved, Tapecut searches your Drive
folder for one of the same name.

**If the recording file itself is gone** — moved, renamed or deleted — **Edit**
still opens the transcript. The words stay readable and correctable, with a red
bar explaining that playback and export are off until the file turns up.

> Entries are keyed on **name + size**, so renaming a file makes Tapecut treat
> it as a new recording.

## 12. Keyboard & mouse

| | |
|---|---|
| Click | cut a word / restore it |
| Drag | cut a range of words |
| ⌥ Click | restore, never cut |
| Right-click | correct the word's text (↵ save, esc cancel) |
| Double-click | move the playhead there |
| Space | play / pause the preview |
| ⌘Z | undo |
| esc | back out one level — a sheet, then a filler review, then the recording |
| ⌘/ | the shortcut list |

## 13. When things go wrong

**"Missing dependencies" on startup.** Install what it names:
`brew install ffmpeg portaudio`.

**Drive says "not connected".** Re-authorize the remote:

```bash
rclone config create gdrive drive scope=drive.readonly
```

**"Identify speakers" says it needs a token.** See [SETUP.md](SETUP.md) — you
need a HuggingFace token and you must accept the pyannote model's conditions on
its model page.

**The recording has no audio.** Tapecut checks the first minute and warns you if
there is nothing there. Usually this means a failed recording, not a bug.

**A stumble you can hear but cannot see.** It was never transcribed. Lower the
pause threshold (§6) and trim the gap it is sitting in.

**The transcript is not verbatim.** It predates the verbatim primer.
Re-transcribe.

**Playback stutters or will not seek.** Your file is in a format the browser
cannot play natively; Tapecut should convert it automatically, but you can also
convert it yourself with ffmpeg and open the copy.

**Port 8756 is busy.** `PORT=9000 venv/bin/python -m web.server`.

## 14. The desktop app

`venv/bin/python main.py` opens a native PyQt window. It predates the browser UI
and has editing, filler detection and export, but **not** the library, Drive,
speakers, text export or summarising. Use the browser UI unless you specifically
want a native window.

1. **Open…** (⌘O) — audio (.mp3 .wav .m4a .flac) or video (.mp4 .mov .m4v .mkv
   .webm)
2. Optionally type vocabulary hints in the prompt box
3. **Transcribe**
4. Edit with the same click / drag / ⌥-click / right-click vocabulary
5. **▶ Preview**
6. **Find Fillers**
7. **Export…** (⌘E)

The desktop app saves to a `<file>.tapecut.json` sidecar next to the media file
rather than to the library. Delete the sidecar to start fresh.
