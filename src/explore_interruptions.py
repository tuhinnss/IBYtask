"""Day 1, Session 2, Step 5: how common are interruption/resumption
pairs, how long is the "away" period, and -- like quiet restarts in
Step 4 -- does the RESUME point show a detectable app-switch boundary
signal, or is it also a blind spot for the telemetry-based approach?

Pairs process_suspended <-> process_resumed events in gt.jsonl via
split_id, computes the away-duration, and reuses the Step 2/4 boundary-
neighborhood measurement at each resume point.

Run from the repo root:
    python src/explore_interruptions.py

Writes outputs/interruptions.jsonl (gitignored).
"""
import sys
import json
import glob
import statistics as stats
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

WINDOW_MS = 10_000
CLOSE_TOLERANCE_MS = 3_000


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
    lo, hi = center_ms - WINDOW_MS, center_ms + WINDOW_MS
    window = [e for e in events if lo <= e["timestamp_ms"] <= hi]
    app_switches = [e for e in window if e.get("event_type") == "app_switch"]
    nearest = min((abs(e["timestamp_ms"] - center_ms) for e in app_switches), default=None)
    return {
        "app_switch_count": len(app_switches),
        "has_app_switch_within_tolerance": nearest is not None and nearest <= CLOSE_TOLERANCE_MS,
        "nearest_app_switch_ms": nearest,
    }


def main():
    rows = []

    for gt_path in sorted(glob.glob("dataset_a/ses_*/gt.jsonl")):
        session_dir = gt_path.rsplit("/gt.jsonl", 1)[0].rsplit("\\gt.jsonl", 1)[0]
        events = load_session_events(session_dir)
        if not events:
            continue

        suspends = {}   # split_id -> (ts_ms, from_code, to_code)
        for line in open(gt_path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("event") == "process_suspended":
                sid = ev.get("split_id")
                if sid:
                    suspends[sid] = (parse_ts(ev["ts_utc"]), ev.get("from"), ev.get("to"))

        for line in open(gt_path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("event") != "process_resumed":
                continue
            sid = ev.get("split_id")
            if sid not in suspends:
                continue
            sus_ts, from_code, to_code = suspends[sid]
            res_ts = parse_ts(ev["ts_utc"])
            away_s = (res_ts - sus_ts) / 1000.0

            stat = neighborhood_stats(events, res_ts)
            stat.update({
                "session_id": session_dir.split("/")[-1].split("\\")[-1],
                "split_id": sid,
                "process_code": ev.get("process_code"),
                "process_name": ev.get("process_name"),
                "interrupted_by": to_code,
                "phase": ev.get("phase"),
                "away_seconds": away_s,
            })
            rows.append(stat)

    with open("outputs/interruptions.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"interruption/resumption pairs found: {len(rows)}\n")

    away = sorted(r["away_seconds"] for r in rows)
    n = len(away)
    print("=== away-duration (suspend -> resume), seconds ===")
    print(f"  median={away[n//2]:.1f}  p25={away[int(n*.25)]:.1f}  "
          f"p75={away[int(n*.75)]:.1f}  min={away[0]:.1f}  max={away[-1]:.1f}")

    short = [r for r in rows if r["away_seconds"] <= 60]
    long_ = [r for r in rows if r["away_seconds"] > 60]
    print(f"\n  <=60s away (quick check-in): {len(short)}/{n} ({len(short)/n*100:.0f}%)")
    print(f"  >60s away (real context switch): {len(long_)}/{n} ({len(long_)/n*100:.0f}%)")

    print(f"\n=== does the RESUME point show a boundary signal? (vs Step 2/4 baselines) ===")
    hit = sum(1 for r in rows if r["has_app_switch_within_tolerance"])
    print(f"  app_switch within {CLOSE_TOLERANCE_MS/1000:.0f}s of resume: {hit}/{n} ({hit/n*100:.1f}%)")
    print(f"  (Step 2 normal boundaries: 64.3%   Step 4 quiet restarts: 9.1%)")
    asc = [r["app_switch_count"] for r in rows]
    print(f"  app_switch_count in window: median={stats.median(asc):.1f}  mean={stats.mean(asc):.1f}")
    print(f"  (Step 2 normal boundaries: median 26   Step 2 control/non-boundary: median 2)")

    print(f"\n=== who interrupts whom (interrupted_by = the 'to' process code) ===")
    from collections import Counter
    to_counts = Counter(r["interrupted_by"] for r in rows)
    for code, c in to_counts.most_common(10):
        print(f"  {code}: {c}")

    print(f"\n=== short (<=60s) vs long (>60s) interruptions: boundary signal at resume ===")
    for label, group in [("short", short), ("long", long_)]:
        h = sum(1 for r in group if r["has_app_switch_within_tolerance"])
        print(f"  {label:5s} (n={len(group):3d}): app_switch within tolerance = "
              f"{h}/{len(group)} ({h/len(group)*100:.1f}%)")


if __name__ == "__main__":
    main()
