"""Day 1: how big are the two datasets, and what's actually in them?

Just a raw count of sessions/events per dataset, broken down by `layer`
and `event_type`. This is the very first thing worth knowing before
building any segmentation logic on top of it.

Run from the repo root:
    python src/explore_event_stats.py

Produces the numbers quoted in WORK_LOG.md under "Basic shape of the two
datasets" (Day 1 cont.) — including the app_switch-rate difference
between dataset_a (~31% of all events) and dataset_b (~8%).
"""
import collections

from log_utils import iter_events

for root in ["dataset_a", "dataset_b"]:
    sessions = set()
    event_types = collections.Counter()
    layers = collections.Counter()
    n = 0

    for ses, chunk, ev in iter_events(root):
        sessions.add(ses)
        event_types[ev.get("event_type")] += 1
        layers[ev.get("layer")] += 1
        n += 1

    print(f"=== {root} ===")
    print(f"sessions: {len(sessions)}   events: {n}")
    print("layers:", dict(layers))
    print("event types:")
    for et, c in event_types.most_common(20):
        print(f"  {et:25s} {c:7d}  ({c / n * 100:.1f}%)")
    print()
