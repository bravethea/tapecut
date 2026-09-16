/* Tapecut browser UI.
 *
 * Preview strategy: the <video> element plays the ORIGINAL file; a
 * requestAnimationFrame loop skips over cut regions live, so previewing an
 * edit is instant — no server round-trip. Export recomputes the same kept
 * segments server-side (same merging semantics as core/audio_editor.py).
 */

const $ = (id) => document.getElementById(id);

const PAUSE_MIN_GAP_DEFAULT = 1.0;  // gaps ≥ this show a trim chip (user-adjustable)
const PAUSE_KEEP = 0.25;     // seconds kept on each side of a trimmed pause

const state = {
  path: null,
  source: null,       // original location (gdrive:… or local path)
  isVideo: false,
  words: [],          // {word, start, end, deleted, filler?}
  spans: [],          // DOM span per word
  pauseGap: PAUSE_MIN_GAP_DEFAULT,  // current chip threshold in seconds
  pauseCuts: new Set(),  // indices i: gap after word i is trimmed
  pauseChips: {},     // i -> chip DOM element
  undoStack: [],      // snapshots of {w: [{d, t}], p: [pauseCuts]}
  playingIdx: -1,
  fillerIdxs: [],
  drag: null,         // {startIdx, restore, snapshot, moved}
  saveTimer: null,
  editingIdx: null,   // word currently being text-edited (right-click)
  mode: null,         // 'edit' | 'text' | 'notes'
  speakerNames: {},   // SPEAKER_00 -> "Teodora"
  analyses: {},       // kind -> markdown, saved with the transcript
  lastAnalysis: null,
};

const media = $("media");

// Vocalized fillers, matched as a pattern so elongated spellings are caught
// too: uh/uhh/uhhh, um/umm, uhm, ah/ahh/ahm, er/erm, eh, hm/hmm, mm/mhm.
const FILLER_RE = /^(u+[hm]+|a+h+m*|e+r+m*|e+h+|h+m+|m+h+m*|mm+)$/;

// Word/phrase fillers (matched exactly, after punctuation is stripped)
const FILLERS = new Set([
  "like", "you know", "basically", "literally",
  "actually", "so", "right", "okay", "well", "i mean",
  "sort of", "kind of", "i guess", "or whatever",
]);

const isFillerWord = (t) => FILLER_RE.test(t) || FILLERS.has(t);

/* ---------------------------------------------------------------- helpers */

const norm = (t) => t.replace(/[^\w\s]/g, "").trim().toLowerCase();

function fmtTime(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mm = String(m).padStart(h ? 2 : 1, "0"), ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

// Port of core/audio_editor.compute_kept_segments: contiguous kept words merge
// into one range, so natural pauses are preserved — then explicitly trimmed
// pauses are subtracted (mirror of pause_cut_ranges + subtract_ranges).
function keptSegments() {
  const segs = [];
  let run = null;
  for (let i = 0; i < state.words.length; i++) {
    const w = state.words[i];
    if (w.deleted) continue;
    if (run && !state.words[i - 1]?.deleted && run.lastIdx === i - 1) {
      run.end = w.end;
      run.lastIdx = i;
    } else {
      if (run) segs.push([run.start, run.end]);
      run = { start: w.start, end: w.end, lastIdx: i };
    }
  }
  if (run) segs.push([run.start, run.end]);

  const cuts = [...state.pauseCuts].sort((a, b) => a - b)
    .map((i) => [state.words[i].end + PAUSE_KEEP, state.words[i + 1].start - PAUSE_KEEP])
    .filter(([s, e]) => e > s);
  if (!cuts.length) return segs;

  const result = [];
  for (const [ss, se] of segs) {
    let pieces = [[ss, se]];
    for (const [cs, ce] of cuts) {
      const next = [];
      for (const [s, e] of pieces) {
        if (ce <= s || cs >= e) { next.push([s, e]); continue; }
        if (cs > s) next.push([s, cs]);
        if (ce < e) next.push([ce, e]);
      }
      pieces = next;
    }
    result.push(...pieces);
  }
  return result.filter(([s, e]) => e > s);
}

async function api(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

/* One status surface. setStatus() still writes where it always did, but every
   long job also reports into the app-bar chip, which survives scrolling. */
let jobTimer = null;
function setJob(text, kind = "run") {
  const chip = $("job-chip");
  clearTimeout(jobTimer);
  if (!text) { chip.classList.add("hidden"); return; }
  chip.className = "job-chip" + (kind === "run" ? "" : " " + kind);
  chip.innerHTML = kind === "run" ? '<span class="spin"></span>' : "";
  chip.append(document.createTextNode(text));
  chip.title = text;
  if (kind !== "run") jobTimer = setTimeout(() => chip.classList.add("hidden"), 12000);
}

function pollJob(jobId, onTick) {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const res = await fetch(`/api/job/${jobId}`);
        const data = await res.json();
        if (data.status === "done") return resolve(data);
        if (data.status === "error") return reject(new Error(data.error));
        onTick?.(data);
        setTimeout(tick, 1000);
      } catch (e) { reject(e); }
    };
    tick();
  });
}

/* ---------------------------------------------------------------- shell */

document.querySelectorAll(".rail-tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".rail-tab").forEach((t) => t.classList.toggle("is-on", t === tab));
    ({ drive: "drive-panel", library: "library-panel", local: "open-panel" });
    const map = { drive: "drive-panel", library: "library-panel", local: "open-panel" };
    Object.entries(map).forEach(([k, id]) => $(id).classList.toggle("hidden", k !== tab.dataset.src));
    $("rail-search").placeholder =
      tab.dataset.src === "library" ? "Filter transcripts…" : "Filter by name…";
    applyRailFilter();
  };
});

$("rail-search").oninput = () => applyRailFilter();

/** Filter whichever source list is showing. */
function applyRailFilter() {
  const q = $("rail-search").value.trim().toLowerCase();
  [["#drive-files", ".file-name"], ["#library-list", ".lib-name"]].forEach(([listSel, nameSel]) => {
    const list = document.querySelector(listSel);
    if (!list) return;
    let shown = 0;
    list.querySelectorAll(".file-row, .lib-row").forEach((row) => {
      const hit = !q || (row.querySelector(nameSel)?.textContent || "").toLowerCase().includes(q);
      row.classList.toggle("hidden", !hit);
      if (hit) shown++;
    });
    const note = list.querySelector(".filter-none");
    if (note) note.remove();
    if (q && !shown && list.children.length) {
      const el = document.createElement("div");
      el.className = "rail-empty filter-none";
      el.textContent = `Nothing matching “${$("rail-search").value.trim()}”.`;
      list.appendChild(el);
    }
  });
}

