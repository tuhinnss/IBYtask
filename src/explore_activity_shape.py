"""Day 1, Session 2, Step 8: does the TIMING of event types within an
execution (not just their totals, already covered in Step 1) carry a
per-family fingerprint?

For each event type, compute its "centroid" within an execution: the
mean normalized position of its events in [0, 1], where 0 = the very
start of the execution and 1 = the very end. E.g. a centroid of 0.8 for
keystroke means keystrokes cluster near the end (data entry right before
submitting); 0.2 would mean they cluster near the start.

Run from the repo root:
    python src/explore_activity_shape.py

Writes outputs/activity_shape.jsonl (gitignored).
"""
import sys
import json
import glob
import statistics as stats
import collections
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

EVENT_TYPES = [
    "keystroke", "mouse_click", "mouse_scroll", "clipboard_change",
    "shortcut", "app_switch",
]


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
                st_ms, en_ms = parse_ts(ex["start_ts"]), parse_ts(ex["end_ts"])
                dur = en_ms - st_ms
                if dur <= 0:
                    continue
                window = [e for e in events if st_ms <= e["timestamp_ms"] <= en_ms]

                positions = collections.defaultdict(list)
                for e in window:
                    et = e.get("event_type")
                    if et in EVENT_TYPES:
                        positions[et].append((e["timestamp_ms"] - st_ms) / dur)

                centroids = {
                    et: (stats.mean(positions[et]) if positions.get(et) else None)
                    for et in EVENT_TYPES
                }
                rows.append({"family_name": fam, **{f"centroid_{et}": centroids[et] for et in EVENT_TYPES}})

    with open("outputs/activity_shape.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"total executions: {len(rows)}\n")

    print("=== overall centroid per event type (all families pooled) ===")
    overall = {}
    for et in EVENT_TYPES:
        vals = [r[f"centroid_{et}"] for r in rows if r[f"centroid_{et}"] is not None]
        overall[et] = stats.mean(vals)
        print(f"  {et:18s} mean centroid = {overall[et]:.2f}  (n={len(vals)})")

    print("\n=== per-family centroid for each event type (mean, CV) ===")
    by_fam = collections.defaultdict(list)
    for r in rows:
        by_fam[r["family_name"]].append(r)

    fam_profile = {}
    for fam, execs in sorted(by_fam.items(), key=lambda kv: -len(kv[1])):
        print(f"{fam}  (n={len(execs)})")
        profile = {}
        for et in EVENT_TYPES:
            vals = [e[f"centroid_{et}"] for e in execs if e[f"centroid_{et}"] is not None]
            if len(vals) < 5:
                print(f"    {et:18s} too few samples (n={len(vals)})")
                continue
            mean = stats.mean(vals)
            cv = stats.pstdev(vals) / mean if mean else float("nan")
            profile[et] = mean
            dev = mean - overall[et]
            print(f"    {et:18s} mean={mean:.2f}  CV={cv:.2f}  "
                  f"(vs overall {overall[et]:.2f}, {dev:+.2f})")
        fam_profile[fam] = profile
        print()

    print("=== which families deviate MOST from the overall centroid, per event type ===")
    for et in EVENT_TYPES:
        devs = [(fam, p[et] - overall[et]) for fam, p in fam_profile.items() if et in p]
        devs.sort(key=lambda x: -abs(x[1]))
        top = devs[:3]
        print(f"  {et:18s} " + "  ".join(f"{fam}({d:+.2f})" for fam, d in top))


if __name__ == "__main__":
    main()
