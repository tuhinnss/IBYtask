"""Day 1: how good a process label does dataset_b's app/window data give us?

Answers: which apps actually get used, which Word documents show up (and
under how many different-looking window titles), and what backend
systems sit behind the browser tabs.

Run from the repo root:
    python src/explore_dataset_b_labels.py

Produces the numbers under "Dataset_b, app and title inventory" in
WORK_LOG.md (Day 1 cont.), including the "Compatibility Mode" title-format
gotcha.
"""
import sys
import re
import collections

from log_utils import iter_events

sys.stdout.reconfigure(encoding="utf-8")  # window titles are in Japanese

apps = collections.Counter()
word_titles = collections.Counter()
browser_titles = collections.Counter()

for ses, chunk, ev in iter_events("dataset_b"):
    if ev.get("event_type") != "app_switch":
        continue
    new_app = ev.get("payload", {}).get("new_app", {})
    name = new_app.get("app_name") if isinstance(new_app, dict) else new_app
    title = new_app.get("window_title") if isinstance(new_app, dict) else None

    apps[name] += 1
    if name and "word" in str(name).lower():
        word_titles[title] += 1
    if name and ("chrome" in str(name).lower() or "edge" in str(name).lower()):
        browser_titles[title] += 1

print("apps switched to:", apps.most_common(20))

print("\nWord window titles seen:")
for t, c in word_titles.most_common(30):
    print(f"  {c:3d}  {t}")

print("\nBrowser window titles seen (top 20):")
for t, c in browser_titles.most_common(20):
    print(f"  {c:3d}  {t}")

# --- The same doc shows up as "foo  -  Compatibility Mode - Word" AND
# "foo [Compatibility Mode] - Word", plus blank/"Resume Reading" noise.
# Strip that before counting distinct documents. ---
print("\n=== distinct Word documents after stripping title noise ===")
names = set()
for title in word_titles:
    if not title or title in ("Word", "Resume Reading"):
        continue
    base = re.split(r"\s*(\[Compatibility Mode\]|-  Compatibility Mode)", title)[0].strip()
    if base:
        names.add(base)

print(len(names), "distinct base doc names")
for n in sorted(names):
    print(" -", n)