/* theme: system by default, toggled explicitly and remembered */
const THEME_KEY = "tapecut-theme";
function applyTheme(t) {
  if (t) document.documentElement.setAttribute("data-theme", t);
  else document.documentElement.removeAttribute("data-theme");
  $("btn-theme").title = t ? `Theme: ${t} (click to cycle)` : "Theme: system (click to cycle)";
}
$("btn-theme").onclick = () => {
  const order = [null, "light", "dark"];
  const now = localStorage.getItem(THEME_KEY) || null;
  const next = order[(order.indexOf(now) + 1) % order.length];
  next ? localStorage.setItem(THEME_KEY, next) : localStorage.removeItem(THEME_KEY);
  applyTheme(next);
};
try { applyTheme(localStorage.getItem(THEME_KEY)); } catch { applyTheme(null); }

/* help sheet */
const toggleHelp = (on) => $("help-sheet").classList.toggle("hidden", !on);
$("btn-help").onclick = () => toggleHelp(true);
$("help-close").onclick = () => toggleHelp(false);
$("help-sheet").onclick = (e) => { if (e.target === $("help-sheet")) toggleHelp(false); };

/* output tabs */
document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-on", t === tab));
    ["text-panel", "analysis-panel"].forEach((id) =>
      $(id).classList.toggle("hidden", id !== tab.dataset.panel));
  };
});

/* clean-up menu */
const closeMenus = () => document.querySelectorAll(".menu").forEach((m) => m.classList.add("hidden"));
$("btn-cleanup").onclick = (e) => {
  e.stopPropagation();
  const menu = $("cleanup-menu");
  const wasOpen = !menu.classList.contains("hidden");
  closeMenus();
  if (!wasOpen) menu.classList.remove("hidden");
};
document.addEventListener("click", (e) => {
  if (!e.target.closest(".menu-wrap")) closeMenus();
});

/* ---------------------------------------------------------------- modes */

const MODE_NOTE = {
  edit: "Editing a recording — cut words and pauses, then export the media.",
  text: "Transcribing — read the text, label speakers, export TXT/Markdown/subtitles.",
  notes: "Working on the transcript — meeting notes, action items, key points.",
};

document.querySelectorAll(".mode-card").forEach((card) => {
  card.onclick = () => setMode(card.dataset.mode);
});
$("btn-modes").onclick = () => {
  $("mode-picker").classList.remove("hidden");
  $("workspace").classList.add("hidden");
  $("btn-modes").classList.add("hidden");
  history.replaceState(null, "", "#");
};

/** The filler bar belongs to a review that a mode change would strand. */
function resetTransientUI() {
  closeMenus();
  $("filler-bar").classList.add("hidden");
}

function setMode(mode) {
  state.mode = mode;
  $("mode-picker").classList.add("hidden");
  $("workspace").classList.remove("hidden");
  $("btn-modes").classList.remove("hidden");
  $("mode-note").textContent = MODE_NOTE[mode] || "";
  history.replaceState(null, "", "#" + mode);
  applyMode();
}

/** Show only what this task needs; the transcript itself is common to all. */
function applyMode() {
  const editing = state.mode === "edit";
  const notes = state.mode === "notes";
  $("media-wrap").classList.toggle("hidden", !editing || state.mediaMissing);
  $("controls").classList.toggle("hidden", !editing);
  $("help").classList.toggle("hidden", !editing);
  $("cover-panel").classList.toggle("hidden", !editing);
  $("stage").classList.toggle("hidden", !editing);
  // open the panel this task is about; the other stays one click away
  const wanted = notes ? "analysis-panel" : "text-panel";
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("is-on", t.dataset.panel === wanted));
  ["text-panel", "analysis-panel"].forEach((id) =>
    $(id).classList.toggle("hidden", id !== wanted));
  if (state.words.length) refreshTextPreview();
}

/* ---------------------------------------------------------------- drive */

$("btn-drive-list").onclick = () => listDrive();
$("btn-drive-random").onclick = () => fetchDrive({ random: true });
$("drive-folder").addEventListener("keydown", (e) => { if (e.key === "Enter") listDrive(); });

async function initDrive() {
  try {
    const res = await fetch("/api/drive/status");
    const st = await res.json();
    $("drive-folder").value = st.folder;
    if (!st.configured) {
      $("drive-status").textContent = "not connected — run: rclone config create gdrive drive scope=drive.readonly";
      return;
    }
    $("drive-status").textContent = "connected (read-only)";
    listDrive();
  } catch {
    $("drive-status").textContent = "server unreachable";
  }
}

