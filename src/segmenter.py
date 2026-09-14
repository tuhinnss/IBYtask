"""Day 2: turn the Day 1 rule into actual code.

The idea (from notes/step1_first_approach.md): figure out what "signature"
of work is happening at each moment (a browser URL route, a Word document,
or just an app name if neither is available), collapse consecutive events
with the same signature into a run, then merge nearby runs into one
segment as long as they keep cycling within a small, recent set of
signatures. Cut a new segment on a long idle gap or a genuinely new
signature that isn't part of what's currently in play.

Usage:
    python src/segmenter.py dataset_a > outputs/segments_a.jsonl
    python src/segmenter.py dataset_b > outputs/segments_b.jsonl

Tunable constants are at the top -- see WORK_LOG.md Day 2 for why these
particular values, and evaluate_segments.py for how they were chosen.
"""
import sys
import re
import json
import glob
from datetime import datetime, timezone

# --- tunables (see WORK_LOG.md Day 2 for how these were picked) ---
IDLE_GAP_SECONDS = 20      # silence this long always starts a new segment
WINDOW_SECONDS = 30        # how far back a signature can be "recently active"
MAX_SIGNATURES = 3         # a segment can legitimately touch this many signatures
SHORT_GAP_SECONDS = 6      # allowed gap when picking up a brand new signature

BROWSER_APPS = {"google chrome", "microsoft edge"}
WORD_APPS = {"microsoft word"}
# Excel/PowerPoint are excluded here: dataset_a reuses ONE shared workbook/deck
# (m1_reference / Budget_Report) across many different processes, so the
# filename carries no signal for those two apps -- see WORK_LOG.md Day 2.
# NOTE_APPS is intentionally empty -- see normalize_note_title below. Tried
# using Notepad titles as an anchor (set() -> {"notepad"}), it made label
# purity WORSE (31.6%->29.9%), even after stripping case ids/parentheticals
# (->30.0%). The notes vary by real per-case content beyond just an id, so
# they fragment one process family into many labels instead of collapsing
# to one. Kept the normalizer in case a smarter version is worth trying
# later (e.g. clustering note texts instead of exact-matching them).
NOTE_APPS = set()
NOTE_BOILERPLATE = {"untitled", "launch_m1.ps1", "setup.md", "open", "notepad"}

_COMPAT_MODE_RE = re.compile(r"\s*(\[Compatibility Mode\]|-\s*Compatibility Mode|-\s*Protected View)")


def normalize_office_title(title, suffix):
    """'foo  -  Compatibility Mode - Word' / 'foo [Compatibility Mode] - Word' -> 'foo'."""
    if not title or title in (suffix, "Resume Reading"):
        return None
    base = _COMPAT_MODE_RE.split(title)[0].strip()
    base = re.sub(rf"\s*-\s*{suffix}$", "", base).strip()
    return base or None


_PARENS_RE = re.compile(r"\([^)]*\)")


def normalize_note_title(title):
    """'*追跡確認 SHIP-2026-3075 (近鉄ロジスティクス) - Notepad' -> '追跡確認'.

    These notes are per-CASE, not per-process-type -- the case id and
    company name change every execution (see WORK_LOG.md Day 2: this is
    the second attempt, the first one used the raw title and that made
    label purity *worse*, not better, because it fragmented one process
    into one label per case). So: drop parentheticals and any token that
    contains a digit, keep whatever generic phrase is left.
    """
    base = normalize_office_title(title, "Notepad")
    if not base:
        return None
    base = base.lstrip("*").strip()
    if base.lower() in NOTE_BOILERPLATE:
        return None
    base = _PARENS_RE.sub("", base)
    tokens = [t for t in base.split() if not any(ch.isdigit() for ch in t)]
    base = " ".join(tokens).strip(" -")
    return base or None


def url_route(url):
    """'http://host:port/#/resident-tax' -> '#/resident-tax'; '.../' -> '/'."""
    if not url:
        return None
    if "#" in url:
        return "#" + url.split("#", 1)[1]
    # no hash route -- fall back to the path so at least sso-mock.html etc differ
    path = url.split("://", 1)[-1]
    path = path.split("/", 1)[1] if "/" in path else ""
    return "/" + path if path else "/"


def load_session_events(session_dir):
    """All events for a session, across chunks, sorted by REAL timestamp.

    Sequence/array order is not safe to trust here -- screenshot_smart
    events land out of chronological order (see WORK_LOG.md Day 1).
    """
    events = []
    for chunk in sorted(glob.glob(f"{session_dir}/chunk_*")):
        fp = f"{chunk}/events.jsonl"
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        except FileNotFoundError:
            pass
    events.sort(key=lambda e: e["timestamp_ms"])
    return events


