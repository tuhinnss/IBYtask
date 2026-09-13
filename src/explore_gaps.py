"""Day 1: how long are the pauses between events, and a detour into a bug.

Two questions this answers:

1. What's a sane "the person stepped away" gap threshold, based on the
   real distribution of `correlation.ms_since_last_event` — not a guess?
2. Why is the *minimum* gap value negative in both datasets, in one case
   by over ten minutes? (Spoiler: it's not a bug in this script.)

Run from the repo root:
    python src/explore_gaps.py

Produces the numbers under "Gap distribution" and the whole
"screenshot_smart" detour in WORK_LOG.md (Day 1 cont.).
"""
import collections

from log_utils import iter_events

# --- Part 1: percentiles of the gap between consecutive events ---
for root in ["dataset_a", "dataset_b"]:
    gaps = []
    for ses, chunk, ev in iter_events(root):
        g = ev.get("correlation", {}).get("ms_since_last_event")
        if g is not None:
            gaps.append(g)
    gaps.sort()
    n = len(gaps)

    def pct(p):
        return gaps[int(n * p)]

    print(f"=== {root} === n={n}")
    print(f"min {gaps[0]}  median {gaps[n // 2]}  p75 {pct(.75)}  "
          f"p90 {pct(.9)}  p95 {pct(.95)}  p99 {pct(.99)}  max {gaps[-1]}")
    for th in [5000, 10000, 15000, 20000, 30000, 60000, 120000, 300000]:
        c = sum(1 for g in gaps if g > th)
        print(f"  gaps > {th:>6d}ms: {c:5d}  ({c / n * 100:.2f}%)")
    print()

# --- Part 2: the minimum gap is negative -- which event_type causes that? ---
print("=== negative-gap events (< -500ms), by event_type ===")
et_counter = collections.Counter()
for root in ["dataset_a", "dataset_b"]:
    for ses, chunk, ev in iter_events(root):
        g = ev.get("correlation", {}).get("ms_since_last_event")
        if g is not None and g < -500:
            et_counter[ev.get("event_type")] += 1
print(dict(et_counter))
print("(turns out: 100% screenshot_smart, both datasets, zero exceptions --")
print(" see WORK_LOG.md for the why)")
