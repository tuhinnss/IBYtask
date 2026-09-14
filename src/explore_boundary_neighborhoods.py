"""Day 1, Session 2, Step 2: is there actually a measurable signal at
process boundaries, or was the Day 1 "app-switch burst on a boundary"
observation just true for the 3 examples that got hand-traced?

For every ground-truth execution's start_ts (a real boundary) in
dataset_a, look at the raw events in a window around it: how many
events, how many app_switch events, how close is the nearest one.
Compare against a CONTROL group -- the same measurement taken at each
execution's midpoint (guaranteed to be mid-task, not a boundary). If
boundaries don't look different from the control, "burst = boundary"
isn't a real signal.

Run from the repo root:
    python src/explore_boundary_neighborhoods.py

Writes outputs/boundary_neighborhoods.jsonl (gitignored) with one row per
(boundary, control) pair for reuse in a later step.
"""
import sys
import json
import glob
import collections
import statistics as stats
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

WINDOW_MS = 10_000       # +/- 10s neighborhood around each point of interest
CLOSE_TOLERANCE_MS = 3_000  # "is an app_switch basically right on the boundary?"


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000


def load_session_events(session_dir):
    events = []
    for chunk in sorted(glob.glob(f"{session_dir}/chunk_*")):
        try:
            with open(f"{chunk}/events.jsonl", encoding="utf-8") as f:
                events.extend(json.loads(line) for line in f if line.strip())
        except FileNotFoundError:
            pass
    events.sort(key=lambda e: e["timestamp_ms"])
    return events


def neighborhood_stats(events, center_ms):
    """events must be sorted by timestamp_ms."""
    lo, hi = center_ms - WINDOW_MS, center_ms + WINDOW_MS
    window = [e for e in events if lo <= e["timestamp_ms"] <= hi]
    app_switches = [e for e in window if e.get("event_type") == "app_switch"]

    nearest_switch_dist = None
    if app_switches:
        nearest_switch_dist = min(abs(e["timestamp_ms"] - center_ms) for e in app_switches)

    # gap immediately spanning the center point (last event before vs first at/after)
    before = [e for e in events if e["timestamp_ms"] < center_ms]
    after = [e for e in events if e["timestamp_ms"] >= center_ms]
    spanning_gap_ms = None
    if before and after:
        spanning_gap_ms = after[0]["timestamp_ms"] - before[-1]["timestamp_ms"]

    return {
        "event_count": len(window),
        "app_switch_count": len(app_switches),
        "has_app_switch_within_tolerance": (
            nearest_switch_dist is not None and nearest_switch_dist <= CLOSE_TOLERANCE_MS
        ),
        "nearest_app_switch_ms": nearest_switch_dist,
        "spanning_gap_ms": spanning_gap_ms,
    }


def main():
    rows = []

    for gtm_path in sorted(glob.glob("dataset_a/ses_*/gt_manifest.json")):
        session_dir = gtm_path.rsplit("/gt_manifest.json", 1)[0].rsplit(
            "\\gt_manifest.json", 1
        )[0]
        events = load_session_events(session_dir)
        if not events:
            continue

        with open(gtm_path, encoding="utf-8") as f:
            gtm = json.load(f)

        for proc in gtm.get("processes", []):
            fam = proc.get("family_name")
            for ex in proc.get("executions", []):
                if not ex.get("start_ts") or not ex.get("end_ts"):
                    continue
                st_ms = parse_ts(ex["start_ts"])
                en_ms = parse_ts(ex["end_ts"])
                mid_ms = (st_ms + en_ms) / 2

                b = neighborhood_stats(events, st_ms)
                c = neighborhood_stats(events, mid_ms)
                rows.append({
                    "session_id": session_dir.split("/")[-1].split("\\")[-1],
                    "family_name": fam,
                    "case_id": ex.get("case_id"),
                    "boundary": b,
                    "control": c,
                })

    with open("outputs/boundary_neighborhoods.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"boundaries analyzed: {len(rows)}  (window = +/-{WINDOW_MS/1000:.0f}s, "
          f"close tolerance = {CLOSE_TOLERANCE_MS/1000:.0f}s)\n")

    def summarize(key, field):
        vals = [r[key][field] for r in rows if r[key][field] is not None]
        return vals

    print("=== event_count in window: boundary vs control ===")
    bv, cv = summarize("boundary", "event_count"), summarize("control", "event_count")
    print(f"  boundary: median={stats.median(bv):.1f}  mean={stats.mean(bv):.1f}")
    print(f"  control:  median={stats.median(cv):.1f}  mean={stats.mean(cv):.1f}")

    print("\n=== app_switch_count in window: boundary vs control ===")
    bv, cv = summarize("boundary", "app_switch_count"), summarize("control", "app_switch_count")
    print(f"  boundary: median={stats.median(bv):.1f}  mean={stats.mean(bv):.1f}")
    print(f"  control:  median={stats.median(cv):.1f}  mean={stats.mean(cv):.1f}")
    zero_b = sum(1 for r in rows if r["boundary"]["app_switch_count"] == 0)
    zero_c = sum(1 for r in rows if r["control"]["app_switch_count"] == 0)
    print(f"  boundary windows with ZERO app_switch events: {zero_b}/{len(rows)} "
          f"({zero_b/len(rows)*100:.1f}%)")
    print(f"  control windows with ZERO app_switch events:  {zero_c}/{len(rows)} "
          f"({zero_c/len(rows)*100:.1f}%)")

    print(f"\n=== is there an app_switch within {CLOSE_TOLERANCE_MS/1000:.0f}s of the point? ===")
    hit_b = sum(1 for r in rows if r["boundary"]["has_app_switch_within_tolerance"])
    hit_c = sum(1 for r in rows if r["control"]["has_app_switch_within_tolerance"])
    print(f"  boundary: {hit_b}/{len(rows)} ({hit_b/len(rows)*100:.1f}%)")
    print(f"  control:  {hit_c}/{len(rows)} ({hit_c/len(rows)*100:.1f}%)")

    print("\n=== nearest app_switch distance (ms), when one exists in the window ===")
    bv = summarize("boundary", "nearest_app_switch_ms")
    cv = summarize("control", "nearest_app_switch_ms")
    print(f"  boundary: median={stats.median(bv):.0f}ms  (n={len(bv)})")
    print(f"  control:  median={stats.median(cv):.0f}ms  (n={len(cv)})")

    print("\n=== spanning gap (ms) -- the gap that CONTAINS the point ===")
    bv = summarize("boundary", "spanning_gap_ms")
    cv = summarize("control", "spanning_gap_ms")
    print(f"  boundary: median={stats.median(bv):.0f}ms  p90={sorted(bv)[int(len(bv)*.9)]:.0f}ms")
    print(f"  control:  median={stats.median(cv):.0f}ms  p90={sorted(cv)[int(len(cv)*.9)]:.0f}ms")

    print("\n=== per-family: % of boundaries with an app_switch within tolerance ===")
    by_fam = collections.defaultdict(list)
    for r in rows:
        by_fam[r["family_name"]].append(r["boundary"]["has_app_switch_within_tolerance"])
    for fam, hits in sorted(by_fam.items(), key=lambda kv: stats.mean(kv[1])):
        print(f"  {fam:14s} {sum(hits)}/{len(hits)} ({stats.mean(hits)*100:.0f}%)")


if __name__ == "__main__":
    main()