def signature_stream(events):
    """Yield (timestamp_ms, kind, signature) each time the "what's being
    worked on" signature changes. kind is 'web' / 'doc' / 'app', used to
    prioritize labels later (a URL route or doc name beats a bare app name).
    """
    current_app = None
    current_sig = None
    for ev in events:
        et = ev.get("event_type")
        ts = ev["timestamp_ms"]
        sig = None

        if et == "app_switch":
            new_app = ev.get("payload", {}).get("new_app", {}) or {}
            current_app = (new_app.get("app_name") or "").strip()
            app_lower = current_app.lower()
            if app_lower in WORD_APPS:
                doc = normalize_office_title(new_app.get("window_title"), "Word")
                sig = ("doc", doc) if doc else ("app", current_app)
            elif app_lower in NOTE_APPS:
                note = normalize_note_title(new_app.get("window_title"))
                sig = ("note", note) if note else ("app", current_app)
            elif app_lower in BROWSER_APPS:
                sig = ("app", current_app)  # refined below once a tab shows up
            else:
                sig = ("app", current_app)

        # a browser tab can be known on ANY event via context, not just app_switch
        tab = ev.get("context", {}).get("active_browser_tab")
        if tab and current_app and current_app.lower() in BROWSER_APPS:
            route = url_route(tab.get("url"))
            if route:
                sig = ("web", route)

        if sig is None:
            continue  # nothing informative on this event -- keep current signature
        if sig != current_sig:
            current_sig = sig
            yield ts, sig[0], sig[1]


def runs_from_stream(stream):
    """Collapse a signature stream into (kind, value, start_ms, end_ms) runs."""
    stream = list(stream)
    runs = []
    for i, (ts, kind, val) in enumerate(stream):
        end = stream[i + 1][0] if i + 1 < len(stream) else ts
        runs.append((kind, val, ts, end))
    return runs


def segment_session(events):
    """The actual Day 1 rule, operationalized over signature runs.

    Returns a list of dicts: {start_ms, end_ms, label}.
    """
    runs = runs_from_stream(signature_stream(events))
    if not runs:
        return []

    segments = []
    seg_start = runs[0][2]
    seg_end = runs[0][3]
    recent = {}          # signature -> last-touched ms, within this segment
    label_votes = {}      # (kind, val) -> total ms spent, for picking a label later
    distinct = set()

    def record(kind, val, start, end):
        sig = (kind, val)
        recent[sig] = end
        label_votes[sig] = label_votes.get(sig, 0) + max(end - start, 0)
        distinct.add(sig)

    def flush(end_ms):
        if not label_votes:
            return
        # Pick a label by signature KIND first, not by raw dwell time: a doc
        # name is a specific procedure ("shinkui_keiyaku_tetsuzuki"), a web
        # route can be a generic, reused module (dataset_b reuses dataset_a's
        # exact "#/payroll-items" route across unrelated departments -- see
        # WORK_LOG.md Day 2). So doc/note anchors always win over a route,
        # and only fall back to the bare app name when nothing else fired.
        for kind in ("doc", "note", "web", "app"):
            pool = {s: v for s, v in label_votes.items() if s[0] == kind}
            if pool:
                label = max(pool.items(), key=lambda kv: kv[1])[0][1]
                segments.append({"start_ms": seg_start, "end_ms": end_ms, "label": label})
                return

    record(*runs[0][:2], runs[0][2], runs[0][3])

    for kind, val, start, end in runs[1:]:
        sig = (kind, val)
        gap_s = (start - seg_end) / 1000.0

        same_as_active = any(
            (start - last) / 1000.0 <= WINDOW_SECONDS for s, last in recent.items() if s == sig
        )
        room_for_new = len(distinct) < MAX_SIGNATURES and gap_s <= SHORT_GAP_SECONDS

        if gap_s > IDLE_GAP_SECONDS:
            flush(seg_end)
            seg_start = start
            recent, label_votes, distinct = {}, {}, set()
        elif not (same_as_active or sig in distinct or room_for_new):
            flush(seg_end)
            seg_start = start
            recent, label_votes, distinct = {}, {}, set()

        record(kind, val, start, end)
        seg_end = end

    flush(seg_end)
    return segments


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # labels can be Japanese (Notepad note titles)
    if len(sys.argv) != 2 or sys.argv[1] not in ("dataset_a", "dataset_b"):
        print("usage: python src/segmenter.py <dataset_a|dataset_b>", file=sys.stderr)
        sys.exit(1)
    root = sys.argv[1]

    for session_dir in sorted(glob.glob(f"{root}/ses_*")):
        session_id = session_dir.split("/")[-1].replace("\\", "/").split("/")[-1]
        events = load_session_events(session_dir)
        for seg in segment_session(events):
            print(json.dumps({
                "session_id": session_id,
                "start": ms_to_iso(seg["start_ms"]),
                "end": ms_to_iso(seg["end_ms"]),
                "label": seg["label"],
            }, ensure_ascii=False))


if __name__ == "__main__":
    main()
