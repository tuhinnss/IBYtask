"""Day 3, Step 1: the decisive question -- does OCR text actually
DISTINGUISH process families, or is it just present and accurate?

Step 6 proved extracted_text is available (97.7% of executions) and
faithful (70.5% content accuracy). It never proved it separates
families, and the whole Stage B labeling design depends on that.

This builds a term profile per family from a TRAIN split and classifies
HELD-OUT executions by nearest profile. Two variants:
  all_terms   -- everything
  no_ids      -- ID-like tokens (INV-124819-003, bare digits) stripped,
                 to see how much accuracy is carried by ID patterns
                 rather than real vocabulary.

Also inventories every Chrome URL in dataset_a (closing the open-ideas
item about only ever looking at the top 25).

Run from the repo root:
    python src/explore_ocr_labeling.py
"""
import sys
import os
import re
import json
import glob
import math
import collections
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

TRAIN_EVERY = 10          # deterministic split: 7/10 train, 3/10 test
BOILERPLATE_DF = 0.40     # drop terms appearing in >40% of executions
MIN_DF = 3

ASCII_TOKEN = re.compile(r"[A-Za-z0-9_\-]{2,}")
ID_LIKE = re.compile(r"^[A-Za-z]{2,5}-\d+(-\d+)?$|^\d+$")


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000


def is_cjk(ch):
    o = ord(ch)
    return (0x3040 <= o <= 0x30FF) or (0x4E00 <= o <= 0x9FFF)


def tokenize(text, drop_ids=False):
    """ASCII word tokens + Japanese character bigrams (no MeCab needed)."""
    toks = []
    for m in ASCII_TOKEN.findall(text):
        t = m.lower()
        if drop_ids and ID_LIKE.match(m):
            continue
        toks.append(t)
    cjk = [c for c in text if is_cjk(c)]
    toks += ["".join(pair) for pair in zip(cjk, cjk[1:])]
    return toks


def load_session_events(session_dir):
    events = []
    for chunk in sorted(glob.glob(f"{session_dir}/chunk_*")):
        try:
            with open(f"{chunk}/events.jsonl", encoding="utf-8") as f:
                events.extend(json.loads(l) for l in f if l.strip())
        except FileNotFoundError:
            pass
    events.sort(key=lambda e: e["timestamp_ms"])
    return events


def collect():
    rows = []
    url_by_family = collections.defaultdict(collections.Counter)
    for gtm_path in sorted(glob.glob("dataset_a/ses_*/gt_manifest.json")):
        sess = os.path.dirname(gtm_path)
        events = load_session_events(sess)
        if not events:
            continue
        gtm = json.load(open(gtm_path, encoding="utf-8"))
        for proc in gtm.get("processes", []):
            fam = proc.get("family_name")
            for ex in proc.get("executions", []):
                if not ex.get("start_ts") or not ex.get("end_ts"):
                    continue
                st, en = parse_ts(ex["start_ts"]), parse_ts(ex["end_ts"])
                texts, urls = [], []
                for e in events:
                    if not (st <= e["timestamp_ms"] <= en):
                        continue
                    ctx = e.get("context") or {}
                    et = (ctx.get("extracted_text") or {}).get("text")
                    if et:
                        texts.append(et)
                    tab = ctx.get("active_browser_tab") or {}
                    if tab.get("url"):
                        urls.append(tab["url"])
                for u in urls:
                    url_by_family[u][fam] += 1
                if texts:
                    rows.append({"family": fam, "text": " ".join(texts)})
    return rows, url_by_family


def evaluate(rows, drop_ids):
    docs = [(r["family"], collections.Counter(tokenize(r["text"], drop_ids))) for r in rows]
    n = len(docs)
    df = collections.Counter()
    for _, c in docs:
        for t in c:
            df[t] += 1
    vocab = {t for t, d in df.items() if MIN_DF <= d <= BOILERPLATE_DF * n}
    idf = {t: math.log(n / df[t]) for t in vocab}

    def vec(counter):
        v = {t: cnt * idf[t] for t, cnt in counter.items() if t in vocab}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    train, test = [], []
    for i, (fam, c) in enumerate(docs):
        (test if i % TRAIN_EVERY >= 7 else train).append((fam, vec(c)))

    profiles = collections.defaultdict(lambda: collections.defaultdict(float))
    for fam, v in train:
        for t, x in v.items():
            profiles[fam][t] += x
    for fam, p in profiles.items():
        norm = math.sqrt(sum(x * x for x in p.values())) or 1.0
        for t in p:
            p[t] /= norm

    correct = 0
    confusion = collections.Counter()
    for fam, v in test:
        best, best_s = None, -1.0
        for cand, p in profiles.items():
            s = sum(x * p.get(t, 0.0) for t, x in v.items())
            if s > best_s:
                best, best_s = cand, s
        if best == fam:
            correct += 1
        else:
            confusion[(fam, best)] += 1
    return correct / len(test), len(test), len(vocab), confusion, profiles


def main():
    rows, url_by_family = collect()
    print(f"executions with OCR text: {len(rows)}")
    fams = collections.Counter(r["family"] for r in rows)
    majority = max(fams.values()) / len(rows)
    print(f"families: {len(fams)}   random baseline: {1/len(fams)*100:.1f}%   "
          f"majority-class baseline: {majority*100:.1f}%\n")

    for label, drop in [("all_terms", False), ("no_ids", True)]:
        acc, ntest, nvocab, conf, profiles = evaluate(rows, drop)
        print(f"=== {label} ===")
        print(f"  vocab={nvocab}  held-out n={ntest}  ACCURACY = {acc*100:.1f}%")
        if conf:
            print("  top confusions (true -> predicted):")
            for (a, b), c in conf.most_common(5):
                print(f"    {a} -> {b}: {c}")
        print()

    print("=== Chrome URL inventory (closing the open-ideas item) ===")
    print(f"distinct URLs seen across dataset_a: {len(url_by_family)}")
    routes = collections.defaultdict(collections.Counter)
    for url, fams_c in url_by_family.items():
        route = "#" + url.split("#", 1)[1] if "#" in url else url.split("://", 1)[-1].split("/", 1)[-1]
        for f, c in fams_c.items():
            routes[route][f] += c
    print(f"distinct routes after stripping host/port: {len(routes)}\n")
    print(f"{'route':45s} {'families':>9s}  {'events':>7s}")
    for route, fams_c in sorted(routes.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {route:43s} {len(fams_c):9d}  {sum(fams_c.values()):7d}")


if __name__ == "__main__":
    main()
