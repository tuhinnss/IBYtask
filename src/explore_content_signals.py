"""Day 1, Session 2, Step 6: is there a usable CONTENT signal (not just
behavioral), and is it something dataset_b could actually produce too
(since dataset_b has no gt.jsonl to lean on)?

Two checks:
1. Does raw clipboard_change.payload.text_content ever actually contain
   clipboard text, across all of dataset_a? (DATA_SCHEMA doesn't say
   it's redacted, but a spot-check in this session suggested it might be.)
2. context.extracted_text (screen OCR) covers ~4% of events per
   DATA_SCHEMA. Using gt.jsonl's OWN clipboard_copy content_preview as an
   oracle (production-unavailable, but fine for validating HERE): when a
   case-identifying string was copied during an execution, does the OCR
   text anywhere in that execution's window ever contain it?

Run from the repo root:
    python src/explore_content_signals.py

Writes outputs/content_signals.jsonl (gitignored).
"""
import sys
import json
import glob
import statistics as stats
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")


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
    # --- Check 1: is clipboard_change.text_content ever populated, across ALL of dataset_a? ---
    cc_total = 0
    cc_with_content = 0
    for ses in sorted(glob.glob("dataset_a/ses_*")):
        for chunk in sorted(glob.glob(f"{ses}/chunk_*")):
            for line in open(f"{chunk}/events.jsonl", encoding="utf-8"):
                ev = json.loads(line)
                if ev.get("event_type") == "clipboard_change":
                    cc_total += 1
                    if (ev.get("payload") or {}).get("text_content"):
                        cc_with_content += 1

    print("=== Check 1: raw clipboard_change.payload.text_content ===")
    print(f"  total clipboard_change events (all of dataset_a): {cc_total}")
    print(f"  with non-null/non-empty text_content: {cc_with_content} "
          f"({cc_with_content / cc_total * 100:.1f}%)")
    print("  -> if 0%: clipboard CONTENT is not usable, only clipboard TIMING/frequency is.\n")

    # --- Check 2: extracted_text coverage + does it capture what was actually copied? ---
    rows = []
    for gtm_path in sorted(glob.glob("dataset_a/ses_*/gt_manifest.json")):
        session_dir = gtm_path.rsplit("/gt_manifest.json", 1)[0].rsplit(
            "\\gt_manifest.json", 1
        )[0]
        gt_path = f"{session_dir}/gt.jsonl"
        try:
            gt_lines = [json.loads(l) for l in open(gt_path, encoding="utf-8") if l.strip()]
        except FileNotFoundError:
            continue
        events = load_session_events(session_dir)
        if not events:
            continue

        with open(gtm_path, encoding="utf-8") as f:
            gtm = json.load(f)

        copies = [
            (parse_ts(e["ts_utc"]), e.get("content_preview"))
            for e in gt_lines
            if e.get("event") == "clipboard_copy" and e.get("content_preview")
        ]

        for proc in gtm.get("processes", []):
            fam = proc.get("family_name")
            for ex in proc.get("executions", []):
                if not ex.get("start_ts") or not ex.get("end_ts"):
                    continue
                st_ms, en_ms = parse_ts(ex["start_ts"]), parse_ts(ex["end_ts"])

                window = [e for e in events if st_ms <= e["timestamp_ms"] <= en_ms]
                ocr_texts = [
                    e["context"]["extracted_text"]["text"]
                    for e in window
                    if e.get("context", {}).get("extracted_text", {}).get("text")
                ]
                ocr_blob = " ".join(ocr_texts)
                ocr_char_count = len(ocr_blob)

                copied_here = [c for ts, c in copies if st_ms <= ts <= en_ms]
                hits = sum(1 for c in copied_here if c in ocr_blob)

                rows.append({
                    "family_name": fam,
                    "has_ocr": bool(ocr_texts),
                    "ocr_char_count": ocr_char_count,
                    "copied_values": copied_here,
                    "ocr_captured_copied_value": hits > 0 if copied_here else None,
                })

    with open("outputs/content_signals.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(rows)
    has_ocr_n = sum(1 for r in rows if r["has_ocr"])
    print("=== Check 2: context.extracted_text (screen OCR) coverage ===")
    print(f"  executions with >=1 OCR'd text event in their window: {has_ocr_n}/{n} "
          f"({has_ocr_n / n * 100:.1f}%)")

    checkable = [r for r in rows if r["ocr_captured_copied_value"] is not None]
    captured = [r for r in checkable if r["ocr_captured_copied_value"]]
    print(f"\n  executions where something was copied (checkable against OCR): {len(checkable)}")
    print(f"  of those, OCR text ANYWHERE in the window contained the copied value: "
          f"{len(captured)}/{len(checkable)} ({len(captured) / len(checkable) * 100:.1f}%)")

    print("\n=== OCR char-count stability per family (of executions that have any OCR) ===")
    by_fam = {}
    for r in rows:
        if r["has_ocr"]:
            by_fam.setdefault(r["family_name"], []).append(r["ocr_char_count"])
    for fam, vals in sorted(by_fam.items(), key=lambda kv: -len(kv[1])):
        mean = stats.mean(vals)
        cv = stats.pstdev(vals) / mean if mean else float("nan")
        print(f"  {fam:14s} n={len(vals):3d}  median={stats.median(vals):6.0f} chars  CV={cv:.2f}")


if __name__ == "__main__":
    main()
