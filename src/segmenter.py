"""Segments and labels the operation logs -- every rule here is one sentence,
deliberately, so it can be explained end to end rather than defended.

Two jobs, kept separate because the EDA showed they need different signals:

  WHERE does a task start?   App-switching SPIKES (Step 2: ~26 switches in a
                             +/-10s window at a real boundary vs 2 mid-task).
                             Measured relative to each session's own normal
                             rate, so it transfers between departments.

  WHAT was the task?         Whichever document was open during the segment.
                             87% of segments have one (measured) -- no need
                             to guess for those. The rest are honestly
                             labelled "other" rather than forced into a
                             guessed group.

No trained model, no clustering. Every step below is one sentence.

Run from the repo root:
    python src/segmenter.py                 # evaluate on dataset_a
    python src/segmenter.py dataset_b out   # write segments.jsonl
"""
import os
import re
import sys
import json
import glob
import bisect
import collections
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

# --- constants, each one justified by a finding in WORK_LOG.md -------------
DENSITY_WINDOW_MS = 5_000  # how far either side to count switching activity
SPIKE_PERCENTILE = 0.60    # keep the busiest 40% of moments in each session
SUPPRESS_MS = 10_000       # one boundary per 10s window, strongest spike wins
MIN_BURST = 3              # sessions with fewer switches than this are skipped
MATCH_TOL_MS = 5_000       # scoring: a boundary counts as found within 5s
MIN_SEGMENT_MS = 5_000     # ignore slivers
DOC_DOMINANT_SHARE = 0.40  # a document open in more of the run than this is
                           # a shared file, not a real per-process anchor

OFFICE_APPS = ("Microsoft Word", "Microsoft Excel", "Microsoft PowerPoint")
TRANSIENT = {"word", "excel", "powerpoint", "notepad", "untitled", "opening",
             "opening -", "resume reading", "find and replace", "open",
             "save as", "print"}


# --------------------------------------------------------------- loading

def load_events(session_dir):
    """Every event in a session, oldest first.

    Sorted by timestamp, not by file order: screenshot events get written
    out of order (Day 1 finding), so file order is not time order.
    """
    events = []
    for chunk in sorted(glob.glob(os.path.join(session_dir, "chunk_*"))):
        try:
            with open(os.path.join(chunk, "events.jsonl"), encoding="utf-8") as f:
                events.extend(json.loads(l) for l in f if l.strip())
        except FileNotFoundError:
            pass
    events.sort(key=lambda e: e["timestamp_ms"])
    return events


def app_switches(events):
    """[(timestamp, app_switched_to)] for every app switch."""
    out = []
    for e in events:
        if e.get("event_type") != "app_switch":
            continue
        new = ((e.get("payload") or {}).get("new_app") or {}).get("app_name")
        if new:
            out.append((e["timestamp_ms"], new))
    return out


# ------------------------------------------------------- WHERE: boundaries

def count_near(sorted_ts, centre, half):
    lo = bisect.bisect_left(sorted_ts, centre - half)
    return bisect.bisect_right(sorted_ts, centre + half) - lo


def find_boundaries(switches):
    """A task starts where switching activity is locally among the busiest
    moments IN THIS SESSION -- ranked, not compared to a fixed multiplier.

    A fixed "3.5x the session average" threshold does not transfer between
    departments: dataset_a's switching is naturally very bursty (the median
    moment is already ~5x the average), so a fixed multiplier barely filters
    anything there and picks up almost nothing on dataset_b, which is
    flatter. Ranking each session's own moments and keeping the busiest
    PERCENTILE sidesteps that -- it only asks "is this locally busy for
    this session", never "does it clear an absolute or averaged bar".

    SPIKE_PERCENTILE is the one number tuned against dataset_a's ground
    truth; everything else here is just bookkeeping.
    """
    ts = sorted(t for t, _ in switches)
    if len(ts) < MIN_BURST:
        return []

    density = [count_near(ts, t, DENSITY_WINDOW_MS) for t in ts]
    cutoff = sorted(density)[int(len(density) * SPIKE_PERCENTILE)]

    chosen = []
    order = sorted(range(len(ts)), key=lambda i: -density[i])
    for i in order:
        if density[i] < cutoff:
            break
        if all(abs(ts[i] - c) >= SUPPRESS_MS for c in chosen):
            chosen.append(ts[i])
    return sorted(chosen)


