# Segmentation Design (evidence-based)

Written at the end of Day 2's EDA (Session 2, Steps 1–9). Every design
decision below cites the step that justifies it. Nothing here is a guess
carried over from the Day 1 hand-traced examples — where the evidence
contradicted those early hunches, the evidence wins.

This is the spec Day 3's implementation should follow.

---

## 1. The one architectural decision that matters

**Boundary detection and labeling are separate problems with separate
signals. Build them as two stages, not one.**

The earlier rough `segmenter.py` conflated them: it tracked a single
"signature" (URL route / doc name / app name) and used *changes in that
signature* both to cut segments and to name them. That's why it scored
well on boundaries (93.4% hit rate) but badly on labels (31.8% purity) —
one mechanism was being asked to do two jobs whose evidence points in
completely different directions:

| | Best signal | Source |
|---|---|---|
| **Boundary detection** | app-transition density (behavioral) | Step 2, 3 |
| **Labeling** | screen content / document anchors | Step 6, Day 1 |

Step 1 is the proof they must be separated: app identity is a *strong*
boundary signal and a *near-useless* label signal (12 of 15 families
share the same dominant app-set).

---

## 2. Evidence summary

What the nine steps actually established:

| Signal | Verdict | Evidence |
|---|---|---|
| App-transition density in a window | **Strong** for boundaries | 13x separation: median 26 vs 2 (Step 2) |
| Nearest-transition proximity | **Strong** for precision | ~206ms at boundary vs 3.7s at control (Step 2) |
| Transition *type* (from→to) | **Strong**, directional | Excel→Chrome 83.5% vs Word/Teams/PPT→Chrome 0–27% (Step 3) |
| Same-app "switches" | **Noise-heavy**, weak | 88.3% of all app_switch events are Chrome→Chrome (Step 3) |
| Idle gaps | **Weak**, high precision when it fires | >20s = 0.25% of gaps (Session 1) |
| Screen OCR (`extracted_text`) | **Most promising** for labels, untested | 97.7% coverage, 70.5% content accuracy (Step 6) |
| Document/file anchors | **Strong** for labels in dataset_b | 13 distinct procedures (Day 1) |
| Browser URL route | **Partial** — 5/15 families in A; generic in B | Day 1, Day 2 |
| App-set / app-sequence | **Weak** for labels | 12/15 families share a set; 21–50% seq match (Step 1) |
| Window titles | **Dead end** | 24% purity, no better than app-name baseline (Step 7) |
| Clipboard content | **Dead end** — never populated | 0 of 5,198 events (Step 6) |
| Event-type timing/rhythm | **Dead end** | deviations <0.15, CV up to 0.70 (Step 8) |

---

## 3. Stage 0 — Preprocessing

1. **Sort events by `timestamp_ms`, never by file/sequence order.**
   `screenshot_smart` events are logged asynchronously and land out of
   chronological order — negative `ms_since_last_event` values down to
   -713,900ms, 100% of them screenshots (Session 1).
2. **Recompute inter-event gaps from timestamps.** Don't trust
   `correlation.ms_since_last_event` near L1 events (same finding).
3. **Classify each `app_switch` into `real_transition` vs
   `same_app_focus`** using `payload.previous_app` vs `payload.new_app`.
   88.3% fall in the latter bucket (Step 3). Keep both — same-app events
   still carry a mild signal (+7.2pp over baseline) — but weight them
   far lower.
4. Merge chunks per session before any of this; chunk boundaries are a
   recording artifact with no relationship to process boundaries.

---

## 4. Stage A — Boundary detection

### A1. Score the timeline
Compute a rolling **boundary score** over a sliding window (~±5s,
tuned on dataset_a):

```
score(t) =  w1 * density(real_transitions, window)
          + w2 * density(same_app_focus, window)      # w2 << w1
          + w3 * transition_type_weight(window)
          + w4 * idle_gap_bonus(t)
```

