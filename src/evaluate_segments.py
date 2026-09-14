"""Day 2: how good is segmenter.py against dataset_a's ground truth?

Two things the README says actually matter, so those are the two things
measured here:
1. Are segment boundaries roughly right? (overlap against gt_manifest.json
   executions, plus boundary error for the ones that do match)
2. Is the same true process consistently given the same predicted label,
   and different processes given different labels? (purity, both ways)

Usage:
    python src/segmenter.py dataset_a > outputs/segments_a.jsonl
    python src/evaluate_segments.py outputs/segments_a.jsonl
"""
import sys
import json
import glob
import collections
from datetime import datetime


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def load_predicted(path):
    by_session = collections.defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            seg = json.loads(line)
            by_session[seg["session_id"]].append(
                (parse_ts(seg["start"]), parse_ts(seg["end"]), seg["label"])
            )
    for segs in by_session.values():
        segs.sort()
    return by_session


def load_ground_truth():
    by_session = collections.defaultdict(list)
    for gtm_path in sorted(glob.glob("dataset_a/ses_*/gt_manifest.json")):
        session_id = gtm_path.split("/")[-2] if "/" in gtm_path else gtm_path.split("\\")[-2]
        with open(gtm_path, encoding="utf-8") as f:
            gtm = json.load(f)
        for proc in gtm.get("processes", []):
            fam = proc.get("family_name")
            for ex in proc.get("executions", []):
                if not ex.get("start_ts") or not ex.get("end_ts"):
                    continue  # a handful of executions are missing a boundary -- skip
                st = parse_ts(ex["start_ts"])
                en = parse_ts(ex["end_ts"])
                by_session[session_id].append((st, en, fam))
    for execs in by_session.values():
        execs.sort()
    return by_session


def overlap(a_start, a_end, b_start, b_end):
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def main():
    if len(sys.argv) != 2:
        print("usage: python src/evaluate_segments.py <segments.jsonl>", file=sys.stderr)
        sys.exit(1)

    predicted = load_predicted(sys.argv[1])
    gt = load_ground_truth()

    total_gt = 0
    total_pred = 0
    hits = 0  # gt executions with >=50% of their duration covered by one predicted segment
    start_errs, end_errs = [], []
    pred_to_gt = collections.Counter()      # (pred_label) -> Counter(true_family)
    fam_to_pred = collections.Counter()     # (true_family) -> Counter(pred_label)
    pred_label_votes = collections.defaultdict(collections.Counter)
    fam_pred_votes = collections.defaultdict(collections.Counter)

    for session_id, execs in gt.items():
        segs = predicted.get(session_id, [])
        total_gt += len(execs)
        total_pred += len(segs)
        for gst, gen, fam in execs:
            gdur = max(gen - gst, 1e-6)
            best = None
            best_ov = 0.0
            for pst, pen, label in segs:
                ov = overlap(gst, gen, pst, pen)
                if ov > best_ov:
                    best_ov = ov
                    best = (pst, pen, label)
            ratio = best_ov / gdur
            if best and ratio >= 0.5:
                hits += 1
                pst, pen, label = best
                start_errs.append(abs(pst - gst))
                end_errs.append(abs(pen - gen))
                pred_label_votes[label][fam] += 1
                fam_pred_votes[fam][label] += 1

    def median(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else float("nan")

    # purity: for each predicted label, how concentrated is it on one true family?
    purity_num = sum(c.most_common(1)[0][1] for c in pred_label_votes.values())
    purity_den = sum(sum(c.values()) for c in pred_label_votes.values())
    purity = purity_num / purity_den if purity_den else float("nan")

    # inverse purity: for each true family, how concentrated on one predicted label?
    inv_num = sum(c.most_common(1)[0][1] for c in fam_pred_votes.values())
    inv_den = sum(sum(c.values()) for c in fam_pred_votes.values())
    inv_purity = inv_num / inv_den if inv_den else float("nan")

    print(f"gt executions total:        {total_gt}")
    print(f"predicted segments total:   {total_pred}  "
          f"(ratio {total_pred / total_gt:.2f}x)")
    print(f"hit rate (>=50% overlap):   {hits}/{total_gt}  ({hits / total_gt * 100:.1f}%)")
    print(f"median start error (hits):  {median(start_errs):.1f}s")
    print(f"median end error (hits):    {median(end_errs):.1f}s")
    print(f"label purity (pred->true):  {purity * 100:.1f}%  "
          f"(of the events under one predicted label, this % share the same true family)")
    print(f"inverse purity (true->pred):{inv_purity * 100:.1f}%  "
          f"(of one true family's events, this % got the same predicted label)")
    print(f"distinct predicted labels:  {len(pred_label_votes)}  "
          f"(true process families: {len(fam_pred_votes)})")


if __name__ == "__main__":
    main()
