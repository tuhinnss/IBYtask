"""Day 1, Session 2, Step 4: are "quiet" same-process restarts (the 230
cases from Session 1 where a process restarts for a new case with NO
process_switched_out/process_suspended marker in gt.jsonl) also harder to
detect in the raw telemetry -- or do they show the same boundary
app-switch pattern Steps 2-3 found for boundaries in general?

Joins gt.jsonl (to tag each process_started event as "restart, no
marker" or "normal") to gt_manifest.json (for start_ts) via case_id, then
reuses Step 2's boundary-neighborhood measurement split by that tag.

Run from the repo root:
    python src/explore_restart_boundaries.py

Writes outputs/restart_boundaries.jsonl (gitignored).
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


def restart_flags_from_gt(gt_path):
    """case_id -> True if this process_started had no switch/suspend marker
    separating it from the previous process_started of the SAME code."""
    flags = {}
    last_started_code = None
    for line in open(gt_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        et = ev.get("event")
        if et == "process_started":
            code = ev.get("process_code")
            case_id = ev.get("case_id")
            if case_id:
                flags[case_id] = (last_started_code == code)
            last_started_code = code
        elif et in ("process_switched_out", "process_suspended"):
            last_started_code = None
    return flags


def neighborhood_stats(events, center_ms):
    lo, hi = center_ms - WINDOW_MS, center_ms + WINDOW_MS
    window = [e for e in events if lo <= e["timestamp_ms"] <= hi]
    app_switches = [e for e in window if e.get("event_type") == "app_switch"]
    nearest = min((abs(e["timestamp_ms"] - center_ms) for e in app_switches), default=None)
    return {
        "event_count": len(window),
        "app_switch_count": len(app_switches),
        "has_app_switch_within_tolerance": nearest is not None and nearest <= CLOSE_TOLERANCE_MS,
        "nearest_app_switch_ms": nearest,
    }


def main():
    rows = []

    for gtm_path in sorted(glob.glob("dataset_a/ses_*/gt_manifest.json")):
        session_dir = gtm_path.rsplit("/gt_manifest.json", 1)[0].rsplit(
            "\\gt_manifest.json", 1
        )[0]
        gt_path = f"{session_dir}/gt.jsonl"
        try:
            restart_flags = restart_flags_from_gt(gt_path)
        except FileNotFoundError:
            continue

        events = load_session_events(session_dir)
        if not events:
            continue

        with open(gtm_path, encoding="utf-8") as f:
            gtm = json.load(f)

        for proc in gtm.get("processes", []):
            fam = proc.get("family_name")
            for ex in proc.get("executions", []):
                case_id = ex.get("case_id")
                if not ex.get("start_ts") or case_id not in restart_flags:
                    continue
                st_ms = parse_ts(ex["start_ts"])
                stat = neighborhood_stats(events, st_ms)
                stat.update({
                    "family_name": fam,
                    "case_id": case_id,
                    "is_quiet_restart": restart_flags[case_id],
                })
                rows.append(stat)

    with open("outputs/restart_boundaries.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    quiet = [r for r in rows if r["is_quiet_restart"]]
    normal = [r for r in rows if not r["is_quiet_restart"]]
    print(f"total boundaries matched: {len(rows)}")
    print(f"quiet restarts (no switch/suspend marker): {len(quiet)}")
    print(f"normal boundaries (marker present, or genuinely new process): {len(normal)}\n")

    def summarize(group, field):
        vals = [r[field] for r in group if r[field] is not None]
        return vals

    print("=== event_count in +/-10s window ===")
    print(f"  quiet restart: median={stats.median(summarize(quiet,'event_count')):.1f}")
    print(f"  normal:        median={stats.median(summarize(normal,'event_count')):.1f}")

    print("\n=== app_switch_count in +/-10s window ===")
    qv, nv = summarize(quiet, "app_switch_count"), summarize(normal, "app_switch_count")
    print(f"  quiet restart: median={stats.median(qv):.1f}  mean={stats.mean(qv):.1f}")
    print(f"  normal:        median={stats.median(nv):.1f}  mean={stats.mean(nv):.1f}")

    print(f"\n=== has an app_switch within {CLOSE_TOLERANCE_MS/1000:.0f}s? ===")
    qh = sum(1 for r in quiet if r["has_app_switch_within_tolerance"])
    nh = sum(1 for r in normal if r["has_app_switch_within_tolerance"])
    print(f"  quiet restart: {qh}/{len(quiet)} ({qh/len(quiet)*100:.1f}%)")
    print(f"  normal:        {nh}/{len(normal)} ({nh/len(normal)*100:.1f}%)")

    print("\n=== nearest app_switch distance (ms), when one exists ===")
    qv = summarize(quiet, "nearest_app_switch_ms")
    nv = summarize(normal, "nearest_app_switch_ms")
    print(f"  quiet restart: median={stats.median(qv):.0f}ms (n={len(qv)})")
    print(f"  normal:        median={stats.median(nv):.0f}ms (n={len(nv)})")


if __name__ == "__main__":
    main()
