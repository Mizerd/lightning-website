#!/usr/bin/env python3
"""Invariant checks on the generated site. Run after any edit to public/.

    python3 tools/check.py

These are the things that have actually broken, not a general test suite:

  * every local reference resolves to a file on disk
  * every package card has its own download button, pointing at its own asset
    (the "every Linux button serves the .deb" bug)
  * the page's baked-in version agrees with releases.json
  * releases.js is not cacheable for longer than the HTML that it rewrites
    (the cache skew that caused that bug to reach a browser)

Exits non-zero on the first failure, so it is usable in a pre-push hook.

The JavaScript paths cannot be checked here -- they need a DOM. To test those,
see the jsdom recipe in the README's "Checking a change" section.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "public")

failures = []


def check(label, ok, detail=""):
    print("  %-4s %s%s" % ("ok" if ok else "FAIL", label,
                           "" if ok else "  -- " + detail))
    if not ok:
        failures.append(label)


html = open(os.path.join(PUB, "index.html"), encoding="utf-8").read()
feed = json.load(open(os.path.join(PUB, "releases.json"), encoding="utf-8"))
headers = open(os.path.join(PUB, "_headers"), encoding="utf-8").read()

# ---- local references resolve ---------------------------------------------
refs = set(re.findall(r'(?:src|href)="(/[^"]*)"', html))
refs |= {"/" + u for u in re.findall(r'url\("/([^"]*)"\)', html)}
missing = sorted(r for r in refs if not os.path.exists(PUB + r))
check("local references resolve", not missing, ", ".join(missing))

# ---- one download button per package, each pointing somewhere different ----
cards = re.findall(
    r'data-lg-format="([^"]*)"[^>]*data-lg-file="([^"]*)"(.*?)(?=<div data-lg-pkg|</section)',
    html, re.S)
pkgs = feed["packages"]
check("a card per package", len(cards) == len(pkgs),
      "%d cards vs %d packages" % (len(cards), len(pkgs)))

hrefs, bad = [], []
for fmt, fil, body in cards:
    m = re.search(r'data-lg-dl[^>]*href="([^"]*)"', body)
    if not m:
        bad.append("%s has no button" % fmt)
        continue
    hrefs.append(m.group(1))
    # The button must point at this card's own file, not a neighbour's.
    if fil and not m.group(1).endswith(fil):
        bad.append("%s button -> %s" % (fmt, m.group(1).rsplit("/", 1)[-1]))
check("each button points at its own asset", not bad, "; ".join(bad))
check("every button URL is distinct", len(hrefs) == len(set(hrefs)),
      "%d buttons, %d distinct" % (len(hrefs), len(set(hrefs))))

# ---- filenames match the feed ---------------------------------------------
feed_files = [p.get("file", "") for p in pkgs]
card_files = [f for _, f, _ in cards]
check("card filenames match releases.json", card_files == feed_files,
      "%s != %s" % (card_files, feed_files))

# ---- version agreement ----------------------------------------------------
baked = set(re.findall(r'data-lg-bind="version">([^<]*)<', html))
check("baked version matches feed", baked == {feed["version"]},
      "%s vs %s" % (baked, feed["version"]))

# ---- no cache skew between the HTML and the script that rewrites it -------
js_rule = re.search(r"^/releases\.js\s*\n\s*Cache-Control:\s*(.+)$",
                    headers, re.M)
policy = (js_rule.group(1).strip() if js_rule else "(no rule)")
# A max-age above zero lets an old script run against new HTML.
stale_ok = re.search(r"max-age=([1-9]\d*)", policy)
check("releases.js is not cacheable past the HTML", not stale_ok,
      "policy is %r; use no-cache" % policy)

print()
if failures:
    print("FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all checks passed")
