# Open Ideas / Follow-ups

Running list of things flagged mid-analysis that are worth checking
later but weren't the step we were on at the time. Chat history doesn't
reliably carry across sessions, so these live here instead. Mark `[x]`
when addressed, and say where/how.

## From Step 1 (process execution signatures)
- [ ] Only ever looked at the TOP 25 Chrome URLs in dataset_a. The 10
  process families with no obvious `#/route` match might have their own
  lower-frequency URL routes that just didn't make a top-25 list. Worth
  a dedicated check before concluding the browser gives us nothing for
  those families.

## From Step 2 (boundary neighborhood analysis)
- [x] Control-point (mid-execution) spanning-gap has a p90 of 22s — 10%
  of "definitely mid-task" moments sit inside a 20+ second silence.
  CHECKED in Step 5: NOT explained by formal interruptions — a
  suspend/resume gap splits into two separate gt_manifest executions, so
  it structurally can't land inside one execution's midpoint. Still
  unexplained; more likely just Session 1's known long-duration-tail
  executions. Open again if it matters later.

## From Step 3 (app transition analysis)
- [ ] 88.3% of all app_switch events in dataset_a are Chrome->Chrome
  (same app both sides) -- almost certainly multi-window focus noise,
  not real navigation. Worth confirming via active_browser_tab /
  window_title_change whether any of these actually correspond to a
  real route change worth treating as a signal, rather than discarding
  all of them as noise.
- [x] Word/Teams/PowerPoint -> Chrome transitions are strongly
  ANTI-boundary (0-27% vs 60.8% baseline). CHECKED in Step 5: NOT the
  same mechanism as formal interruptions (those have a 6-minute median
  away-time, 99% over 60s). This is a separate, shorter "glance and
  come right back" behavior that never gets a process_suspended marker
  at all -- still worth understanding on its own, just not explained by
  the interruption/resumption data.