- `density(real_transitions)` is the workhorse — the 13x separation from
  Step 2 is the single largest effect measured anywhere in the EDA.
- `transition_type_weight` is **signed**, per Step 3: `Excel→Chrome` and
  similar push the score up; `Word→Chrome`, `Teams→Chrome`,
  `PowerPoint→Chrome` push it *down*. These aren't neutral — they're
  0–27% boundary-associated against a 60.8% baseline, so treating them
  as weak-positive (as any density-only approach does) is actively wrong.
- `idle_gap_bonus` fires rarely (0.25% of gaps exceed 20s) but is
  high-precision when it does. Additive bonus, never a primary trigger.

### A2. Pick and snap
- Take local maxima above a threshold as candidate boundaries.
- **Snap each candidate to the nearest `real_transition` event.** At true
  boundaries the nearest transition sits ~206ms away (Step 2) — snapping
  converts a rough peak into a near-exact timestamp, and should
  meaningfully beat the ~8–10s median boundary error the old segmenter
  had.

### A3. The quiet-restart fallback (the known blind spot)
Step 4 is unambiguous: 13.1% of boundaries — the same process restarting
back-to-back for a new case — have **no** transition signal (median 2
transitions in window, identical to non-boundary control points; 9.1%
within 3s vs 72.9% for normal boundaries). No amount of tuning Stage A1
finds these, because the telemetry genuinely looks like continuous work.

Fallback, in order of preference:

1. **Duration-based split (recommended).** After labeling (Stage B),
   compute the duration distribution *per label* within the dataset
   itself. A segment running far beyond its label's own typical duration
   (say >2.5x median) is a candidate for splitting at its internal
   minimum-activity point. This is self-calibrating and needs no ground
   truth, so it works on dataset_b.
2. **Repetition detection (ambitious, optional).** Look for the same
   short action micro-pattern occurring twice within one candidate
   segment and split between repeats. Higher ceiling, much more work,
   and unvalidated — only if Day 3 has time left over.
3. **Accept the loss (the honest default).** A missed quiet restart
   merges two executions of the *same* process. That costs boundary
   accuracy but costs **nothing** in label consistency — the merged
   segment still gets the correct label. Given the brief evaluates both,
   this is the cheapest error to absorb.

### A4. What needs no special handling
Interruption/resumption. Step 5 checked this specifically because Day 1
flagged it as a hard case: resume points show 65.8% within-3s detection
and median 26.5 transitions — statistically identical to ordinary
boundaries. The Stage A1 detector already covers them. Resumed work gets
a separate segment with the *same* label, per the Day 1 decision.

---

## 5. Stage B — Labeling

### B1. Anchor hierarchy (priority by *kind*, not by dwell time)
Per-segment, pick the label anchor in this order:

1. **Document/file anchor** — Word filename, normalized (strip both
   `Compatibility Mode` title formats, drop bare `Word` / `Resume
   Reading` / blank). Strongest available signal in dataset_b: 13
   distinct real procedure names (Day 1).
2. **OCR content signature** — see B2. The main new mechanism.
3. **Browser URL route** — real but limited: covers 5/15 families in
   dataset_a, and dataset_b reuses the *same generic* route strings
   across unrelated departments, so it cannot stand alone there (Day 2).
4. **App-set** — tie-breaker only. One genuinely useful case exists:
   PowerPoint ⇒ budget-variance-analysis, the single family with a
   distinctive app footprint (Step 1, reconfirmed in Steps 8 and 9).

Priority must be by anchor *kind*, not by which anchor accumulated more
time in the segment — that mistake is what let generic URL routes drown
out specific document names in the earlier segmenter.

### B2. OCR content signature (the new core mechanism)
Step 6 established that `context.extracted_text` is present for 97.7% of
executions and accurately reflects on-screen content 70.5% of the time.
This is the only content-level signal that survived the EDA, and it's
available in dataset_b (unlike anything requiring `gt.jsonl`).