def to_segments(boundaries, first_ts, last_ts):
    edges = sorted({first_ts, last_ts} | {b for b in boundaries
                                          if first_ts < b < last_ts})
    return [{"start": a, "end": z} for a, z in zip(edges, edges[1:])
            if z - a >= MIN_SEGMENT_MS]


# ----------------------------------------------------------- WHAT: labels

def document_name(title):
    """'shinkui_keiyaku_tetsuzuki  -  Compatibility Mode - Word' -> the name."""
    if not title:
        return None
    t = re.split(r"\s*(\[Compatibility Mode\]|-\s*Compatibility Mode"
                 r"|-\s*Protected View)", title)[0]
    t = re.sub(r"\s*-\s*(Word|Excel|PowerPoint|Notepad)$", "", t)
    t = re.sub(r"\s*-\s*AutoRecovered$", "", t).strip().lstrip("*").strip()
    return t if t and t.lower() not in TRANSIENT else None


def find_document(events, seg):
    """Which document (if any) was open the most during this segment."""
    docs = collections.Counter()
    for e in events:
        if not (seg["start"] <= e["timestamp_ms"] <= seg["end"]):
            continue
        if e.get("event_type") != "app_switch":
            continue
        na = (e.get("payload") or {}).get("new_app") or {}
        if na.get("app_name") in OFFICE_APPS:
            name = document_name(na.get("window_title"))
            if name:
                docs[name] += 1
    return docs.most_common(1)[0][0] if docs else None


def choose_labels(segments):
    """Label each segment by the document that was open -- or "other" if
    none was, rather than guessing.

    87% of segments have their own document open (measured) -- no need to
    compare segments to each other or guess a group for those. Tried
    clustering the rest by on-screen text to avoid an "other" bucket; it
    didn't make the output more correct, just more confident-looking, so
    it's gone. Honestly saying "other" is a feature: it marks exactly
    which segments Step 2 shouldn't lean on too heavily.

    One safeguard kept: a document only counts as a real anchor if it
    isn't a generic file shared by the whole run. Measured: dataset_a's
    one shared workbook ("m1_reference") is open in 80% of all anchored
    segments -- trusting it would label almost everything the same thing.
    dataset_b's real procedure names each sit at 12-19%. So: trust a
    document only if it's under DOC_DOMINANT_SHARE of the run.
    """
    doc_counts = collections.Counter(s["doc"] for s in segments if s["doc"])
    doc_total = sum(doc_counts.values()) or 1
    trusted = {d for d, c in doc_counts.items() if c / doc_total <= DOC_DOMINANT_SHARE}

    for s in segments:
        if s["doc"] and s["doc"] in trusted:
            s["label"] = s["doc"]
            s["method"] = "document_anchor"
        else:
            s["label"] = "other"
            s["method"] = "none"
    return segments


# ------------------------------------------------------------- evaluation

def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000


def truth_for(session_dir):
    """[(timestamp, process_name)] of every real task start."""
    path = os.path.join(session_dir, "gt_manifest.json")
    if not os.path.exists(path):
        return []
    out = []
    for proc in json.load(open(path, encoding="utf-8")).get("processes", []):
        for ex in proc.get("executions", []):
            if ex.get("start_ts") and ex.get("end_ts"):
                out.append((parse_ts(ex["start_ts"]), parse_ts(ex["end_ts"]),
                            proc.get("family_name")))
    return sorted(out)


def score(all_pred, all_truth):
    tp = fp = 0
    n_true = 0
    for pred, truth in zip(all_pred, all_truth):
        n_true += len(truth)
        used = set()
        for b, _, _ in truth:
            hit, dist = None, None
            for i, p in enumerate(pred):
                if i in used:
                    continue
                d = abs(p - b)
                if d <= MATCH_TOL_MS and (dist is None or d < dist):
                    hit, dist = i, d
            if hit is not None:
                used.add(hit)
                tp += 1
        fp += len(pred) - len(used)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / n_true if n_true else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1, sum(len(p) for p in all_pred), n_true


