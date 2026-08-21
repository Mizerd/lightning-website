#!/usr/bin/env python3
"""Invariant checks on the generated site. Run after any edit to public/.

    python3 tools/check.py

These are the things that have actually broken, not a general test suite:

  * every local reference resolves to a file on disk
  * every package card has its own download button, pointing at its own asset
    (the "every Linux button serves the .deb" bug)
  * the page's baked-in version agrees with releases.json
  * nothing served mentions GitLab -- the site points at GitHub only
  * the Linux commands have copy buttons, and they ship hidden
  * releases.js is not cacheable for longer than the HTML that it rewrites
    (the cache skew that caused that bug to reach a browser)

Exits non-zero on the first failure, so it is usable in a pre-push hook.

The JavaScript paths cannot be checked here -- they need a DOM. To test those,
see the jsdom recipe in the README's "Checking a change" section.
"""

import json
import os
import re
import struct
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

# ---- copy buttons -----------------------------------------------------------
# Linux install commands get a copy button; Windows and macOS get none,
# because their boxes hold GUI actions rather than commands. Every button
# ships hidden, so a reader without JavaScript is never shown one that cannot
# work -- releases.js reveals them.
lin_i, win_i = html.index(">Linux</h3>"), html.index(">Windows</h3>")
linux_col, rest = html[lin_i:win_i], html[win_i:]
# The responsive pass appends class="lg-cmd" after the attribute, so match the
# attribute name rather than assuming it closes the tag.
n_cmds = len(re.findall(r"data-lg-copy(?![a-z-])", linux_col))
n_linux = linux_col.count("data-lg-copybtn")
check("a copy button per Linux command", n_linux and n_linux == n_cmds,
      "%d buttons, %d commands" % (n_linux, n_cmds))
check("no copy buttons outside the Linux column", "data-lg-copybtn" not in rest,
      "%d found" % rest.count("data-lg-copybtn"))
check("every copy button ships hidden",
      html.count("data-lg-copybtn hidden") == html.count("data-lg-copybtn"),
      "%d of %d" % (html.count("data-lg-copybtn hidden"),
                    html.count("data-lg-copybtn")))

# ---- screenshots: sized, and openable --------------------------------------
# Every screenshot carries its own width/height. Without them the box is zero
# pixels tall until the (lazy) image arrives, so the caption sits under
# nothing and the grid jumps as they land. The numbers must be the file's
# real ones, or the reserved box is the wrong shape -- which is worse than
# reserving none at all.
shots = re.findall(r'<img src="/assets/(screenshot-[a-z-]+\.png)"[^>]*?'
                   r'width="(\d+)" height="(\d+)"', html)
check("every screenshot declares its size", len(shots) == 4,
      "%d of 4" % len(shots))

wrong = []
for name, w, h in shots:
    with open(os.path.join(PUB, "assets", name), "rb") as fh:
        head = fh.read(24)
    rw, rh = struct.unpack(">II", head[16:24])
    if (rw, rh) != (int(w), int(h)):
        wrong.append("%s says %sx%s, is %dx%d" % (name, w, h, rw, rh))
check("declared sizes match the files", not wrong, "; ".join(wrong))

# The zoom trigger is a <button> so it is keyboard-reachable; a click handler
# on the <img> would not be. One per screenshot, no more.
n_zoom = html.count("data-lg-zoom ")
check("a zoom trigger per screenshot", n_zoom == 4, "%d triggers" % n_zoom)
check("every Expand badge ships hidden",
      html.count("data-lg-zoomhint hidden") == html.count("data-lg-zoomhint"),
      "%d of %d" % (html.count("data-lg-zoomhint hidden"),
                    html.count("data-lg-zoomhint")))

# ---- the theme strip is the app's real palette ------------------------------
# The swatches are copied from qml/AppTheme.qml in the client repo, which this
# repo cannot see. Nothing here can prove they are current -- but it can prove
# nobody quietly dropped one, which is the failure that would leave the page
# saying "Eleven themes" above ten swatches.
n_sw = html.count('class="lg-swatch"')
claimed = re.search(r">Eleven themes", html)
check("eleven theme swatches", n_sw == 11, "%d swatches" % n_sw)
check("the page still claims eleven", bool(claimed), "heading reworded?")

# ---- structured data --------------------------------------------------------
# Google picked the GitHub repository as this page's canonical while the
# domain still redirected there. The self-referencing canonical says this URL
# is the original; sameAs says the repository is the same project rather than
# a competing copy. Both have to be present and agree with the rest of the
# page, or the signal is noise.
ld_m = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                 html, re.S)
check("a JSON-LD block is present", bool(ld_m))
if ld_m:
    ld = json.loads(ld_m.group(1))
    check("JSON-LD version matches the feed",
          ld.get("softwareVersion") == feed["version"],
          "%s vs %s" % (ld.get("softwareVersion"), feed["version"]))
    check("JSON-LD points back at GitHub",
          any("github.com" in u for u in ld.get("sameAs", [])),
          str(ld.get("sameAs")))
    check("JSON-LD url is the canonical one",
          ld.get("url") == "https://www.lightning-matrix.org/",
          str(ld.get("url")))

canon = re.search(r'<link rel="canonical" href="([^"]*)"', html)
check("a self-referencing canonical",
      bool(canon) and canon.group(1) == "https://www.lightning-matrix.org/",
      canon.group(1) if canon else "absent")

# og:image is referenced by content=, not src=/href=, so the resolver above
# never sees it. A social card that 404s is invisible until someone shares a
# link and gets a blank box.
for prop in ("og:image",):
    m = re.search(r'<meta property="%s" content="([^"]*)"' % prop, html)
    path = m.group(1).split("lightning-matrix.org", 1)[-1] if m else ""
    check("%s resolves" % prop, bool(m) and os.path.exists(PUB + path),
          m.group(1) if m else "absent")

# ---- GitHub only ----------------------------------------------------------
# The site must not link to GitLab or name it. unbundle.py asserts this while
# building; this repeats the check against what is actually on disk, which is
# what gets deployed.
gitlab = sorted(
    os.path.relpath(os.path.join(dirpath, f), ROOT)
    for dirpath, _dirs, files in os.walk(PUB)
    for f in files
    if f.rsplit(".", 1)[-1] in ("html", "json", "js", "txt", "xml")
    and "gitlab" in open(os.path.join(dirpath, f), encoding="utf-8",
                         errors="ignore").read().lower())
check("no GitLab reference in public/", not gitlab, ", ".join(gitlab))

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
