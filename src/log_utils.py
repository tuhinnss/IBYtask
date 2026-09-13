"""Tiny shared helper for the exploration scripts in this folder.

Not a real library — just the bit of glue every explore_*.py script needs:
walking session/chunk folders under a dataset root and yielding parsed
events. Kept in one place so the ~10 lines of glob/json boilerplate isn't
copy-pasted into every script.

All scripts here assume they're run from the repo root, e.g.:
    python src/explore_event_stats.py
"""
import json
import glob


def iter_chunks(root):
    """Yield (session_dir, chunk_dir, events) for every chunk under root.

    `events` is the full list of parsed JSON lines from that chunk's
    events.jsonl, in file order (== sequence_number order, which is NOT
    always the same as timestamp order — see explore_gaps.py). `root` is
    "dataset_a" or "dataset_b".
    """
    for ses in sorted(glob.glob(f"{root}/ses_*")):
        for chunk in sorted(glob.glob(f"{ses}/chunk_*")):
            fp = f"{chunk}/events.jsonl"
            try:
                with open(fp, encoding="utf-8") as f:
                    events = [json.loads(line) for line in f if line.strip()]
            except FileNotFoundError:
                continue
            yield ses, chunk, events


def iter_events(root):
    """Yield (session_dir, chunk_dir, event) for every event under root."""
    for ses, chunk, events in iter_chunks(root):
        for ev in events:
            yield ses, chunk, ev