def purity(pairs):
    by_label = collections.defaultdict(collections.Counter)
    by_truth = collections.defaultdict(collections.Counter)
    for label, truth in pairs:
        by_label[label][truth] += 1
        by_truth[truth][label] += 1
    p = (sum(c.most_common(1)[0][1] for c in by_label.values())
         / max(sum(sum(c.values()) for c in by_label.values()), 1))
    ip = (sum(c.most_common(1)[0][1] for c in by_truth.values())
          / max(sum(sum(c.values()) for c in by_truth.values()), 1))
    return p, ip, len(by_label)


def iso(ms):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# -------------------------------------------------------------------- main

def run(dataset):
    all_pred, all_truth, segments = [], [], []
    for d in sorted(glob.glob(f"{dataset}/ses_*")):
        events = load_events(d)
        if not events:
            continue
        switches = app_switches(events)
        bounds = find_boundaries(switches)
        all_pred.append(bounds)
        all_truth.append(truth_for(d))
        for seg in to_segments(bounds, events[0]["timestamp_ms"],
                               events[-1]["timestamp_ms"]):
            doc = find_document(events, seg)
            seg.update({"session": os.path.basename(d), "doc": doc})
            segments.append(seg)
    return all_pred, all_truth, choose_labels(segments)


def main():
    dataset = sys.argv[1] if len(sys.argv) > 1 else "dataset_a"
    write = len(sys.argv) > 2
    all_pred, all_truth, segments = run(dataset)

    durs = sorted((s["end"] - s["start"]) / 1000 for s in segments)
    print(f"{dataset}: {len(segments)} segments, "
          f"median duration {durs[len(durs)//2]:.0f}s")

    if any(all_truth):
        prec, rec, f1, n_pred, n_true = score(all_pred, all_truth)
        print(f"\nboundaries:  precision={prec*100:.1f}%  recall={rec*100:.1f}%  "
              f"F1={f1*100:.1f}%   predicted={n_pred} vs {n_true} real "
              f"({n_pred/n_true:.2f}x)")
        # label quality: match each segment to the task it overlaps most
        pairs = []
        truth_by_sess = {os.path.basename(d): truth_for(d)
                         for d in sorted(glob.glob(f"{dataset}/ses_*"))}
        for s in segments:
            best, ov = None, 0
            for a, z, fam in truth_by_sess.get(s["session"], []):
                o = max(0, min(z, s["end"]) - max(a, s["start"]))
                if o > ov:
                    best, ov = fam, o
            if best:
                pairs.append((s["label"], best))
        p, ip, nlab = purity(pairs)
        print(f"labels:      purity={p*100:.1f}%  inverse purity={ip*100:.1f}%  "
              f"({nlab} labels for 15 real processes)")

    if write:
        # segments.jsonl keeps exactly the 4 fields the brief asks for.
        # "method" (document_anchor vs none) isn't part of that file, but
        # every segment still carries it in memory here for Step 2 to
        # reuse when it wants to weight confident labels over guesses.
        with open("segments.jsonl", "w", encoding="utf-8") as f:
            for s in segments:
                f.write(json.dumps({
                    "session_id": s["session"],
                    "start": iso(s["start"]),
                    "end": iso(s["end"]),
                    "label": s["label"],
                }, ensure_ascii=False) + "\n")
        counts = collections.Counter(s["label"] for s in segments)
        n_anchored = sum(1 for s in segments if s["method"] == "document_anchor")
        print(f"\nwrote segments.jsonl ({len(segments)} segments, "
              f"{len(counts)} labels, {n_anchored}/{len(segments)} "
              f"from a real document, rest 'other')")
        for label, c in counts.most_common():
            print(f"  {c:4d}  {label}")


if __name__ == "__main__":
    main()
