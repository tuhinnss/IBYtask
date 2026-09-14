"""Day 1, Session 2, Step 7: does ANY level of window-title normalization
give a usable per-family label signal -- tested properly this time,
across all four office apps and multiple normalization schemes, using
the same purity math the segmenter evaluator uses?

Day 2 tried raw Notepad titles once, it made purity worse, and that was
left as the final word. This step tests it systematically instead of
generalizing from one attempt.

Run from the repo root:
    python src/explore_window_titles.py

Writes outputs/window_title_labels.jsonl (gitignored).
"""
import sys
import re
import json
import glob
import collections
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

OFFICE_APPS = {"Notepad", "Microsoft Excel", "Microsoft Word", "Microsoft PowerPoint"}
BOILERPLATE = {
    "", "excel", "word", "powerpoint", "notepad", "untitled", "find and replace",
    "resume reading", "open", "opening -",
}
_COMPAT_RE = re.compile(
    r"\s*(\[Compatibility Mode\]|-\s*Compatibility Mode|-\s*Protected View|-\s*Safe Mode)"
)
_APP_SUFFIX_RE = re.compile(r"\s*-\s*(Excel|Word|PowerPoint|Notepad)$")


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


def clean_title(title):
    if not title:
        return None
    t = title.lstrip("*").strip()
    t = _COMPAT_RE.split(t)[0].strip()
    t = _APP_SUFFIX_RE.sub("", t).strip()
    if t.lower() in BOILERPLATE:
        return None
    return t or None


_PARENS_RE = re.compile(r"\([^)]*\)")


def scheme_raw(t):
    return t


def scheme_first_token(t):
    parts = t.split()
    return parts[0] if parts else None


def scheme_prefix_before_digit(t):
    t2 = _PARENS_RE.sub("", t)
    tokens = [tok for tok in t2.split() if not any(ch.isdigit() for ch in tok)]
    out = " ".join(tokens).strip(" -")
    return out or None


SCHEMES = {
    "app_name_only": None,  # handled specially as the baseline
    "raw_title": scheme_raw,
    "first_token": scheme_first_token,
    "prefix_before_digit": scheme_prefix_before_digit,
}


def purity(pairs):
    """pairs: list of (label, true_family). Returns (purity, inv_purity, n_labels)."""
    label_votes = collections.defaultdict(collections.Counter)
    fam_votes = collections.defaultdict(collections.Counter)
    for label, fam in pairs:
        label_votes[label][fam] += 1
        fam_votes[fam][label] += 1
    num = sum(c.most_common(1)[0][1] for c in label_votes.values())
    den = sum(sum(c.values()) for c in label_votes.values())
    inv_num = sum(c.most_common(1)[0][1] for c in fam_votes.values())
    inv_den = sum(sum(c.values()) for c in fam_votes.values())
    return (num / den if den else float("nan"),
            inv_num / inv_den if inv_den else float("nan"),
            len(label_votes))


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
                window = [e for e in events if st_ms <= e["timestamp_ms"] <= en_ms]

                titles = []
                apps_seen = []
                for e in window:
                    if e.get("event_type") != "app_switch":
                        continue
                    na = e.get("payload", {}).get("new_app") or {}
                    if na.get("app_name") in OFFICE_APPS:
                        apps_seen.append(na["app_name"])
                        ct = clean_title(na.get("window_title"))
                        if ct:
                            titles.append(ct)

                rows.append({
                    "family_name": fam,
                    "office_app": collections.Counter(apps_seen).most_common(1)[0][0]
                                  if apps_seen else None,
                    "titles": titles,
                })

    with open("outputs/window_title_labels.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"total executions: {len(rows)}\n")
    print("=== purity comparison across labeling schemes ===")
    print("(purity: of executions sharing a label, % that are truly the same family)")
    print("(inverse purity: of one true family's executions, % that got the same label)\n")

    # baseline: label = which single office app dominated (or None if none used)
    baseline_pairs = [(r["office_app"], r["family_name"]) for r in rows if r["office_app"]]
    p, ip, nlab = purity(baseline_pairs)
    print(f"  {'app_name_only (baseline)':26s} coverage={len(baseline_pairs)/len(rows)*100:5.1f}%  "
          f"labels={nlab:3d}  purity={p*100:5.1f}%  inv_purity={ip*100:5.1f}%")

    for name, fn in SCHEMES.items():
        if fn is None:
            continue
        pairs = []
        for r in rows:
            if not r["titles"]:
                continue
            # dominant title under this scheme (mode)
            vals = [fn(t) for t in r["titles"]]
            vals = [v for v in vals if v]
            if not vals:
                continue
            label = collections.Counter(vals).most_common(1)[0][0]
            pairs.append((label, r["family_name"]))
        if not pairs:
            print(f"  {name:26s} coverage=  0.0%  (no usable titles)")
            continue
        p, ip, nlab = purity(pairs)
        print(f"  {name:26s} coverage={len(pairs)/len(rows)*100:5.1f}%  "
              f"labels={nlab:4d}  purity={p*100:5.1f}%  inv_purity={ip*100:5.1f}%")


if __name__ == "__main__":
    main()
