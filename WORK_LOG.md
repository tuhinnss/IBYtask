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

Day 2:
### Boundary Neighborhood Analysis

Developed `explore_boundary_neighborhoods.py` to analyze raw event activity in the proximity of **1,752 real process boundaries** and mid-task control points.
Main finding – the density of **app switching events is much higher near boundaries** – median **26 app switches vs 2** in a window of ±10s. Also, the closest app switch occurred much closer to a real boundary – **206ms vs 3.7s**.
But still, only **64.3%** of boundaries were associated with an app switch event within 3 seconds, which means that the use of just one switch close enough to the boundary point can miss too many cases. However, the signal is present in all 15 process families, ranging from 51% to 71%.
Also analyzed gaps between events and concluded that all negative gaps occurred during `screenshot_smart` events, which means that it is some specific behavior of timestamps, and not some data quality problem.
**Conclusion:** app switching **burst/density** is a significant signal of boundaries, but should not be seen as a one-switch signal.

### App Transition Analysis

Built `explore_app_transitions.py` to check whether the *specific* app-to-app transition (not just "a switch happened") carries a boundary signal. Found something I didn't expect first: **88.3% of all app_switch events are Chrome→Chrome** (same app both sides) — almost certainly multi-window focus noise inside Chrome, not real navigation. Once I looked past that, real transitions split cleanly into two groups: `Excel→Chrome` (n=248) is **83.5%** boundary-associated — a strong "new task starting" tell — while `Word/Teams/PowerPoint→Chrome` are **0–27%** boundary-associated, i.e. almost always mid-task check-ins that return to the same work, not a new task.
**Conclusion:** not all switches are equal — some transition types should push toward a boundary guess, others should suppress one.

### Same-Process Restart Analysis

Followed up on Day 1's finding of 230 "quiet" restarts (same process code repeating with no `process_switched_out`/`process_suspended` marker). Ran the Step 2 boundary-neighborhood check on just these 230 and the result is stark: **median app_switch_count = 2**, matching Step 2's *non-boundary control* exactly, and only **9.1%** have an app_switch within 3s (vs 72.9% for normal boundaries). These 12.6% of all boundaries are essentially invisible to the app-switch signal — the telemetry genuinely looks like uninterrupted work.
**Conclusion:** this is likely the hardest sub-problem for the segmenter; app-switch-based detection alone won't catch these.

### Interruption/Resumption Analysis

Paired `process_suspended`/`process_resumed` via `split_id` (190 pairs) and checked the boundary signal at the **resume** point specifically — worried it might be another blind spot like the restarts above. It isn't: resume points show **65.8%** app-switch-within-3s and a median app_switch_count of **26.5**, statistically the same as ordinary boundaries. Away-time is almost always long (median **363s / ~6 min**, 99% over 60s) — a real context switch, not a quick glance. This also let me correct two guesses from earlier: the Step 2 control-point 22s-gap outlier isn't explained by these (structurally can't be, since a suspend/resume splits into two separate ground-truth executions), and the Word/Teams/PowerPoint anti-boundary pattern above is a *different*, shorter phenomenon than formal interruptions, not the same mechanism.
**Conclusion:** interruption/resumption doesn't need special-case detection handling — the existing signal already covers it.

### Case/Context Signal Analysis

Checked whether actual on-screen/clipboard *content* (not just behavior) could label the families app identity can't tell apart. Raw `clipboard_change.text_content` is a dead end — **0% of 5,198 events** across all of dataset_a have any actual text, only length. But `context.extracted_text` (screen OCR) is a real, near-universal signal: present in **97.7%** of executions, and — checked against what `gt.jsonl` says was actually copied — it captures that same content **70.5%** of the time.
**Conclusion:** clipboard content is unusable, but OCR text is the most promising untested lead for solving the 10-ambiguous-family labeling problem.

### Window-Title Analysis

Tested Day 2's one-off "Notepad titles hurt purity" finding properly — across all four office apps, at several normalization levels, using the same purity math as the segmenter evaluator. Raw title and first-word both land within noise of the naive app-name baseline (~24% purity). Stripping everything after the first digit gets purity up to **39.3%** but coverage collapses to **32%** — a real but narrow improvement, still below what OCR (Step 6) or the actual working segmenter already achieve.
**Conclusion:** window titles are a closed question now, not just an assumption — not worth further investment.

### Event-Type / Activity-Pattern Analysis

Checked whether the *timing* of event types within an execution (not totals, already covered on Day 1) fingerprints a family — e.g. does keystroke activity cluster early or late. Mostly negative: per-family deviations from the overall timing baseline are small (mostly <0.15 on a 0–1 scale) and noisy. One nice cross-check: `app_switch` events cluster earliest overall (centroid 0.36 vs ~0.5–0.6 for everything else), which lines up with the boundary-neighborhood finding above. 予算差異分析 (budget variance) stood out again as later-loaded across several event types — but it's the same family Day 1 already flagged as easy (PowerPoint), not a new lead.
**Conclusion:** activity rhythm doesn't add a new labeling signal — closes another avenue, same as window titles.

### Hard-Case Analysis

Built `explore_hard_cases.py` to fold every weak spot found so far into one difficulty score per execution – quiet restart, duration outlier, ambiguous app-set, missing OCR.
Main finding – the difficulty here is broad but shallow. **74.4%** of executions have an app-set shared by 5+ families, but only **13.2%** carry two or more problems at once, and **zero out of 1,589** carry all four. Even the worst cases leave me at least one usable signal. 予算差異分析 is confirmed the easiest family (mean score **0.17**), 経費精算承認 the hardest (**1.23**).
**Conclusion:** I don't need to solve one impossible worst case – I need a strong default for the ambiguous majority plus cheap fallbacks for the rare problems, since they almost never stack.

### Segmentation Design

Wrote the last two days up into `notes/segmentation_design.md` – the spec I'll build against tomorrow, not code yet.
The main decision – **boundary detection and labeling have to be two separate stages**. That is exactly what my earlier rough segmenter got wrong: one "signature change" mechanism doing both jobs, which is why it hit 93.4% on boundaries but only **31.8%** on labels. App identity is a strong boundary signal and a useless label signal, so the two can't share a mechanism. Boundaries get the behavioural signals (transition density, weighted by transition type, snapped to the nearest real transition); labels get the content ones (document anchor first, then OCR).
I also fixed the bar now instead of chasing it later – **≥85%** boundary hit rate (quiet restarts cap it near 87% anyway) and **≥60%** label purity, up from 31.8%.
**Conclusion:** the whole design leans on OCR text being family-distinguishing, which Step 6 never actually proved – so Day 3 starts with a one-hour check of that assumption before I build anything on top of it.


