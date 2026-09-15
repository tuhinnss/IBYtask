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
| Screen OCR (`extracted_text`) | **Validated — strongest label signal** | 82.1% held-out family accuracy vs 6.7% random (Day 3) |
| Document/file anchors | **Strong** for labels in dataset_b | 13 distinct procedures (Day 1) |
| Browser URL route | **Dead in A** — all 5 main routes used by all 15 families; generic in B | Day 3 |
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
3. **Browser URL route** — **demoted to near-useless (Day 3).** The
   full URL inventory shows all five main routes (`#/resident-tax`,
   `#/leave-applications`, `#/payroll-items`, `#/onboarding`,
   `#/social-insurance`) are visited by *all 15 families* — every family
   touches every route, so the route carries no family information in
   dataset_a. Day 2's "covers 5/15 families" reading was wrong. Keep only
   as a weak co-occurrence feature, never as a primary anchor.
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

### B3. ✅ Dependency tested and cleared (Day 3)
Step 6 proved OCR text is *usable*; it did not prove it is
*family-distinguishing*. That was the single assumption the whole of
Stage B rested on, so Day 3 tested it before building anything.

`src/explore_ocr_labeling.py` builds a TF-IDF term profile per family
from a 70% train split and classifies **held-out** executions by nearest
profile:

```
held-out n=513, 15 families
  random baseline        6.7%
  majority-class         8.8%
  all terms             80.7%
  ID-like tokens removed 82.1%   <- signal is real vocabulary, not case-IDs
```

Two things make this convincing rather than just a nice number:

1. **Stripping ID-like tokens made it BETTER, not worse.** If accuracy
   had been carried by case-ID prefixes (`INV-`, `SHP-`, `EXP-`), it
   would have collapsed — those are dataset_a-specific and wouldn't
   transfer. It rose instead, so the signal is genuine process
   vocabulary, which is exactly the kind of thing that *should* transfer
   to dataset_b's different processes.
2. It is ~9x the random baseline on held-out data, not training data.

**Important caveat — do not over-read this number.** It measures
classification given *perfect* ground-truth segment windows and *known*
family labels. The real pipeline has neither:
- Stage A supplies imperfect windows, so real label quality will be lower.
- dataset_b has no labels at all, so the production mechanism must be
  **clustering**, not classification.

What the experiment establishes is that the classes *are separable in
OCR space* — which is the precondition for clustering to work. Validate
the clustering pipeline on dataset_a (cluster, then measure purity
against known families, and use that to choose k) before running it on
dataset_b.

**Known weakness:** every top confusion predicts 出荷追跡 (shipment
tracking) — its profile acts as an attractor, probably because its OCR
content is the most diverse. Worth a profile-normalisation tweak if
labeling quality stalls.

### B2a. Clustering validated on dataset_a (Day 3)

`src/segment_labels.py` clusters segments by OCR term vector (spherical
k-means, tf-idf, ID tokens and non-work sites stripped) and scores the
result against the 15 known families:

```
k     cohesion  purity   inverse purity
12     0.5606    56.9%      72.0%      <- unsupervised elbow picks this
15     0.5984    59.5%      70.7%      <- dataset_a's true k
18     0.6290    66.8%      69.8%
old segmenter baseline:     31.8%      50.8%
```

Purity nearly doubles against the baseline and inverse purity rises
~20 points, so the design's >=60% target is essentially met at true k.

**Choosing k without ground truth.** The elbow heuristic picks 12 where
the truth is 15 — a consistent *under*-estimate, so dataset_b's k gets a
+3 correction. This is a calibration borrowed from one dataset to
another and should be stated as an assumption in the report, not treated
as established.

**Anchors are dataset-specific, exactly as section 6 predicted:**

| | office switches with an anchor | distinct | usable |
|---|---|---|---|
| dataset_a | 90% | 14, but dominated by one shared `m1_reference` workbook | no |
| dataset_b | 61% | 14 genuine procedure names | yes |

So dataset_a must lean on OCR clustering, while dataset_b can use
document anchors to *name* clusters. Labels come from the cluster either
way — the brief evaluates label consistency, not label text, and
clustering is what delivers consistency.

### B4. Filter non-work browsing
The Day 3 URL inventory also surfaced obvious non-business browsing
inside execution windows — YouTube, Jira, GitHub, AWS console, Slack,
Claude.ai. This is the README's warned-about *"operations unrelated to
any business process are mixed in."* Cheap win: treat these hosts as
non-work and exclude them from both anchor extraction and OCR term
vectors, so they can't pollute a cluster.

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

## 6a. Domain shift between A and B — the Day 3 failure

The first end-to-end run produced **16 segments across 15 dataset_b
sessions** — about one segment per 11-minute session, when 10-20 tasks
per session is the realistic expectation. Stage A was firing almost no
boundaries on B. The cause:

```
                  switches/min    local density (+/-5s window)
dataset_a              33.5        median 25   max 35
dataset_b               9.8        median  3   max 16
```

**Dataset_b's peak switch density sits below dataset_a's median.** A
model trained on A learned "a boundary looks like density 25-35", a
level B never reaches anywhere, so nothing crossed the threshold. This
is precisely the brief's warning that an approach tuned on A "will not
necessarily transfer to Dataset B", made concrete and measurable.

**Fix:** every scale-sensitive feature is now expressed relative to the
session's own baseline — local density divided by that session's median
density, gaps divided by that session's median gap. The question becomes
"is this an unusually busy moment *for this session*" rather than "does
this exceed an absolute count learned elsewhere". Transition-type lift,
app-set change and the is-real flag were already scale-free.

**Consequence for the report:** any threshold tuned on one department's
data is a liability when deployed to another. That is a deployment risk
worth stating explicitly in the Step 3 write-up, not just a modelling
detail — the same trap would hit an automation tool rolled out from one
department to the next.

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

