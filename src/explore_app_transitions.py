"""Day 1, Session 2, Step 3: does the SPECIFIC app transition (not just
"a switch happened") carry a boundary signal?

For every app_switch event in dataset_a, record its (previous_app ->
new_app) pair and whether it falls within a small tolerance of a
ground-truth boundary (start_ts) or not. Compare the transition-pair
distribution at boundaries vs away from them -- are some transitions
much more boundary-associated than their overall frequency would predict?

Run from the repo root:
    python src/explore_app_transitions.py

Writes outputs/app_transitions.jsonl (gitignored) with one row per
app_switch event.
"""
import sys
import json
import glob
import collections
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

TOLERANCE_MS = 5_000  # how close to a gt start_ts counts as "at a boundary"


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


def nearest_boundary_dist(ts_ms, boundaries_sorted):
    """boundaries_sorted: sorted list of ms. Simple linear-ish scan is fine
    here (a handful of boundaries per session)."""
    best = None
    for b in boundaries_sorted:
        d = abs(ts_ms - b)
        if best is None or d < best:
            best = d
    return best


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

        boundaries = []
        for proc in gtm.get("processes", []):
            for ex in proc.get("executions", []):
                if ex.get("start_ts"):
                    boundaries.append(parse_ts(ex["start_ts"]))
        boundaries.sort()
        if not boundaries:
            continue

        for ev in events:
            if ev.get("event_type") != "app_switch":
                continue
            payload = ev.get("payload", {})
            prev = (payload.get("previous_app") or {}).get("app_name")
            new = (payload.get("new_app") or {}).get("app_name")
            if not prev or not new:
                continue
            dist = nearest_boundary_dist(ev["timestamp_ms"], boundaries)
            rows.append({
                "prev_app": prev,
                "new_app": new,
                "is_at_boundary": dist is not None and dist <= TOLERANCE_MS,
                "nearest_boundary_ms": dist,
            })

    with open("outputs/app_transitions.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total = len(rows)
    at_boundary = sum(1 for r in rows if r["is_at_boundary"])
    print(f"total app_switch transitions: {total}")
    print(f"at a boundary (within {TOLERANCE_MS/1000:.0f}s): {at_boundary} "
          f"({at_boundary/total*100:.1f}%)\n")

    # transition -> (count at boundary, count total)
    pair_boundary = collections.Counter()
    pair_total = collections.Counter()
    for r in rows:
        pair = (r["prev_app"], r["new_app"])
        pair_total[pair] += 1
        if r["is_at_boundary"]:
            pair_boundary[pair] += 1

    baseline_rate = at_boundary / total  # if transition type didn't matter, every
    # pair's boundary-rate should hover near this

    print(f"baseline: if transition type didn't matter, every pair's own\n"
          f"'% at boundary' should be close to the overall rate: {baseline_rate*100:.1f}%\n")

    print("=== transition pairs with >=20 occurrences, ranked by how much their\n"
          "    boundary-rate DEVIATES from the baseline (most over-represented first) ===")
    scored = []
    for pair, tot in pair_total.items():
        if tot < 20:
            continue
        rate = pair_boundary[pair] / tot
        scored.append((pair, tot, rate, rate - baseline_rate))
    scored.sort(key=lambda x: -x[3])

    print("\n-- most boundary-associated --")
    for pair, tot, rate, dev in scored[:10]:
        print(f"  {pair[0]:22s} -> {pair[1]:22s}  n={tot:4d}  "
              f"at-boundary={rate*100:5.1f}%  (+{dev*100:.1f}pp vs baseline)")

    print("\n-- least boundary-associated (most likely mid-task) --")
    for pair, tot, rate, dev in scored[-10:]:
        print(f"  {pair[0]:22s} -> {pair[1]:22s}  n={tot:4d}  "
              f"at-boundary={rate*100:5.1f}%  ({dev*100:.1f}pp vs baseline)")

    print(f"\ntotal distinct transition pairs (n>=20): {len(scored)}  "
          f"(n<20, excluded: {len(pair_total) - len(scored)})")


if __name__ == "__main__":
    main()
