# Work Log

## Day 1 — reading the brief, checking  the dataset, trying to find insights.

I read README.md / DATA_SCHEMA.md, then walked `events.jsonl` next to `gt.jsonl` for one session by eye, I found the following:

- A burst of app-switching tends to sit right on a real process boundary.
- Work gets interrupted and resumed under a *new* case_id — even the
  ground truth doesn't cleanly track that as "the same case," so I don't need to either. Two segments, same label, done.
- In dataset_b the Word document filename being edited is basically a free process label. Dataset_a has no such luxury.


Turned the throwaway checks into small scripts under `src/` (share a tiny `src/log_utils.py` for walking session/chunk folders) so these numbers are reproducible, not just asserted. Run any of them from the repo root.

**[`explore_event_stats.py`](src/explore_event_stats.py)** ran this to get an idea of how the both dataset look like 
dataset_a:
63 sessions / 162,768 events, "app_switch" alone is 31% of everything.
dataset_b: 15 sessions / 20,477 events, "app_switch" is only 8%.
Bigger gap than expected — not sure yet if that's a real behavioral
difference or an artifact of A being denser test data.
I got an idea of which were the highest number of events, and the difference betwn both the datasets. 

**[`explore_gaps.py`](src/explore_gaps.py)** — 
I tried finding out gaps which were worth investing into. Found the following in the process:
gap percentiles:
`p95 ≈ 2s, p99 ≈ 5s` in both datasets; only ~0.25% (A) / 0.03% (B) of gaps exceed 20s. So "long gap = stepped away" is a fine rule but it'll fire *rarely* — app-switch-pattern is doing most of the segmenting work, gap is just a tie-breaker.

There is a strange thing I found out:  minimum gap is **negative** (down to
-713,900ms). I checked every event with a gap under -500ms (1,446 of
them) — **100% are `screenshot_smart`**, zero exceptions. Screenshots get logged async and land out of timestamp order even though sequence/array order says otherwise.

**[`explore_ground_truth.py`](src/explore_ground_truth.py)** — 
I studied the ground truth. These were my findings after aggregating all 63 sessions of A: 2,009 executions, 15 process families, near-even finance/hr/ops split. Median durations mostly 24–40s (one outlier, budget variance analysis, at 74s). A few processes have long max-duration tails (vendor contact: median 39s, max 1,145s) — likely the interrupt/resume pattern from Day 1. Only 5/15 families have more than one `variant` (std/exc, reg/adj).

Also chased the schema's "duplicate `process_started`" warning: literal back-to-back duplicates = 0. What actually happens (230 times) is the *same* process code restarting for a new case with **no** switch/suspend marker in between — the next `process_started` line just *is* the boundary. So the segmenter can't always expect an explicit "left this task" signal.

**[`explore_dataset_b_labels.py`](src/explore_dataset_b_labels.py)** I found strong labeling signals in Dataset B: three backend systems visible through Edge (finance, HR/payroll, and order/inventory), along with 13 distinct Word document templates after normalizing the window titles. This gives me a much richer source of process-label information than Dataset A. One issue I found is that Word titles contain formatting noise: the same document appears in two different “Compatibility Mode” formats, while generic titles such as Word and Resume Reading don't provide useful labeling information. I therefore need to strip these before using document filenames as reliable labeling anchors.

### Where this leaves me
- Idle-gap cutoffs: minor signal, don't over-invest. I shouldn't heavily rely on them since they are very rare.
- Screenshot gaps: Their timestamps can be out of order, so I should recompute inter-event gaps from event timestamps rather than trusting sequence order or the reported gap field.
- App-switch-pattern / anchor-document detection carries most of the
  weight — Day 1 hunch confirmed at scale.
- Segmenter must open a new segment on "this pattern just restarted,"not only on "a different pattern appeared."
- For B: normalize Word titles (strip compat-mode suffixes, drop
  blank/"Resume Reading") before using filename as a label\

Day1:Session 2: 

I checked whether each process family has a clear pattern in its raw events. I analyzed 1,752 executions across 15 families and compared the apps used, app order, and basic event statistics.

The main finding was that **apps and app order alone aren't enough to identify the process**. Most processes use the same few apps, mainly Chrome, Excel, and Notepad. The numerical features show some consistency, but they're better as supporting signals rather than the main classifier.
So the more useful information is probably **what is happening inside the apps**, like the Chrome URL, clipboard content, or notes/documents.
Next, I'll check all Chrome URLs instead of only the top 25, to see if the other process families have less frequent but more specific URL patterns.
