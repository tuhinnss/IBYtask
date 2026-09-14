"""Day 1, Session 2, Step 1: does each process family have a stable
observable fingerprint in the raw telemetry, if you only had the events
inside one execution's time window (no ground truth)?

For every ground-truth execution in dataset_a, slice out the raw events
that fall inside its [start_ts, end_ts] window and compute simple
observable stats: event counts by type, which apps were touched, in what
order. Then aggregate per process family and check how consistent those
stats are.

Run from the repo root:
    python src/explore_process_signatures.py

Also writes the raw per-execution feature rows to
outputs/process_signatures.jsonl (gitignored) in case a later step wants
to reuse them instead of recomputing.
"""
import sys
import json
import glob
import collections
import statistics as stats
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")  # family names are in Japanese


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000  # ms


def load_session_events(session_dir):
    """All events for one session, across chunks, sorted by real timestamp."""
    events = []
    for chunk in sorted(glob.glob(f"{session_dir}/chunk_*")):
        try:
            with open(f"{chunk}/events.jsonl", encoding="utf-8") as f:
                events.extend(json.loads(line) for line in f if line.strip())
        except FileNotFoundError:
            pass
    events.sort(key=lambda e: e["timestamp_ms"])
    return events


def app_name_of(ev):
    if ev.get("event_type") == "app_switch":
        return (ev.get("payload", {}).get("new_app") or {}).get("app_name")
    return None


def signature_for_execution(events, st_ms, en_ms, fallback_app):
    """events must already be sorted by timestamp_ms."""
    window = [e for e in events if st_ms <= e["timestamp_ms"] <= en_ms]

    app_seq = [a for a in (app_name_of(e) for e in window) if a]
    apps = set(app_seq)
    if fallback_app:
        apps.add(fallback_app)
        if not app_seq:
            app_seq = [fallback_app]

    et_counts = collections.Counter(e.get("event_type") for e in window)
    duration_s = max((en_ms - st_ms) / 1000.0, 1e-6)

    return {
        "event_count": len(window),
        "events_per_sec": len(window) / duration_s,
        "duration_s": duration_s,
        "unique_apps": sorted(apps),
        "app_seq": app_seq,
        "app_switch_count": et_counts.get("app_switch", 0),
        "keystroke_count": et_counts.get("keystroke", 0),
        "mouse_click_count": et_counts.get("mouse_click", 0),
        "mouse_scroll_count": et_counts.get("mouse_scroll", 0),
        "clipboard_change_count": et_counts.get("clipboard_change", 0),
        "shortcut_count": et_counts.get("shortcut", 0),
        "text_input_complete_count": et_counts.get("text_input_complete", 0),
        "window_title_change_count": et_counts.get("window_title_change", 0),
        "screenshot_count": et_counts.get("screenshot_smart", 0),
    }


def collapse(seq):
    """Remove consecutive duplicates: [a,a,b,b,a] -> (a,b,a)."""
    out = []
    for x in seq:
        if not out or out[-1] != x:
            out.append(x)
    return tuple(out)


def main():
    rows = []  # one dict per execution, flattened with family/variant/case_id

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
            code = proc.get("code")
            fam = proc.get("family_name")
            for ex in proc.get("executions", []):
                if not ex.get("start_ts") or not ex.get("end_ts"):
                    continue
                st_ms = parse_ts(ex["start_ts"])
                en_ms = parse_ts(ex["end_ts"])

                # fallback: the app active just before the window opens, in
                # case the execution never triggers its own app_switch event
                # (e.g. it's a continuation of already-open work)
                before = [e for e in events if e["timestamp_ms"] < st_ms]
                fallback_app = None
                if before:
                    fallback_app = (
                        before[-1].get("context", {}).get("active_app") or {}
                    ).get("app_name")

                feat = signature_for_execution(events, st_ms, en_ms, fallback_app)
                feat.update({
                    "session_id": session_dir.split("/")[-1].split("\\")[-1],
                    "case_id": ex.get("case_id"),
                    "process_code": code,
                    "family_name": fam,
                    "variant": ex.get("variant"),
                })
                rows.append(feat)

    with open("outputs/process_signatures.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # --- aggregate per family ---
    by_family = collections.defaultdict(list)
    for r in rows:
        by_family[r["family_name"]].append(r)

    numeric_fields = [
        "duration_s", "event_count", "events_per_sec", "app_switch_count",
        "keystroke_count", "mouse_click_count", "mouse_scroll_count",
        "clipboard_change_count", "shortcut_count", "window_title_change_count",
        "screenshot_count",
    ]

    print(f"total executions analyzed: {len(rows)}")
    print(f"process families: {len(by_family)}\n")

    print("=== per-family numeric stability (coefficient of variation = stdev/mean) ===")
    print("lower CV = more stable/predictable signal across executions of that family\n")
    cv_by_field = collections.defaultdict(list)
    for fam, execs in sorted(by_family.items(), key=lambda kv: -len(kv[1])):
        print(f"{fam}  (n={len(execs)})")
        for field in numeric_fields:
            vals = [e[field] for e in execs]
            mean = stats.mean(vals)
            sd = stats.pstdev(vals)
            cv = sd / mean if mean else float("nan")
            cv_by_field[field].append(cv)
            print(f"    {field:26s} median={stats.median(vals):7.2f}  mean={mean:7.2f}  CV={cv:5.2f}")
        print()

    print("=== which numeric features are most stable OVERALL (avg CV across families) ===")
    for field, cvs in sorted(cv_by_field.items(), key=lambda kv: stats.mean(kv[1])):
        print(f"  {field:26s} avg CV = {stats.mean(cvs):.2f}")

    print("\n=== app-set / app-sequence purity per family ===")
    print("'app-set match %' = fraction of this family's executions whose exact")
    print("set of touched apps equals the single most common set for that family.")
    print("'sequence match %' = same idea but for the collapsed app-switch ORDER.\n")
    for fam, execs in sorted(by_family.items(), key=lambda kv: -len(kv[1])):
        app_sets = collections.Counter(frozenset(e["unique_apps"]) for e in execs)
        top_set, top_set_n = app_sets.most_common(1)[0]
        seqs = collections.Counter(collapse(e["app_seq"]) for e in execs)
        top_seq, top_seq_n = seqs.most_common(1)[0]
        print(f"{fam}  (n={len(execs)})")
        print(f"    dominant app set:      {sorted(top_set)}  "
              f"-> {top_set_n}/{len(execs)} ({top_set_n / len(execs) * 100:.0f}%), "
              f"{len(app_sets)} distinct sets seen")
        print(f"    dominant app sequence: {top_seq}  "
              f"-> {top_seq_n}/{len(execs)} ({top_seq_n / len(execs) * 100:.0f}%), "
              f"{len(seqs)} distinct sequences seen")


if __name__ == "__main__":
    main()
