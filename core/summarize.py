# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Transcript analysis: summary, decisions, action items, key topics.

Three backends, tried in order — the first that is usable wins:

  api    ANTHROPIC_API_KEY is set → Claude via the HTTP API (best quality)
  cli    the `claude` CLI is installed AND logged in → same models, no key
  local  always available → no LLM at all; a rule-based pass that pulls out
         action-item sentences, decisions, questions and frequent topics

The local backend means the feature works on a plane with no setup. It is
honest about what it is: extraction, not abstraction — it quotes the transcript
rather than writing prose about it.
"""
import json
import os
import re
import shutil
import subprocess
from collections import Counter

TIMEOUT = 300
MAX_CHARS = 120_000          # keep a long session inside one prompt

ACTION_PATTERNS = [
    r"\bI'?ll\b", r"\bwe'?ll\b", r"\bwe should\b", r"\bI should\b",
    r"\bwe need to\b", r"\bI need to\b", r"\bwe have to\b", r"\blet'?s\b",
    r"\bcan you\b", r"\bcould you\b", r"\bplease\b", r"\bto[- ]?do\b",
    r"\bnext step", r"\baction item", r"\bfollow up\b", r"\bwill send\b",
    r"\bwill share\b", r"\bgoing to\b", r"\bmake sure\b", r"\bremind\b",
]
DECISION_PATTERNS = [
    r"\bwe decided\b", r"\bwe agreed\b", r"\bdecision\b", r"\blet'?s go with\b",
    r"\bwe'?re going to\b", r"\bthe plan is\b", r"\bwe settled on\b",
]
DEADLINE_PATTERNS = [
    r"\bby (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\bby (?:next|this) (?:week|month|year)\b", r"\btomorrow\b",
    r"\bdeadline\b", r"\bdue\b", r"\bbefore the\b",
]
STOPWORDS = set("""
a an and are as at be been but by can could did do does for from had has have he her
his how i if in into is it its just like me more my no not of on or our out so than
that the their them then there these they this to too us was we were what when where
which who will with would you your yeah okay um uh really kind sort thing things about
""".split())


class SummarizeError(RuntimeError):
    pass


# ------------------------------------------------------------------ backends

def _api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


def _cli_ready() -> bool:
    """The CLI is only useful if it is installed AND authenticated."""
    exe = shutil.which("claude")
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "-p", "--output-format", "text"], input="ok",
                           capture_output=True, text=True, timeout=45)
    except Exception:
        return False
    return r.returncode == 0 and "Not logged in" not in (r.stdout + r.stderr)


def available_backend() -> str:
    if _api_key():
        return "api"
    if _cli_ready():
        return "cli"
    return "local"


def backend_info() -> dict:
    backend = available_backend()
    return {
        "backend": backend,
        "label": {
            "api": "Claude (API key)",
            "cli": "Claude (Claude Code CLI)",
            "local": "Built-in extraction (no AI model)",
        }[backend],
        "hint": "" if backend != "local" else
                "For written summaries, run `claude` once in a terminal and sign in, "
                "or set ANTHROPIC_API_KEY — then reload this page.",
    }


def _run_api(prompt: str) -> str:
    import urllib.request
    body = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"content-type": "application/json",
                 "x-api-key": _api_key(), "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.load(resp)
    return "".join(part.get("text", "") for part in data.get("content", []))


def _run_cli(prompt: str) -> str:
    r = subprocess.run([shutil.which("claude"), "-p", "--output-format", "text"],
                       input=prompt, capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        raise SummarizeError((r.stderr or r.stdout).strip()[:300])
    return r.stdout.strip()


PROMPTS = {
    "summary": (
        "Summarise this transcript. Give a short paragraph of what it covered, "
        "then bullet points of the main topics. Use the speaker labels where they help. "
        "Plain Markdown, no preamble."
    ),
    "meeting": (
        "Write meeting notes from this transcript, as Markdown with these sections, "
        "omitting any that genuinely have no content:\n"
        "## Summary\n## Decisions\n## Action items\n(one line each: owner — task — deadline if stated)\n"
        "## Open questions\n## Notes\n"
        "Only state what the transcript supports; do not invent owners or dates. No preamble."
    ),
    "todos": (
        "List every action item, task or commitment in this transcript as a Markdown "
        "checklist: `- [ ] owner — task — deadline (if stated)`. Use 'unassigned' when no "
        "owner is clear. If there are none, say exactly: No action items found. No preamble."
    ),
    "keypoints": (
        "Pull out the key points of this transcript as concise Markdown bullets, "
        "grouped under short headings. No preamble."
    ),
}


def _llm(kind: str, transcript: str, backend: str) -> str:
    prompt = f"{PROMPTS[kind]}\n\n<transcript>\n{transcript[:MAX_CHARS]}\n</transcript>"
    return _run_api(prompt) if backend == "api" else _run_cli(prompt)


# ------------------------------------------------------------------ local pass

def _sentences(transcript: str) -> list[str]:
    body = re.sub(r"^\s*\[?[\d:]+\]?\s*", "", transcript, flags=re.MULTILINE)
    parts = re.split(r"(?<=[.!?])\s+", body.replace("\n", " "))
    return [p.strip() for p in parts if len(p.strip()) > 12]


def _matching(sentences, patterns) -> list[str]:
    rx = re.compile("|".join(patterns), re.IGNORECASE)
    seen, out = set(), []
    for s in sentences:
        key = s.lower()[:70]
        if rx.search(s) and key not in seen:
            seen.add(key)
            out.append(s if len(s) < 240 else s[:237] + "…")
    return out


def _topics(transcript: str, limit=12) -> list[tuple[str, int]]:
    words = re.findall(r"[a-zA-Z][a-zA-Z'-]{3,}", transcript.lower())
    counts = Counter(w for w in words if w not in STOPWORDS)
    return counts.most_common(limit)


def _local(kind: str, transcript: str) -> str:
    sentences = _sentences(transcript)
    actions = _matching(sentences, ACTION_PATTERNS)
    decisions = _matching(sentences, DECISION_PATTERNS)
    questions = [s for s in sentences if s.rstrip().endswith("?")][:12]
    deadlines = _matching(sentences, DEADLINE_PATTERNS)

    note = ("\n\n---\n*Extracted by the built-in pass — these are quoted straight from "
            "the transcript, not written by a model. Sign in to the `claude` CLI or set "
            "ANTHROPIC_API_KEY for written summaries.*")

    if kind == "todos":
        if not actions:
            return "No action items found." + note
        return "\n".join(f"- [ ] {s}" for s in actions[:25]) + note

    out = []
    if kind in ("summary", "keypoints"):
        topics = _topics(transcript)
        out.append("## Most discussed")
        out.append(", ".join(f"**{w}** ({n})" for w, n in topics))
        out.append("")
        opening = sentences[:3]
        if opening:
            out.append("## Opening")
            out += [f"> {s}" for s in opening]
            out.append("")

    if kind == "meeting" or decisions:
        out.append("## Decisions")
        out += [f"- {s}" for s in decisions[:10]] or ["- *(none detected)*"]
        out.append("")
    out.append("## Action items")
    out += [f"- [ ] {s}" for s in actions[:20]] or ["- *(none detected)*"]
    out.append("")
    if deadlines:
        out.append("## Mentions of timing")
        out += [f"- {s}" for s in deadlines[:10]]
        out.append("")
    if questions:
        out.append("## Questions raised")
        out += [f"- {s}" for s in questions[:10]]
    return "\n".join(out).rstrip() + note


# ------------------------------------------------------------------ public

def analyse(kind: str, transcript: str, backend: str | None = None) -> dict:
    """Run one analysis. Returns {"kind", "backend", "text"}."""
    if kind not in PROMPTS:
        raise SummarizeError(f"Unknown analysis: {kind}")
    if not transcript.strip():
        raise SummarizeError("The transcript is empty.")
    backend = backend or available_backend()
    if backend in ("api", "cli"):
        try:
            return {"kind": kind, "backend": backend,
                    "text": _llm(kind, transcript, backend)}
        except Exception as exc:
            # never fail outright — fall back to the offline pass and say so
            return {"kind": kind, "backend": "local",
                    "text": _local(kind, transcript),
                    "warning": f"Claude was unavailable ({exc}); used the built-in pass."}
    return {"kind": kind, "backend": "local", "text": _local(kind, transcript)}
