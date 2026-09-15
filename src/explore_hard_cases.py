"""Day 1, Session 2, Step 9: combine the weak spots found in Steps 1-8
into one per-execution "difficulty score", to see whether hard cases are
spread evenly or concentrated, and to pull concrete worst-case examples.

Four difficulty flags, one per prior finding:
  - is_quiet_restart      (Step 4: no app-switch boundary signal at all)
  - is_long_outlier       (Session 1 + Step 1: duration >> the family's
                            own typical duration -- risk of internal
                            fragmentation/misdetection)
  - is_ambiguous_appset   (Step 1: this execution's app-set is shared by
                            >=5 different families in the whole dataset)
  - no_ocr                (Step 6: zero OCR'd screen text anywhere in
                            the execution's window)

Run from the repo root:
    python src/explore_hard_cases.py

Writes outputs/hard_cases.jsonl (gitignored).
"""
import sys
import json
import glob
import statistics as stats
import collections
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

OUTLIER_MULTIPLIER = 3  # duration > 3x the family's own median duration


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


def app_name_of(ev):
    if ev.get("event_type") == "app_switch":
        return (ev.get("payload", {}).get("new_app") or {}).get("app_name")
    return None


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
                if not ex.get("start_ts") or not ex.get("end_ts") or case_id not in restart_flags:
                    continue
                st_ms, en_ms = parse_ts(ex["start_ts"]), parse_ts(ex["end_ts"])
                duration_s = (en_ms - st_ms) / 1000.0
                window = [e for e in events if st_ms <= e["timestamp_ms"] <= en_ms]

                app_seq = [a for a in (app_name_of(e) for e in window) if a]
                app_set = frozenset(app_seq)
                has_ocr = any(
                    e.get("context", {}).get("extracted_text", {}).get("text") for e in window
                )

                rows.append({
                    "session_id": session_dir.split("/")[-1].split("\\")[-1],
                    "case_id": case_id,
                    "family_name": fam,
                    "duration_s": duration_s,
                    "app_set": sorted(app_set),
                    "is_quiet_restart": restart_flags[case_id],
                    "has_ocr": has_ocr,
                })

    # --- post-process: family median duration, app-set ambiguity ---
    by_fam_durations = collections.defaultdict(list)
    for r in rows:
        by_fam_durations[r["family_name"]].append(r["duration_s"])
    fam_median = {f: stats.median(v) for f, v in by_fam_durations.items()}

    set_to_fams = collections.defaultdict(set)
    for r in rows:
        set_to_fams[frozenset(r["app_set"])].add(r["family_name"])

    for r in rows:
        r["is_long_outlier"] = r["duration_s"] > OUTLIER_MULTIPLIER * fam_median[r["family_name"]]
        r["is_ambiguous_appset"] = len(set_to_fams[frozenset(r["app_set"])]) >= 5
        r["no_ocr"] = not r["has_ocr"]
        r["difficulty_score"] = sum([
            r["is_quiet_restart"], r["is_long_outlier"], r["is_ambiguous_appset"], r["no_ocr"]
        ])

    with open("outputs/hard_cases.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(rows)
    print(f"total executions scored: {n}\n")

    print("=== difficulty score distribution (0 = easy, 4 = every flag present) ===")
    score_counts = collections.Counter(r["difficulty_score"] for r in rows)
    for score in sorted(score_counts):
        c = score_counts[score]
        print(f"  score {score}: {c:4d} ({c / n * 100:5.1f}%)")

    print("\n=== individual flag rates ===")
    for flag in ["is_quiet_restart", "is_long_outlier", "is_ambiguous_appset", "no_ocr"]:
        c = sum(1 for r in rows if r[flag])
        print(f"  {flag:22s} {c:4d} ({c / n * 100:.1f}%)")

    print("\n=== per-family: mean difficulty score, ranked hardest first ===")
    by_fam = collections.defaultdict(list)
    for r in rows:
        by_fam[r["family_name"]].append(r["difficulty_score"])
    for fam, scores in sorted(by_fam.items(), key=lambda kv: -stats.mean(kv[1])):
        hard = sum(1 for s in scores if s >= 2)
        print(f"  {fam:14s} mean={stats.mean(scores):.2f}  "
              f"score>=2: {hard}/{len(scores)} ({hard / len(scores) * 100:.0f}%)")

    print("\n=== worst examples (highest difficulty score) ===")
    worst = sorted(rows, key=lambda r: -r["difficulty_score"])[:5]
    for r in worst:
        print(f"  {r['session_id']}  case={r['case_id']}  family={r['family_name']}  "
              f"score={r['difficulty_score']}  duration={r['duration_s']:.0f}s  "
              f"quiet_restart={r['is_quiet_restart']}  long_outlier={r['is_long_outlier']}  "
              f"ambiguous_appset={r['is_ambiguous_appset']}  no_ocr={r['no_ocr']}")


if __name__ == "__main__":
    main()
