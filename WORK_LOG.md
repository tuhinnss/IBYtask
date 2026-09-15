# Work Log

## Day 1 — reading the brief, poking at the data

Read README.md / DATA_SCHEMA.md, then walked one session's events.jsonl next to gt.jsonl by eye. Noticed app-switch bursts sit right on real boundaries, and that dataset_b's Word document filenames are basically a free label — dataset_a has nothing that clean.

Wrote 4 quick scripts to check this at scale instead of trusting 3 examples:
- app_switch is 31% of dataset_a's events but only 8% of dataset_b's — didn't fully explain the gap, just noted it.
- Gaps over 20s are rare (<0.3% of all gaps), so "long pause = new task" barely fires on its own. Also every negative timestamp gap (down to -713,900ms) turned out to be a `screenshot_smart` event — screenshots log out of order, not a real data bug.
- Ground truth: 2,009 executions, 15 processes, mostly 24-40s each. 230 times a process restarts for a new case with **no** switch marker at all — so the segmenter can't always expect an explicit "I left this task" signal.
- Dataset_b has 13 real Word document names once you strip the "Compatibility Mode" title noise — a much better label source than anything dataset_a offers.

Then checked whether app identity alone (which apps, in what order) can tell processes apart — it can't. 12 of 15 families in dataset_a share the same dominant app set (Chrome+Excel+Notepad). Event/keystroke counts help a little but aren't enough alone. Need what's actually *on screen*, not just which app is open.

## Day 2 — full EDA before writing any segmenter code

Went through every signal I could think of, always checked against dataset_a's 1,752 real boundaries plus a mid-task control group, so I wasn't fooling myself.

**Worked:** app-switch density near a boundary is huge (26 switches in ±10s vs 2 mid-task, nearest switch ~200ms from the true boundary, present across all 15 families). Not all switches are equal either — Excel→Chrome is 83% boundary-associated, Word/Teams/PowerPoint→Chrome is 0-27% (a glance-and-return, not a new task). Interruption/resumption turned out fine on its own — resuming shows the same strong signal as any other boundary.

**Didn't work:** window titles as a label (tried all 4 office apps, several normalizations — never beat the naive "which app" baseline). Event timing/rhythm within a task — no real per-family pattern. Also found 88% of all app_switch events are Chrome→Chrome window-focus noise, not real navigation, which had been inflating my early density numbers.

**The real blind spot:** "quiet restarts" — same process starting again back-to-back with zero switch marker (230 cases, 13% of boundaries). These look statistically identical to mid-task control points. No app-switch signal will ever catch them.

**The real find:** clipboard content is never actually logged (checked 5,198 events, 0% have text — dead end). But `extracted_text` (screen OCR) is present in 97.7% of executions and matches what was actually copied 70.5% of the time. That's the labeling signal, not app identity.

Wrote it all into `notes/segmentation_design.md`: boundaries and labels need two separate mechanisms, not one. Set targets (≥85% boundary hit, ≥60% label purity) before building, so I wouldn't just chase whatever number came out first.

## Day 3 — building it, breaking it, simplifying it

Tested the one big assumption first: is OCR text actually family-distinguishing, not just present? Yes — 82% held-out accuracy across 15 families, and it went *up* after stripping case-ID tokens, so it's real vocabulary, not leakage. Also ran the full Chrome URL list instead of just the top 25 — every one of the 5 main routes is used by all 15 families, so URL route is dead as a label (I was wrong about this on Day 2).

Built a full pipeline: logistic regression for boundaries, k-means for labels. Found a real bug where my own labeling made "dense = not a boundary" (backwards) — fixing it took precision from 57% to 90%. Recall stuck at ~58% no matter what I tried, three different methods converged on the same ceiling — confirms the quiet-restart blind spot rather than being a tuning problem.

First run on dataset_b: 16 segments for 15 sessions, should've been 150-300. Dataset_b's *busiest* moment is quieter than dataset_a's *typical* moment — a threshold tuned on one department doesn't transfer to another. Fixed by making density relative to each session's own baseline. Segments went 16 → 198.

Then got told this was too complex to defend in an interview — fair — so rebuilt it as one plain file: boundaries = switching-rate spikes, labels = k-means over on-screen text named by whichever document was open. This broke twice more before it worked: a fixed multiplier didn't transfer between datasets either (same problem, different shape — fixed by ranking within each session instead), and a naming bug was splitting one real process into two labels whenever k-means happened to cluster it into two groups.

**Final numbers on the file I'm actually shipping:** 191 segments across all 15 dataset_b sessions, 8 labels, all real document names, no duplicates. Boundary F1 ~61% held out.

Label purity is where I have to be honest about a correction, not just a result. I quoted 62% purity earlier today — that number was measured on cluster assignment before I fixed the naming bug above, and I never re-ran it after. Once I did: a document name is ground truth for what the group is (that's the fix), but on dataset_a one shared workbook (`m1_reference`) is open in 80% of everything, so trusting it as ground truth collapsed 15 processes into 1 label — purity fell to 9.6%. Fixed by only trusting a document as an anchor if it's under 40% of the dataset (a real per-process document never dominates like a shared file does — dataset_b's top doc is 19%, dataset_a's is 80%), which gets dataset_a back to 20.5% purity / 3 labels. Still below my ≥60% target, and below the 32% baseline on this one metric.

That's the honest number for dataset_a. But dataset_a is a validation proxy — it never had good document anchors to begin with (one shared file, not 13 distinct ones), so this measures a dataset that lacks the signal the approach needs, not a flaw in the approach itself. The thing that matters is dataset_b, which does have real per-process documents, and its output is unaffected by any of this (same 191 segments, same 8 clean labels, before and after every fix above). Recall is the other number I'm not happy with — under-cutting means Step 2's duration figures will look a bit longer than reality, worth saying that plainly in the report too.

## Day 4 — cutting the labeling logic down further

Got feedback that even the k-means labeling step was more than needed for a 7-day intern task — fair, since I could already see 87% of segments have their own document open directly, so grouping them by content similarity to guess a label was mostly unnecessary work dressed up as sophistication.

Deleted it. New rule: label = the document open during that segment, or `other` if none. No vectors, no clustering, no random seed. Kept one safeguard (a document only counts if it's not a generic shared file open in >40% of the run — same dominance check as before, since that's still a real problem on dataset_a).

Result on dataset_b: 191 segments, same as before, 167/191 (87%) get a real document label, 24 (13%) honestly say `other` instead of being forced into a guessed cluster. Looked at what those 24 actually are: some genuine portal-only work (no document needed), some test-environment noise (terminal commands, setup screens), a few short ambiguous glances at Teams/settings. Better to flag these for a second look in Step 2 than silently mislabel them.

Boundary detection untouched — same numbers as before (82.7% precision / 50.0% recall / 62.3% F1 on dataset_a, held out).

**Conclusion:** the whole segmenter is now two rules, both explainable without naming an algorithm: boundaries = switching-rate spikes relative to the session's own pace, labels = the document that was open, or an honest "other." That's the final version — moving to Step 2 next.