async function listDrive() {
  const folder = $("drive-folder").value.trim();
  $("drive-error").classList.add("hidden");
  $("drive-files").innerHTML = '<div class="muted" style="padding:8px 4px">Loading…</div>';
  $("drive-dirs").innerHTML = "";
  try {
    const res = await fetch(`/api/drive/list?folder=${encodeURIComponent(folder)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    await api("/api/drive/folder", { folder });   // remember as default

    $("drive-dirs").innerHTML = "";
    // parent-folder chip
    if (folder.includes("/")) {
      const up = document.createElement("span");
      up.className = "chip";
      up.textContent = "↑ up";
      up.onclick = () => { $("drive-folder").value = folder.replace(/\/[^/]+$/, ""); listDrive(); };
      $("drive-dirs").appendChild(up);
    }
    data.dirs.forEach((d) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = "📁 " + d;
      chip.onclick = () => { $("drive-folder").value = `${folder}/${d}`; listDrive(); };
      $("drive-dirs").appendChild(chip);
    });

    const box = $("drive-files");
    box.innerHTML = "";
    if (!data.files.length) {
      box.innerHTML = '<div class="muted" style="padding:8px 4px">No recordings in this folder.</div>';
      return;
    }
    data.files.forEach((f) => {
      const row = document.createElement("div");
      row.className = "file-row";
      row.title = f.cached ? "Open" : "Download from Drive and open";
      row.innerHTML = `
        <span class="file-name">${escapeHtml(f.name)}</span>
        <span class="row-actions">${f.cached ? "" : "↓"}</span>
        <span class="file-meta">
          ${f.transcribed ? '<span class="badge transcribed">transcript</span>' : ""}
          ${f.cached ? '<span class="badge cached">on this Mac</span>' : ""}
          ${(f.size / 1e6).toFixed(1)} MB · ${f.mtime}
        </span>`;
      row.onclick = () => fetchDrive({ name: f.name, size: f.size });
      box.appendChild(row);
    });
    applyRailFilter();
  } catch (e) {
    $("drive-files").innerHTML = "";
    $("drive-error").textContent = e.message;
    $("drive-error").classList.remove("hidden");
  }
}

async function fetchDrive(sel) {
  $("drive-error").classList.add("hidden");
  try {
    const req = { folder: $("drive-folder").value.trim(), ...sel };
    const { job, name } = await api("/api/drive/fetch", req);
    setStatus("drive-fetch-status", `Downloading ${name} from Drive…`);
    const info = await pollJob(job, (j) =>
      setStatus("drive-fetch-status", `Downloading ${name} from Drive… ${Math.round(j.elapsed)}s`));
    setStatus("drive-fetch-status", "");
    loadRecording(info);
    listDrive();          // refresh cache badges
  } catch (e) {
    setStatus("drive-fetch-status", "");
    $("drive-error").textContent = e.message;
    $("drive-error").classList.remove("hidden");
  }
}

/* ---------------------------------------------------------------- cover */

$("btn-cover-add").onclick = addCover;
$("cover-input").addEventListener("keydown", (e) => { if (e.key === "Enter") addCover(); });

async function refreshCover() {
  try {
    const data = await (await fetch("/api/cover")).json();
    $("cover-current").textContent = data.current
      ? `— ${data.current}`
      : "— none set (MP4 export of audio will fail)";
    const grid = $("cover-grid");
    grid.innerHTML = "";
    if (!data.options.length) {
      grid.innerHTML = '<div class="muted">No images yet — add one below.</div>';
      return;
    }
    data.options.forEach((o) => {
      const item = document.createElement("div");
      item.className = "cover-item" + (o.current ? " current" : "");
      item.title = o.current ? "current default cover" : "click to use as default";
      item.innerHTML = `<img src="/api/cover/image/${encodeURIComponent(o.name)}" alt="">
        <div class="cap">${o.current ? "✓ " : ""}${o.name} · ${o.size_kb} KB</div>`;
      item.onclick = () => setCover({ asset: o.name });
      if (!o.current) {
        const del = document.createElement("button");
        del.className = "del";
        del.textContent = "✕";
        del.title = "remove this image";
        del.onclick = async (ev) => {
          ev.stopPropagation();
          await fetch(`/api/cover/${encodeURIComponent(o.name)}`, { method: "DELETE" });
          refreshCover();
        };
        item.appendChild(del);
      }
      grid.appendChild(item);
    });
  } catch { /* server hiccup — leave stale grid */ }
}

async function setCover(body) {
  $("cover-error").classList.add("hidden");
  try {
    await api("/api/cover", body);
    refreshCover();
  } catch (e) {
    $("cover-error").textContent = e.message;
    $("cover-error").classList.remove("hidden");
  }
}

function addCover() {
  const v = $("cover-input").value.trim();
  if (!v) return;
  setCover(v.includes(":") && !v.startsWith("/") && !v.startsWith("~")
    ? { drive: v } : { path: v });
  $("cover-input").value = "";
}

/* ---------------------------------------------------------------- transcript text */

["text-format", "text-include-cut"].forEach((id) => {
  $(id).onchange = () => refreshTextPreview();
});

function textRequest() {
  return {
    format: $("text-format").value,
    words: state.words,
    title: state.path ? state.path.split("/").pop() : "Transcript",
    speaker_names: state.speakerNames,
    include_cut: $("text-include-cut").checked,
    suffix: " - transcript",
  };
}

let textTimer = null;
let textSeq = 0;          // only the newest request may paint the preview
function refreshTextPreview() {
  clearTimeout(textTimer);
  textTimer = setTimeout(async () => {
    if (!state.words.length) { $("text-preview").textContent = ""; return; }
    const seq = ++textSeq;
    $("text-preview").classList.add("loading");
    try {
      const data = await api("/api/text", textRequest());
      if (seq !== textSeq) return;   // a newer request has already been issued
      $("text-preview").textContent = data.text;
      $("text-preview").classList.remove("loading");
    } catch (e) {
      if (seq === textSeq) {
        $("text-preview").textContent = `Could not render: ${e.message}`;
        $("text-preview").classList.remove("loading");
      }
    }
  }, 120);
}

$("btn-text-copy").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("text-preview").textContent);
    setTextStatus("Copied to the clipboard.");
  } catch {
    setTextStatus("Could not copy — select the text and copy manually.");
  }
};

$("btn-text-save").onclick = async () => {
  try {
    const data = await api("/api/text/save", textRequest());
    setTextStatus(`Saved: ${data.output}`);
  } catch (e) {
    setTextStatus(`Save failed: ${e.message}`);
  }
};

function setTextStatus(msg) {
  $("text-status").textContent = msg;
  setTimeout(() => { $("text-status").textContent = ""; }, 8000);
}

/* ---------------------------------------------------------------- analysis */

const ANALYSES = { meeting: "Meeting notes", summary: "Summary",
                   todos: "Action items", keypoints: "Key points" };

Object.keys(ANALYSES).forEach((kind) => {
  $("btn-an-" + kind).onclick = () => runAnalysis(kind);
});

async function initAnalysisBackend() {
  try {
    const info = await (await fetch("/api/analyse/backend")).json();
    $("analysis-backend").textContent = info.label + (info.hint ? " — " + info.hint : "");
  } catch { /* panel still works; the job reports its own backend */ }
}

async function runAnalysis(kind) {
  if (!state.words.length) return;
  const btn = $("btn-an-" + kind);
  btn.disabled = true;
  setStatus("analysis-status", `Working on ${ANALYSES[kind].toLowerCase()}…`);
  try {
    const { job } = await api("/api/analyse", {
      kind, words: state.words, speaker_names: state.speakerNames,
    });
    const data = await pollJob(job, (j) =>
      setStatus("analysis-status", `Working on ${ANALYSES[kind].toLowerCase()}… ${Math.round(j.elapsed)}s`));
    state.analyses[kind] = data.text;
    state.lastAnalysis = { kind, text: data.text };
    $("analysis-out").innerHTML = renderMarkdown(data.text);
    setStatus("analysis-status",
      (data.warning ? data.warning + " " : "") + `${ANALYSES[kind]} — saved with this transcript.`);
    scheduleSave();
  } catch (e) {
    setStatus("analysis-status", `Failed: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
}

$("btn-an-copy").onclick = async () => {
  if (!state.lastAnalysis) return;
  try {
    await navigator.clipboard.writeText(state.lastAnalysis.text);
    setStatus("analysis-status", "Copied to the clipboard.");
  } catch {
    setStatus("analysis-status", "Could not copy — select the text and copy manually.");
  }
};

$("btn-an-save").onclick = async () => {
  if (!state.lastAnalysis) return;
  const name = (state.path ? state.path.split("/").pop() : "transcript");
  try {
    const data = await api("/api/text/save", {
      format: "md", words: [], title: name,
      suffix: " - " + state.lastAnalysis.kind,
      raw: state.lastAnalysis.text,
    });
    setStatus("analysis-status", `Saved: ${data.output}`);
  } catch (e) {
    setStatus("analysis-status", `Save failed: ${e.message}`);
  }
};

/** Minimal Markdown → HTML: headings, bullets, checkboxes, bold, code, quotes. */
function renderMarkdown(md) {
  const esc = (t) => t.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const inline = (t) => esc(t)
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/(^|\s)\*([^*]+)\*/g, "$1<i>$2</i>");
  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of md.split("\n")) {
    const line = raw.trimEnd();
    let m;
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
      closeList();
      const level = Math.min(3, m[1].length);
      out.push(`<h${level}>${inline(m[2])}</h${level}>`);
    } else if ((m = line.match(/^\s*[-*]\s+\[( |x|X)\]\s+(.*)$/))) {
      if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
      const done = m[1].toLowerCase() === "x";
      out.push(`<li class="todo">${done ? "☑" : "☐"} ${inline(m[2])}</li>`);
    } else if ((m = line.match(/^\s*[-*]\s+(.*)$/))) {
      if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
      out.push(`<li>${inline(m[1])}</li>`);
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
      out.push(`<li>${inline(m[1])}</li>`);
    } else if ((m = line.match(/^>\s?(.*)$/))) {
      closeList();
      out.push(`<blockquote>${inline(m[1])}</blockquote>`);
    } else if (!line.trim()) {
      closeList();
    } else {
      closeList();
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  return out.join("\n");
}

/* ---------------------------------------------------------------- library */

async function refreshLibrary() {
  try {
    const res = await fetch("/api/library");
    const data = await res.json();
    $("library-count").textContent = data.entries.length ? `(${data.entries.length})` : "";
    $("library-hint").textContent = `Stored locally in ${data.dir} (JSON + plain text). Tick two to compare.`;
    const box = $("library-list");
    box.innerHTML = "";
    data.entries.forEach((e) => {
      const row = document.createElement("div");
      row.className = "lib-row";
      row.title = "Open in the editor, with your saved edits";

      const name = document.createElement("span");
      name.className = "lib-name";
      name.textContent = e.media_name;
      row.appendChild(name);

      // one primary action; everything else lives behind the ⋯ menu
      const actions = document.createElement("span");
      actions.className = "row-actions";
      const more = document.createElement("div");
      more.className = "menu-wrap";
      const moreBtn = document.createElement("button");
      moreBtn.className = "ghost sm";
      moreBtn.textContent = "⋯";
      moreBtn.title = "More";
      const menu = document.createElement("div");
      menu.className = "menu right hidden";
      menu.onclick = (ev) => ev.stopPropagation();

      const view = document.createElement("button");
      view.className = "menu-item";
      view.innerHTML = "<span>Read the transcript</span>";
      view.onclick = () => { closeMenus(); showViewer([e.key]); };
      menu.appendChild(view);

      const cmp = document.createElement("button");
      cmp.className = "menu-item";
      cmp.innerHTML = "<span>Compare with…</span><span class=\"menu-note\">pick a second transcript</span>";
      cmp.onclick = () => { closeMenus(); startCompare(e.key); };
      menu.appendChild(cmp);

      menu.appendChild(Object.assign(document.createElement("div"), { className: "menu-sep" }));

      ["mp4", "mp3", "wav"].forEach((fmt) => {
        const b = document.createElement("button");
        b.className = "menu-item";
        b.innerHTML = `<span>Export ${fmt.toUpperCase()}</span>`;
        b.onclick = () => { closeMenus(); exportFromLibrary(e, fmt, moreBtn); };
        menu.appendChild(b);
      });

      moreBtn.onclick = (ev) => {
        ev.stopPropagation();
        const wasOpen = !menu.classList.contains("hidden");
        closeMenus();
        if (!wasOpen) menu.classList.remove("hidden");
      };
      more.append(moreBtn, menu);
      actions.appendChild(more);
      row.appendChild(actions);

      const meta = document.createElement("span");
      meta.className = "lib-meta";
      const badges = [];
      if (e.n_cut) badges.push(`<span class="badge edited">${e.n_cut} cut</span>`);
      if ((e.speakers || []).length) {
        badges.push(`<span class="badge speakers">${e.speakers.length} speakers</span>`);
      }
      meta.innerHTML = `${badges.join(" ")} ${fmtTime(e.duration_sec)} · ${e.n_words} words · ${e.saved_at.slice(0, 10)}`;
      row.appendChild(meta);

      row.onclick = () => editFromLibrary(e, moreBtn);
      box.appendChild(row);
    });
    applyRailFilter();
  } catch { /* server hiccup — leave stale list */ }
}

/** Compare: pick the first transcript, then the next click picks the second. */
let compareFirst = null;
function startCompare(key) {
  if (!compareFirst) {
    compareFirst = key;
    $("library-hint").textContent = "Now choose a second transcript from ⋯ → Compare with…";
    return;
  }
  const pair = [compareFirst, key];
  compareFirst = null;
  $("library-hint").textContent = "";
  showViewer(pair);
}

const escapeHtml = (t) => String(t).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function editFromLibrary(entry, btn) {
  const label = btn.textContent;
  const status = $("library-hint");
  const originalHint = status.textContent;
  btn.disabled = true;
  btn.textContent = "…";
  try {
    const { job } = await api(`/api/library/${entry.key}/open`, {});
    const info = await pollJob(job, (j) => {
      status.textContent = `Opening ${entry.media_name} — ${Math.round(j.elapsed)}s `
        + "(re-downloading from Drive if needed)…";
    });
    status.textContent = originalHint;
    loadRecording(info);            // saved cuts + trimmed pauses come with it
    setStatus("transcribe-status",
      `Reopened "${info.name}" with your saved edits — keep editing where you left off.`);
  } catch (e) {
    status.textContent = originalHint;
    $("editor").classList.remove("hidden");
    $("missing-bar").classList.remove("hidden");
    $("missing-msg").textContent = `Could not open "${entry.media_name}": ${e.message}`;
    $("missing-bar").scrollIntoView({ behavior: "smooth", block: "center" });
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

async function exportFromLibrary(entry, fmt, btn) {
  const label = btn.textContent;
  btn.disabled = true;
  const status = $("library-hint");
  const originalHint = status.textContent;
  try {
    btn.textContent = "…";
    const { job } = await api(`/api/library/${entry.key}/export`, { format: fmt });
    const data = await pollJob(job, (j) => {
      status.textContent = `Exporting ${entry.media_name} — ${Math.round(j.elapsed)}s `
        + "(re-downloading from Drive if needed, then encoding)…";
    });
    status.textContent = `✓ Exported: ${data.output}`;
  } catch (e) {
    status.textContent = `Export failed: ${e.message}`;
    setTimeout(() => { status.textContent = originalHint; }, 8000);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

async function showViewer(keys) {
  const cols = $("viewer-cols");
  cols.innerHTML = "";
  const entries = await Promise.all(keys.map(async (k) => (await fetch(`/api/library/${k}`)).json()));
  $("viewer-title").textContent = entries.length === 2 ? "Compare transcripts" : entries[0].media_name;
  entries.forEach((e) => {
    const col = document.createElement("div");
    col.className = "viewer-col";
    const words = e.words.map((w) =>
      w.deleted ? `<span class="cutw">${w.word}</span>` : w.word).join(" ");
    col.innerHTML = `<h3>${e.media_name}</h3>
      <div class="meta">${e.saved_at} · ${fmtTime(e.duration_sec)} · ${e.words.length} words (cut words struck through)</div>
      <div>${words}</div>`;
    cols.appendChild(col);
  });
  $("viewer").classList.remove("hidden");
}

$("viewer-close").onclick = () => $("viewer").classList.add("hidden");
$("viewer").addEventListener("click", (e) => {
  if (e.target === $("viewer")) $("viewer").classList.add("hidden");
});

/* ---------------------------------------------------------------- open */

$("btn-open").onclick = openFile;
$("path-input").addEventListener("keydown", (e) => { if (e.key === "Enter") openFile(); });

$("btn-browse").onclick = browseForFile;

async function browseForFile() {
  const btn = $("btn-browse");
  $("open-error").classList.add("hidden");
  btn.disabled = true;
  setStatus("browse-status", "Finder window open — pick a recording…");
  try {
    const { job } = await api("/api/browse", {});
    const info = await pollJob(job);
    if (info.cancelled) {
      setStatus("browse-status", "");
      return;
    }
    setStatus("browse-status", "");
    $("path-input").value = info.path;
    loadRecording(info);
  } catch (e) {
    setStatus("browse-status", "");
    $("open-error").textContent = e.message;
    $("open-error").classList.remove("hidden");
  } finally {
    btn.disabled = false;
  }
}

async function convertForPlayback(path) {
  setStatus("transcribe-status", "Converting this format so it can play in the browser…");
  try {
    const { job } = await api("/api/convert", { path });
    const data = await pollJob(job, (j) =>
      setStatus("transcribe-status",
        `Converting for playback… ${Math.round(j.elapsed)}s (one time — the original is untouched)`));
    media.src = `/media?path=${encodeURIComponent(data.play_path)}`;
    setStatus("transcribe-status", state.words.length
      ? `Loaded saved transcript (${state.words.length} words).`
      : "Converted — ready to transcribe.");
  } catch (e) {
    setStatus("transcribe-status", `Could not convert for playback: ${e.message}`);
  }
}

async function openFile() {
  const path = $("path-input").value.trim();
  $("open-error").classList.add("hidden");
  if (!path) return;
  try {
    loadRecording(await api("/api/open", { path }));
  } catch (e) {
    $("open-error").textContent = e.message;
    $("open-error").classList.remove("hidden");
  }
}

function loadRecording(info) {
  state.path = info.path;
  state.source = info.source || info.path;
  state.isVideo = info.is_video;
  state.mediaMissing = !!info.media_missing;
  state.speakerNames = info.speaker_names || {};
  state.analyses = info.analyses || {};
  state.lastAnalysis = null;
  $("analysis-out").innerHTML = "";
  $("btn-diarize").disabled = !info.diarization_available || !!info.media_missing;
  $("btn-diarize").title = info.diarization_available
    ? "identify who is speaking"
    : "needs a HuggingFace token (HF_TOKEN) — the pyannote models are gated";
  $("now-open").textContent = info.name || "";
  $("prompt-input").value = info.prompt || "";

  // the recording file is gone but its transcript is not: show the words so
  // they stay readable and correctable, and switch off anything needing audio
  $("missing-bar").classList.toggle("hidden", !state.mediaMissing);
  if (state.mediaMissing) {
    $("missing-msg").textContent =
      `The recording "${info.name}" could not be found, so playback and export are off. `
      + "Its transcript is below and still editable. Use 📂 Choose a file… to open the "
      + "recording again (renaming a file makes Tapecut see it as a new one).";
    media.removeAttribute("src");
    $("media-wrap").classList.add("hidden");
  } else {
    $("media-wrap").classList.remove("hidden");
  }
  ["btn-play", "btn-export", "btn-pauses"].forEach((id) => {
    $(id).disabled = state.mediaMissing;
  });
  // browsers cannot play .wma/.aiff/.avi/.mov/.mkv — those get a converted
  // copy for the preview player only (transcribe/export use the original)
  if (state.mediaMissing) {
    /* nothing to play */
  } else if (info.needs_conversion) {
    media.removeAttribute("src");
    convertForPlayback(info.path);
  } else {
    media.src = `/media?path=${encodeURIComponent(info.path)}`;
  }
  media.classList.toggle("audio-only", !info.is_video);
  $("media-label").textContent = info.is_video
    ? "Video — cuts you make below apply to the picture too"
    : (info.audio_in_video_container
        ? "Audio only (this .mp4 has no picture track) — MP4 export uses your cover image"
        : "Audio");
  $("transcribe-panel").classList.remove("hidden");
  document.title = `Tapecut — ${info.name}`;

  const fmt = $("export-format");
  fmt.innerHTML =
    '<option value="mp4">MP4 (YouTube)</option>'
    + '<option value="mp3">MP3 (audio only)</option>'
    + '<option value="wav">WAV (audio only)</option>';

  if (info.words) {
    loadWords(info.words, info.pause_cuts || []);
    // show whichever saved analysis exists, so notes survive a reload
    const saved = Object.keys(state.analyses)[0];
    if (saved) {
      state.lastAnalysis = { kind: saved, text: state.analyses[saved] };
      $("analysis-out").innerHTML = renderMarkdown(state.analyses[saved]);
    }
    setStatus("transcribe-status",
      `Loaded saved transcript (${info.words.length} words) — no need to re-transcribe.`);
  } else {
    $("editor").classList.add("hidden");
    setStatus("transcribe-status", info.model_cached
      ? "Ready to transcribe."
      : "Note: first transcription downloads the Whisper model (~3 GB).");
  }
  if (info.silent) {
    setStatus("transcribe-status",
      "⚠️ This recording appears to contain NO AUDIO (checked the first minute) — "
      + "there is nothing to hear or transcribe. The file is probably a failed recording.");
  }
  $("editor").scrollIntoView({ behavior: "smooth", block: "start" });
}

function setStatus(id, text) {
  const el = $(id);
  el.textContent = text;
  el.classList.toggle("hidden", !text);
}

/* ---------------------------------------------------------------- transcribe */

$("btn-transcribe").onclick = async () => {
  if (!state.path) return;
  const btn = $("btn-transcribe");
  btn.disabled = true;
  try {
    const mins = state.words.length ? "" : " — roughly 2½× the length of the recording";
    setJob("Transcribing…" + mins);
    const { job } = await api("/api/transcribe", {
      path: state.path,
      source: state.source,
      prompt: $("prompt-input").value,
      language: $("lang-select").value,
    });
    const data = await pollJob(job, (j) => {
      setStatus("transcribe-status", `Transcribing… ${Math.round(j.elapsed)}s`);
      setJob(`Transcribing… ${fmtTime(j.elapsed)}`);
    });
    loadWords(data.words);
    const marked = await autoMarkDisfluencies();
    setStatus("transcribe-status",
      `Done — ${data.words.length} words.`
      + (marked
          ? ` ${marked} repetitions/stutters crossed out for you — ⌥-click any to keep it, ⌘Z undoes all.`
          : " Click any word to cut it."));
    setJob(`Transcribed ${data.words.length} words`, "done");
    refreshLibrary();
    listDrive();
  } catch (e) {
    setJob("Transcription failed", "fail");
    setStatus("transcribe-status", `Transcription failed: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
};

/* ---------------------------------------------------------------- transcript */

function loadWords(words, pauseCuts = []) {
  cancelFillers();               // clear old filler state BEFORE spans are replaced
  state.editingIdx = null;       // any in-progress text edit dies with the old spans
  words.forEach((w) => { delete w.filler; });  // filler marks are session-only
  state.words = words;
  state.pauseCuts = new Set(pauseCuts.filter((i) => i >= 0 && i < words.length - 1));
  state.undoStack = [];
  state.playingIdx = -1;
  renderTranscript();
  $("editor").classList.remove("hidden");
  $("empty-state").classList.add("hidden");
  applyMode();
  refreshTextPreview();
}

/** (Re)build the transcript DOM from state.words at the current pause threshold. */
function renderTranscript() {
  const words = state.words;
  state.pauseChips = {};
  const box = $("transcript");
  box.innerHTML = "";
  let shownSpeaker = null;
  state.spans = words.map((w, i) => {
    // start a new labelled paragraph whenever the speaker changes
    if (w.speaker && w.speaker !== shownSpeaker) {
      shownSpeaker = w.speaker;
      const line = document.createElement("span");
      line.className = "speaker-line";
      const chip = document.createElement("span");
      chip.className = "spk " + speakerClass(w.speaker);
      chip.textContent = speakerLabel(w.speaker);
      chip.title = "click to rename this speaker";
      chip.onclick = (ev) => { ev.stopPropagation(); renameSpeaker(w.speaker); };
      line.appendChild(chip);
      const tc = document.createElement("span");
      tc.className = "tc";
      tc.textContent = fmtTime(w.start);
      line.appendChild(tc);
      box.appendChild(line);
    }
    const span = document.createElement("span");
    span.className = "w";
    span.dataset.i = i;
    span.textContent = w.word;
    box.appendChild(span);
    box.appendChild(document.createTextNode(" "));
    // a trimmable-pause chip after this word, when the gap is long enough
    const next = words[i + 1];
    const gap = next ? next.start - w.end : 0;
    if (next && gap >= state.pauseGap) {
      // a bar in the text rather than a chip, so sentences stay readable;
      // height encodes length and the duration is on hover
      const chip = document.createElement("span");
      chip.className = "pause" + (gap >= 6 ? " xl" : gap >= 2.5 ? " lg" : "");
      chip.dataset.p = i;
      chip.dataset.secs = `${gap.toFixed(1)}s`;
      chip.title = `${gap.toFixed(1)} s pause — click to trim it to about half a second`;
      box.appendChild(chip);
      state.pauseChips[i] = chip;
    }
    return span;
  });
  // drop trims whose pause is no longer shown, so no hidden edits linger
  [...state.pauseCuts].forEach((i) => {
    if (!(i in state.pauseChips)) state.pauseCuts.delete(i);
  });
  words.forEach((w, i) => paintWord(i));
  Object.keys(state.pauseChips).forEach((i) => paintPause(+i));
  updatePauseButton();
  updateStats();
  renderSpeakerBar();
}

/* ---------------------------------------------------------------- speakers */

const speakerLabel = (id) => state.speakerNames[id] || (id || "").replace("SPEAKER_", "Speaker ");

function speakerClass(id) {
  const order = speakerIds();
  const n = Math.max(0, order.indexOf(id));
  return "spk-" + (n % 6);
}

function speakerIds() {
  const seen = [];
  state.words.forEach((w) => {
    if (w.speaker && !seen.includes(w.speaker)) seen.push(w.speaker);
  });
  return seen;
}

function renameSpeaker(id) {
  const current = speakerLabel(id);
  const next = prompt(`Name for ${id}:`, current);
  if (next === null) return;
  const clean = next.trim();
  if (clean) state.speakerNames[id] = clean;
  else delete state.speakerNames[id];
  renderTranscript();
  renderSpeakerBar();
  scheduleSave();
  refreshTextPreview();
}

function renderSpeakerBar() {
  const ids = speakerIds();
  const bar = $("speaker-bar");
  bar.classList.toggle("hidden", !state.words.length);
  const box = $("speaker-chips");
  box.innerHTML = "";
  if (!ids.length) {
    box.innerHTML = '<span class="muted">none yet — identify them to label the transcript</span>';
    return;
  }
  ids.forEach((id) => {
    const chip = document.createElement("span");
    chip.className = "spk " + speakerClass(id);
    chip.textContent = speakerLabel(id);
    chip.title = "click to rename";
    chip.onclick = () => renameSpeaker(id);
    box.appendChild(chip);
  });
}

$("btn-diarize").onclick = async () => {
  if (!state.words.length || state.mediaMissing) return;
  const btn = $("btn-diarize");
  const count = $("speaker-count").value;
  btn.disabled = true;
  const label = btn.textContent;
  try {
    const { job } = await api("/api/diarize", {
      path: state.path, source: state.source, words: state.words,
      prompt: $("prompt-input").value, pause_cuts: [...state.pauseCuts],
      speaker_names: state.speakerNames, analyses: state.analyses,
      num_speakers: count || null,
    });
    setStatus("transcribe-status",
      "Identifying speakers — this runs at about the length of the recording…");
    setJob("Identifying speakers… — about as long as the recording");
    const data = await pollJob(job, (j) => {
      setStatus("transcribe-status", `Identifying speakers… ${Math.round(j.elapsed)}s`);
      setJob(`Identifying speakers… ${fmtTime(j.elapsed)}`);
    });
    data.words.forEach((w, i) => { if (state.words[i]) state.words[i].speaker = w.speaker; });
    renderTranscript();
    renderSpeakerBar();
    refreshTextPreview();
    setStatus("transcribe-status",
      `Found ${data.speakers.length} speaker(s) — click a name to rename it.`);
    setJob(`${data.speakers.length} speakers found`, "done");
  } catch (e) {
    setJob("Speaker identification failed", "fail");
    setStatus("transcribe-status", `Could not identify speakers: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
};

function paintPause(i) {
  state.pauseChips[i]?.classList.toggle("cut", state.pauseCuts.has(i));
}

function updatePauseButton() {
  const all = Object.keys(state.pauseChips).map(Number);
  const remaining = all.filter((i) => !state.pauseCuts.has(i));
  const btn = $("btn-pauses");
  const restoring = state.pauseCuts.size && !remaining.length;
  // say what the click will do and what it costs, before it happens
  const savings = remaining.reduce((acc, i) => {
    const gap = state.words[i + 1].start - state.words[i].end;
    return acc + Math.max(0, gap - 2 * PAUSE_KEEP);
  }, 0);
  btn.querySelector("span").textContent = restoring ? "Restore all pauses" : "Trim all pauses";
  $("pauses-note").textContent = restoring
    ? `${state.pauseCuts.size} trimmed — put them back`
    : remaining.length
      ? `${remaining.length} pauses · saves ${fmtTime(savings)}`
      : "no pauses at this length";
  btn.disabled = !all.length || state.mediaMissing;
  btn.dataset.mode = restoring ? "restore" : "trim";
}

function paintWord(i) {
  const w = state.words[i], s = state.spans[i];
  if (!w || !s) return;
  s.classList.toggle("cut", !!w.deleted);
  s.classList.toggle("filler", !!w.filler);
  s.classList.toggle("playing", i === state.playingIdx && !w.deleted);
}

function snapshot() {
  return {
    w: state.words.map((w) => ({ d: !!w.deleted, t: w.word })),
    p: [...state.pauseCuts],
  };
}

function pushUndo() {
  state.undoStack.push(snapshot());
  if (state.undoStack.length > 200) state.undoStack.shift();
}

function undo() {
  finishEdit(false);
  const snap = state.undoStack.pop();
  if (!snap) return;
  snap.w.forEach((s, i) => {
    state.words[i].deleted = s.d;
    if (state.words[i].word !== s.t) {
      state.words[i].word = s.t;
      state.spans[i].textContent = s.t;
    }
    paintWord(i);
  });
  state.pauseCuts = new Set(snap.p);
  Object.keys(state.pauseChips).forEach((i) => paintPause(+i));
  updatePauseButton();
  afterEdit();
}

function afterEdit() {
  updateStats();
  scheduleSave();
  refreshTextPreview();
}

function updateStats() {
  const words = state.words;
  if (!words.length) return;
  const total = words[words.length - 1].end - words[0].start;
  const kept = keptSegments().reduce((acc, [s, e]) => acc + (e - s), 0);
  const cut = words.filter((w) => w.deleted).length;
  const pauses = state.pauseCuts.size;
  const bits = [];
  if (cut) bits.push(`${cut} words cut`);
  if (pauses) bits.push(`${pauses} pauses trimmed`);
  $("stats").innerHTML =
    `<b>${fmtTime(kept)}</b> of ${fmtTime(total)}` +
    (bits.length ? ` · ${bits.join(" · ")}` : " · no cuts yet");
}

/* --- mouse interactions: click toggle, drag cut, alt = restore ----------- */

const transcriptBox = $("transcript");

transcriptBox.addEventListener("mousedown", (e) => {
  if (state.editingIdx != null) {
    // clicking inside the word being edited: let the text cursor work
    if (wordIdxFromEvent(e) === state.editingIdx) return;
    finishEdit(true);          // clicking elsewhere commits the edit…
    e.preventDefault();
    return;                    // …and swallows this click (no accidental cut)
  }
  const chip = e.target.closest?.(".pause");
  if (chip && e.button === 0) {
    e.preventDefault();
    pushUndo();
    const i = +chip.dataset.p;
    if (state.pauseCuts.has(i)) state.pauseCuts.delete(i);
    else state.pauseCuts.add(i);
    paintPause(i);
    updatePauseButton();
    afterEdit();
    return;
  }
  const i = wordIdxFromEvent(e);
  if (i < 0 || e.button !== 0) return;
  e.preventDefault();
  state.drag = { startIdx: i, restore: e.altKey, snapshot: snapshot(), moved: false };
});

transcriptBox.addEventListener("mousemove", (e) => {
  const d = state.drag;
  if (!d) return;
  const i = wordIdxFromEvent(e);
  if (i < 0 || i === d.startIdx && !d.moved) return;
  if (i !== d.startIdx) d.moved = true;
  if (!d.moved) return;
  const [lo, hi] = [Math.min(d.startIdx, i), Math.max(d.startIdx, i)];
  state.words.forEach((w, k) => {
    const target = (k >= lo && k <= hi) ? !d.restore : d.snapshot.w[k].d;
    if (!!w.deleted !== target) { w.deleted = target; paintWord(k); }
  });
});

window.addEventListener("mouseup", (e) => {
  const d = state.drag;
  if (!d) return;
  state.drag = null;
  state.undoStack.push(d.snapshot);
  if (d.moved) { afterEdit(); return; }
  // plain click: toggle (alt-click: force restore)
  const w = state.words[d.startIdx];
  w.deleted = d.restore ? false : !w.deleted;
  paintWord(d.startIdx);
  afterEdit();
});

transcriptBox.addEventListener("dblclick", (e) => {
  if (state.editingIdx != null) return;
  const chip = e.target.closest?.(".pause");
  if (chip) {
    media.currentTime = state.words[+chip.dataset.p].end + 0.001;
    media.play();
    return;
  }
  const i = wordIdxFromEvent(e);
  if (i < 0) return;
  media.currentTime = state.words[i].start + 0.001;
  media.play();
});

function wordIdxFromEvent(e) {
  const t = e.target.closest?.(".w");
  return t ? +t.dataset.i : -1;
}

/* --- text correction: right-click a word to fix it ----------------------- */

transcriptBox.addEventListener("contextmenu", (e) => {
  const i = wordIdxFromEvent(e);
  if (i < 0) return;
  if (i === state.editingIdx) return;  // native menu while already editing
  e.preventDefault();
  startEdit(i);
});

function startEdit(i) {
  finishEdit(true);
  const span = state.spans[i];
  state.editingIdx = i;
  try { span.contentEditable = "plaintext-only"; }
  catch { span.contentEditable = "true"; }       // Firefox fallback
  span.classList.add("editing");
  span.focus();
  const range = document.createRange();
  range.selectNodeContents(span);
  const sel = getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

function finishEdit(commit) {
  const i = state.editingIdx;
  if (i == null) return;
  const span = state.spans[i], w = state.words[i];
  state.editingIdx = null;
  span.contentEditable = "false";
  span.classList.remove("editing");
  span.blur();
  const text = span.textContent.replace(/\s+/g, " ").trim();
  if (!commit || !text || text === w.word) {
    span.textContent = w.word;                   // revert display
    return;
  }
  pushUndo();
  w.word = text;
  span.textContent = text;
  afterEdit();
}

transcriptBox.addEventListener("keydown", (e) => {
  if (state.editingIdx == null) return;
  if (e.key === "Enter") { e.preventDefault(); finishEdit(true); }
  else if (e.key === "Escape") { e.preventDefault(); finishEdit(false); }
});

transcriptBox.addEventListener("focusout", (e) => {
  if (state.editingIdx != null && e.target === state.spans[state.editingIdx]) {
    finishEdit(true);
  }
});

/* ---------------------------------------------------------------- playback */

$("btn-play").onclick = togglePlay;

function togglePlay() {
  if (media.paused) {
    if ($("skip-cuts").checked) {
      const segs = keptSegments();
      if (!segs.length) return;
      // if playhead is before the first kept moment, start there
      if (media.currentTime < segs[0][0] || media.currentTime >= segs[segs.length - 1][1]) {
        media.currentTime = segs[0][0] + 0.001;
      }
    }
    media.play();
  } else {
    media.pause();
  }
}

media.addEventListener("play", () => { $("btn-play").textContent = "⏸ Pause"; skipLoop(); });
media.addEventListener("pause", () => { $("btn-play").textContent = "▶ Play preview"; });

function skipLoop() {
  if (media.paused || media.ended) return;
  const t = media.currentTime;

  if ($("skip-cuts").checked && state.words.length) {
    const segs = keptSegments();
    if (!segs.length) { media.pause(); return; }
    // inside a cut? → jump to the start of the next kept segment
    let inKept = false, next = null;
    for (const [s, e] of segs) {
      if (t >= s && t < e) { inKept = true; break; }
      if (t < s) { next = s; break; }
    }
    if (!inKept) {
      if (next === null) { media.pause(); requestAnimationFrame(skipLoop); return; }
      media.currentTime = next + 0.001;
    }
  }

  highlightAt(media.currentTime);
  requestAnimationFrame(skipLoop);
}

media.addEventListener("timeupdate", () => { if (media.paused) highlightAt(media.currentTime); });

function highlightAt(t) {
  // binary search: last word whose start <= t
  const ws = state.words;
  let lo = 0, hi = ws.length - 1, best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (ws[mid].start <= t) { best = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  if (best >= 0 && t > ws[best].end + 0.35) best = -1; // in a pause
  if (best === state.playingIdx) return;
  const prev = state.playingIdx;
  state.playingIdx = best;
  if (prev >= 0) paintWord(prev);
  if (best >= 0) {
    paintWord(best);
    state.spans[best].scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

/* ---------------------------------------------------------------- fillers */

$("pause-gap").onchange = () => {
  const v = parseFloat($("pause-gap").value);
  if (!isFinite(v) || v <= 0) { $("pause-gap").value = state.pauseGap; return; }
  state.pauseGap = v;
  if (state.words.length) { renderTranscript(); scheduleSave(); }
};

/**
 * Cross out repeated words and stutters. The words stay visible and every one
 * can be restored with ⌥-click or ⌘Z — nothing is hidden or silently dropped.
 * Returns how many were marked.
 */
async function autoMarkDisfluencies() {
  if (!state.words.length) return 0;
  try {
    const res = await api("/api/disfluencies", { words: state.words });
    const idxs = [...(res.repetition || []), ...(res.stutter || [])]
      .filter((i) => !state.words[i].deleted);
    if (!idxs.length) return 0;
    pushUndo();
    idxs.forEach((i) => { state.words[i].deleted = true; paintWord(i); });
    afterEdit();
    return idxs.length;
  } catch {
    return 0;
  }
}

$("btn-disfluencies").addEventListener("click", closeMenus);
$("btn-disfluencies").onclick = async () => {
  const n = await autoMarkDisfluencies();
  setStatus("export-status", n
    ? `Crossed out ${n} repetitions/stutters — ⌥-click any to keep it.`
    : "No repeated words or stutters found.");
};

$("btn-pauses").addEventListener("click", closeMenus);
$("btn-pauses").onclick = () => {
  const all = Object.keys(state.pauseChips).map(Number);
  if (!all.length) return;
  pushUndo();
  if ($("btn-pauses").dataset.mode === "restore") {
    state.pauseCuts.clear();
  } else {
    all.forEach((i) => state.pauseCuts.add(i));
  }
  all.forEach(paintPause);
  updatePauseButton();
  afterEdit();
};

$("btn-fillers").addEventListener("click", closeMenus);
$("btn-fillers").onclick = () => {
  const idxs = [];
  const ws = state.words;
  for (let i = 0; i < ws.length; i++) {
    if (i + 1 < ws.length && FILLERS.has(norm(ws[i].word) + " " + norm(ws[i + 1].word))) {
      idxs.push(i, i + 1); i++; continue;
    }
    if (isFillerWord(norm(ws[i].word))) idxs.push(i);
  }
  if (!idxs.length) { setStatus("export-status", "No filler words found."); return; }
  state.fillerIdxs = idxs;
  idxs.forEach((i) => { ws[i].filler = true; paintWord(i); });
  $("filler-msg").textContent =
    `Found ${idxs.length} filler words (wavy underline). ⌥-click any you want to keep, then:`;
  $("filler-bar").classList.remove("hidden");
};

$("btn-filler-apply").onclick = () => {
  pushUndo();
  const toDelete = state.fillerIdxs.filter((i) => state.words[i].filler);
  toDelete.forEach((i) => { state.words[i].deleted = true; });
  cancelFillers();
  afterEdit();
  setStatus("export-status", `Deleted ${toDelete.length} filler words.`);
};

$("btn-filler-cancel").onclick = cancelFillers;

function cancelFillers() {
  state.fillerIdxs = [];
  state.words.forEach((w, i) => { if (w.filler) { delete w.filler; paintWord(i); } });
  $("filler-bar").classList.add("hidden");
}

/* ---------------------------------------------------------------- save/export */

function scheduleSave() {
  $("save-dot").className = "saving";
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(async () => {
    try {
      await api("/api/save", {
        path: state.path, source: state.source,
        words: state.words, pause_cuts: [...state.pauseCuts],
        prompt: $("prompt-input").value,
        speaker_names: state.speakerNames, analyses: state.analyses,
      });
      $("save-dot").className = "saved";
      setTimeout(() => { $("save-dot").className = ""; }, 1500);
      refreshLibrary();
    } catch {
      $("save-dot").className = "saving";
    }
  }, 800);
}

$("btn-undo").onclick = undo;

$("btn-export").onclick = async () => {
  const btn = $("btn-export");
  btn.disabled = true;
  try {
    const { job } = await api("/api/export", {
      path: state.path, source: state.source, words: state.words,
      pause_cuts: [...state.pauseCuts],
      format: $("export-format").value, prompt: $("prompt-input").value,
    });
    setJob("Exporting…");
    const data = await pollJob(job, (j) => {
      setStatus("export-status", `Exporting… ${Math.round(j.elapsed)}s`);
      setJob(`Exporting… ${fmtTime(j.elapsed)}`);
    });
    setStatus("export-status", `Exported: ${data.output}`);
    setJob("Export finished", "done");
  } catch (e) {
    setJob("Export failed", "fail");
    setStatus("export-status", `Export failed: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
};

/* ---------------------------------------------------------------- keyboard */

document.addEventListener("keydown", (e) => {
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)
    || document.activeElement?.isContentEditable;
  if (e.code === "Space" && !typing && state.words.length) {
    e.preventDefault();
    togglePlay();
  } else if ((e.metaKey || e.ctrlKey) && e.key === "z" && !typing) {
    e.preventDefault();
    undo();
  } else if ((e.metaKey || e.ctrlKey) && e.key === "/") {
    e.preventDefault();
    toggleHelp($("help-sheet").classList.contains("hidden"));
  } else if (e.key === "Escape") {
    toggleHelp(false);
    closeMenus();
    $("viewer").classList.add("hidden");
  }
});

/* ---------------------------------------------------------------- startup */

initDrive();
refreshLibrary();
refreshCover();
initAnalysisBackend();

// deep link: #edit / #text / #notes reopens that task directly
const startMode = location.hash.replace("#", "");
if (["edit", "text", "notes"].includes(startMode)) setMode(startMode);
