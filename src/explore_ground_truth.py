"""Day 1: aggregate the ground truth across all 63 dataset_a sessions.

Answers three things:
1. How many process families are there, how long does each run, and how
   many have more than one handling `variant`? (from gt_manifest.json,
   which is much easier to aggregate in bulk than the raw gt.jsonl)
2. Does the schema's warning -- "gt.jsonl sometimes emits the same
   process_started twice in a row" -- actually show up as literal
   back-to-back duplicate lines, or is it something subtler?

Run from the repo root:
    python src/explore_ground_truth.py

Produces the numbers under "Ground truth, aggregated across all 63
sessions" and the "duplicate process_started" section in WORK_LOG.md
(Day 1 cont.).
"""
import sys
import json
import glob
import collections
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")  # family names are in Japanese

# --- Part 1: families / domains / durations / variants, from gt_manifest.json ---
families = collections.Counter()
domains = collections.Counter()
variants = collections.defaultdict(set)
durations = collections.defaultdict(list)
total_exec = 0

for gtm_path in sorted(glob.glob("dataset_a/ses_*/gt_manifest.json")):
    with open(gtm_path, encoding="utf-8") as f:
        gtm = json.load(f)
    for proc in gtm.get("processes", []):
        fam = proc.get("family_name")
        dom = proc.get("domain")
        for ex in proc.get("executions", []):
            total_exec += 1
            families[fam] += 1
            domains[dom] += 1
            variants[fam].add(ex.get("variant"))
            try:
                st = datetime.fromisoformat(ex["start_ts"].replace("Z", "+00:00"))
                en = datetime.fromisoformat(ex["end_ts"].replace("Z", "+00:00"))
                durations[fam].append((en - st).total_seconds())
            except Exception:
                pass

print("total executions across all sessions:", total_exec)
print("domains:", dict(domains))
print("unique process families:", len(families))
for fam, c in families.most_common():
    ds = sorted(durations[fam])
    med = ds[len(ds) // 2] if ds else 0
    print(f"  {fam}: {c} executions, median {med:.0f}s, "
          f"min {min(ds):.0f}s, max {max(ds):.0f}s, variants={variants[fam]}")

# --- Part 2: chasing the "duplicate process_started" warning in DATA_SCHEMA.md ---
print("\n=== checking the 'duplicate process_started' warning against gt.jsonl ===")
exact_dup = 0
same_code_no_switch_between = 0
sample = None

for gt_path in sorted(glob.glob("dataset_a/ses_*/gt.jsonl")):
    lines = [json.loads(l) for l in open(gt_path, encoding="utf-8") if l.strip()]

    # literal adjacency: two process_started lines back-to-back, same case_id
    for i in range(1, len(lines)):
        prev, cur = lines[i - 1], lines[i]
        if prev.get("event") == "process_started" and cur.get("event") == "process_started":
            if prev.get("case_id") == cur.get("case_id"):
                exact_dup += 1

    # same process code restarting for a new case, with no switch/suspend in between
    last_started = None
    for ev in lines:
        et = ev.get("event")
        if et == "process_started":
            code = ev.get("process_code")
            if last_started == code:
                same_code_no_switch_between += 1
                if sample is None:
                    sample = (gt_path, ev)
            last_started = code
        elif et in ("process_switched_out", "process_suspended"):
            last_started = None

print("literal back-to-back duplicates (same case_id):", exact_dup)
print("same process code restarting with no switch/suspend between:",
      same_code_no_switch_between)
if sample:
    print("sample:", sample[0])
    print(" ", json.dumps(sample[1], ensure_ascii=False))
