# Step 1 — first approach (plain English), Day 1

Based on 3 hand-checked examples (see day1_example_*.md), here's the simple rule
to try first on Day 2. Not code yet — just the idea, in plain words.

## The idea
1. **Group the timeline into bursts of activity around a small set of apps.**
   Walk through events in time order. Keep a rolling "which apps have been
   touched in the last ~20-30 seconds" window. As long as activity keeps
   cycling within roughly the same small set of apps (e.g. just Word + one
   web system, or just Chrome + Excel + Notepad), keep it as ONE ongoing segment.

2. **Cut a new segment when either:**
   - There's a long gap with no activity at all (person stepped away), OR
   - There's a sudden burst of app-switching that settles into a NEW small set
     of apps that's clearly different from the previous set (this is the
     "task changed" signal we saw at the A->M boundary), OR
   - A completely new "anchor" app appears (a new Word doc filename, or a
     different page/section of a web system) that doesn't match what was
     just being worked on.

3. **Label each segment** using whatever identifies it best:
   - If a Word document is involved: use ITS FILENAME as the label
     (e.g. "shinkuitorihikisaki_touroku_tetsuzuki") — dataset_b gives us this
     almost for free.
   - If no document, use the combination of apps + any distinctive
     window-title/URL pattern (e.g. section of a web system like
     "#/payroll-items") as the label.
   - Same combination seen again later -> same label, even if it's a totally
     different time of day. (This is what makes "same process, same label"
     work automatically instead of hand-naming things.)

4. **Don't try to track exact case identity** (which specific person/invoice/
   supplier this is). We only need to be right about WHEN a task happened and
   WHAT TYPE it was — not which individual case. (Confirmed by the B-split
   example, where even the ground truth itself doesn't cleanly track this.)

5. **Interrupted-and-resumed work** (like the B example) is OK to treat as two
   separate segments with the same label, rather than trying to merge them
   into one. Simpler, and probably good enough.

## What "good enough" means (to decide precisely on Day 2, once we can measure it)
Two things we'll check against dataset_a's answer key:
- **Are the start/end times roughly right?** (within a handful of seconds of
  the true boundary counts as a hit)
- **Is the same type of process always given the same label, and different
  types given different labels?** (this is the "consistency" the README cares
  about — not what we NAME things, just whether we're consistent)

## Open questions for Day 2
- What gap length (in seconds) actually separates "still working" from
  "stepped away"? Need to measure this properly across many examples, not
  guess from 3.
- How to handle the messy/busy period we saw at the start of the dataset_b
  example (18:32-18:34) — multiple short things mixed together?
- Does the "small set of apps" idea break when a task legitimately touches
  4+ apps, or when two DIFFERENT tasks happen to use the exact same 2 apps?