Proposed mechanism:
1. Concatenate all `extracted_text` within a segment.
2. Strip boilerplate that appears across all segments (browser chrome,
   "Address and search bar", terminal banners — observed in Step 6).
3. Reduce to a term vector; cluster segments by content similarity.
4. Name each cluster from its most distinctive term or dominant document
   anchor.

This produces *consistent labels without ground truth*, which is exactly
what dataset_b needs.

### B3. ⚠ Untested dependency — test this FIRST on Day 3
Step 6 proved OCR text is **usable** (present and accurate). It did
**not** prove OCR text is **family-distinguishing** — that's the open
item in `notes/open_ideas.md`.

**Day 3 must begin with a cheap check of that hypothesis** (per-family
term overlap on dataset_a, where families are known) before any pipeline
is built on it. If OCR vocabulary does not separate families, Stage B
collapses back to the anchor hierarchy alone and expected label quality
drops to roughly the old segmenter's level — worth knowing in hour one
of Day 3, not on Day 5.

---

## 6. Dataset A vs B — what's shared, what's parameterized

The brief warns they differ, and the EDA confirmed it concretely:

| | dataset_a | dataset_b |
|---|---|---|
| Dominant apps | Chrome + Excel + Notepad | Word + Edge |
| Document anchors | weak (one shared `m1_reference` workbook) | strong (13 procedures) |
| URL routes | 5/15 families | same generic routes, department-agnostic |

**Shared:** Stage 0, Stage A entirely (behavioral signals are
app-agnostic — they operate on transitions, not on *which* apps), and
Stage B's structure.

**Parameterized per dataset:** only the anchor-extraction rules in B1
(which apps yield document anchors, which title formats to normalize).
Keep these in one small config-like block, not scattered through the
code — dataset_b's apps were different than A's, and a third department
would differ again.

---

## 7. What "good enough" means

Deciding this now rather than chasing accuracy on Day 3, per the risk
note in the 7-day plan.

**Boundaries — target ≥85% hit rate at ≥50% overlap.**
Justification: 13.1% of boundaries are quiet restarts with no signal
(Step 4). Unless the Stage A3 fallback works better than expected, ~87%
is close to the practical ceiling. The old segmenter's 93.4% was
measured with a lenient overlap metric and benefited from
over-segmentation (1.31x more segments than ground truth) — some of
those "hits" are accidents of cutting too often. Holding ≥85% with a
segment-count ratio nearer 1.0x is a better outcome than 93% with 1.31x.

**Labels — target ≥60% purity, with fewer than 2x the true label count.**
Justification: baseline is 31.8% purity / 25 labels for 15 true families.
Doubling purity is a meaningful improvement and is plausible *if* B2
works; if B3's check fails, revise this target down immediately and say
so in the report rather than quietly missing it.

**Explicitly not a goal:** 100% boundary recall. Step 4 shows it isn't
achievable from this telemetry, and pursuing it would burn Days 4–6,
which the brief weights far more heavily (the ROI proposal and the
working tool, not segmentation precision for its own sake).

---

## 8. Accepted limitations

State these in the final report rather than hiding them:

1. ~13% of boundaries (quiet same-process restarts) are near-undetectable
   from telemetry alone — Step 4, quantified.
2. ~2.5% of executions have no OCR coverage at all — Step 6/9; these fall
   back to anchor-only labeling.
3. Clipboard *content* is never available, so any approach depending on
   "what was copied" is impossible in production — Step 6, 0 of 5,198.
4. 74.4% of executions have an app-set shared by ≥5 families — labeling
   quality rests almost entirely on Stage B2 working (Step 9).
5. Difficulty is broad-but-shallow: 0 of 1,589 executions carry all four
   difficulty flags (Step 9), so there is always *some* signal — but for
   the hardest 13% it may only be the weakest one.

---

