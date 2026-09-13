#!/usr/bin/env python3
"""Invariant checks on the generated site. Run after any edit to public/.

    python3 tools/check.py

These are the things that have actually broken, not a general test suite:

  * every local reference resolves to a file on disk
  * every package card has its own download button, pointing at its own asset
    (the "every Linux button serves the .deb" bug)
  * every card carries the [data-lg-bind] slots releases.js rewrites, and each
    says what the feed says (the "every Linux card shows the AppImage command"
    bug: releases.js clones card zero, so a missing slot keeps card zero's text)
  * the page's baked-in version agrees with releases.json
  * nothing served mentions GitLab -- the site points at GitHub only
  * the Linux commands have copy buttons, and they ship hidden
  * releases.js is not cacheable for longer than the HTML that it rewrites
    (the cache skew that caused that bug to reach a browser)

Exits non-zero on the first failure, so it is usable in a pre-push hook.

The JavaScript paths cannot be checked here -- they need a DOM. To test those,
see the jsdom recipe in the README's "Checking a change" section.
"""

import html as html_mod
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

# ---- every card resolves to exactly one asset -----------------------------
# /api/latest matches a card to a GitHub asset by SUFFIX. Two cards that share
# one suffix both take whichever asset GitHub happened to list first -- and the
# page looks perfect while doing it, because the hrefs baked into the HTML are
# all correct and only the JavaScript pass goes wrong. That is exactly the
# shape of the bug that once served the .deb from every Linux button.
#
# It stopped being hypothetical in 0.7.5: the Windows portable and the macOS
# bundle are both ".zip". data-lg-match carries a longer, unambiguous suffix
# for such a card, and this is what enforces that no two cards can collide.
tokens = []
for block in re.findall(r'<div data-lg-pkg="[^"]*"[^>]*>', html):
    fmt = re.search(r'data-lg-format="([^"]*)"', block)
    mat = re.search(r'data-lg-match="([^"]*)"', block)
    tokens.append((mat or fmt).group(1).lower() if (mat or fmt) else "")
dupes = sorted({t for t in tokens if tokens.count(t) > 1})
check("no two cards match the same asset suffix", not dupes,
      "shared: " + ", ".join(dupes))
# ...and a match token, where present, must actually be a suffix of the file
# the card names, or it would resolve to nothing at all.
mismatched = []
for block in re.findall(r'<div data-lg-pkg="[^"]*"[^>]*>', html):
    mat = re.search(r'data-lg-match="([^"]*)"', block)
    fil = re.search(r'data-lg-file="([^"]*)"', block)
    if mat and fil and not fil.group(1).lower().endswith(mat.group(1).lower()):
        mismatched.append("%s !~ %s" % (fil.group(1), mat.group(1)))
check("each match token is a suffix of its own file", not mismatched,
      "; ".join(mismatched))

# ---- filenames match the feed ---------------------------------------------
feed_files = [p.get("file", "") for p in pkgs]
card_files = [f for _, f, _ in cards]
check("card filenames match releases.json", card_files == feed_files,
      "%s != %s" % (card_files, feed_files))

# ---- every per-card slot releases.js overwrites exists on every card ------
# releases.js rebuilds the cards at runtime by CLONING CARD ZERO and then
# writing each package's own values into the [data-lg-bind] slots it finds.
# A card missing one of those slots therefore keeps CARD ZERO'S value -- and
# the baked HTML looks perfect, because the miss only shows once the script
# runs. It has happened twice now: first the download button (fixed with the
# unconditional setDownload), then the install command, where a rewrite of
# this page dropped data-lg-bind="pkg.install" from the Linux <code> and every
# Linux card served the AppImage's chmod line.
#
# The text is compared against the feed as well as being present, because a
# slot that exists and says the wrong thing fails in exactly the same way to
# a reader.
slot_missing, slot_wrong = [], []
for (fmt, fil, body), pkg in zip(cards, pkgs):
    for field in ("format", "label", "install"):
        m = re.search(r'data-lg-bind="pkg\.' + field + r'"[^>]*>([^<]*)<', body)
        if not m:
            slot_missing.append("%s has no pkg.%s slot" % (fmt, field))
            continue
        want = html_mod.escape(str(pkg.get(field, "")))
        if m.group(1) != want:
            slot_wrong.append("%s pkg.%s is %r, feed says %r"
                              % (fmt, field, m.group(1), want))
check("every card carries the slots releases.js rewrites", not slot_missing,
      "; ".join(slot_missing))
check("every card slot agrees with the feed", not slot_wrong,
      "; ".join(slot_wrong))

# ---- version agreement ----------------------------------------------------
baked = set(re.findall(r'data-lg-bind="version">([^<]*)<', html))
check("baked version matches feed", baked == {feed["version"]},
      "%s vs %s" % (baked, feed["version"]))

# THE BAKED DATE, not just the baked version.
#
# index.html carries hard-coded values so the page is correct with JavaScript
# OFF -- and that is exactly the reader for whom a stale value is never
# corrected. The version was asserted here; the DATE was not, and on
# 2026-09-13 it was found reading 2026-08-27 against a feed saying 2026-09-10.
# Two weeks wrong, for the only visitor the baked copy exists to serve.
#
# It lives HERE, beside the version it belongs with, and not in the block that
# used to hold it: that block was about motion.js, and deleting the motion
# layer in the same session took this check out with it. A check filed under
# an unrelated heading leaves with that heading.
baked_date = re.search(r'data-lg-bind="released"[^>]*>([^<]+)<', html)
check("the baked release date matches the feed",
      baked_date is not None and baked_date.group(1).strip() == feed["released"],
      "baked %r vs feed %r"
      % (baked_date.group(1).strip() if baked_date else "MISSING",
         feed["released"]))

# ---- copy buttons -----------------------------------------------------------
# Linux install commands get a copy button; Windows and macOS get none,
# because their boxes hold GUI actions rather than commands. Every button
# ships hidden, so a reader without JavaScript is never shown one that cannot
# work -- releases.js reveals them.
# Located by the heading TEXT, not by an exact closing tag: the heading now
# carries a trailing hint span ("AppImage and Flatpak carry their own Qt"),
# and pinning `>Linux</h3>` made this file fail on a page that was correct.
def _col(name):
    m = re.search(r"<h3[^>]*>" + name + r"\b", html)
    if not m:
        raise SystemExit("check.py: no <h3> for " + name)
    return m.start()


lin_i, win_i = _col("Linux"), _col("Windows")
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
# How MANY there are is deliberately not written down here: the set changes
# whenever the client does, and a hard-coded count is exactly what goes stale.
# What has to hold is that EVERY screenshot on the page is sized and openable,
# so the total is counted off the page and the two subsets are compared to it.
on_page = re.findall(r'<img src="/assets/(screenshot-[a-z-]+\.png)"', html)
check("the page shows screenshots", bool(on_page), "none found")

shots = re.findall(r'<img src="/assets/(screenshot-[a-z-]+\.png)"[^>]*?'
                   r'width="(\d+)" height="(\d+)"', html)
check("every screenshot declares its size", len(shots) == len(on_page),
      "%d of %d" % (len(shots), len(on_page)))

wrong = []
for name, w, h in shots:
    with open(os.path.join(PUB, "assets", name), "rb") as fh:
        head = fh.read(24)
    rw, rh = struct.unpack(">II", head[16:24])
    if (rw, rh) != (int(w), int(h)):
        wrong.append("%s says %sx%s, is %dx%d" % (name, w, h, rw, rh))
check("declared sizes match the files", not wrong, "; ".join(wrong))

# A refresh replaces pictures, and the old files are easy to leave behind:
# they are still served, still cost a deploy, and nothing on the page points
# at them. This is what says so.
orphans = sorted(set(f for f in os.listdir(os.path.join(PUB, "assets"))
                     if f.startswith("screenshot-") and f.endswith(".png"))
                 - set(on_page))
check("no unused screenshot in assets/", not orphans, ", ".join(orphans))

# The zoom trigger is a <button> so it is keyboard-reachable; a click handler
# on the <img> would not be. One per screenshot, no more.
n_zoom = html.count("data-lg-zoom ")
check("a zoom trigger per screenshot", n_zoom == len(on_page),
      "%d triggers for %d screenshots" % (n_zoom, len(on_page)))
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

# ---- every weight asked for has a face to answer with ----------------------
# The fonts are self-hosted, and the subset that shipped carries only SOME
# weights: JetBrains Mono at 400/500/700, Manrope at 400/500/600/700. A rule
# asking for a weight with no @font-face does not fall back to a near one --
# with font-display: swap the browser has nothing to swap in and paints the
# run as NOTHING. That is not hypothetical: `.lg-copy` asked JetBrains Mono
# for 600 and every Copy button on the download page was an empty rounded
# rectangle, while the DOM said "Copy" the whole time -- so neither this file
# nor a jsdom test could see it. Only a render could, and only by looking.
faces = {}
for m in re.finditer(r"@font-face\s*\{(.*?)\}", html, re.S):
    body = m.group(1)
    fam = re.search(r"font-family:\s*'([^']+)'", body)
    w = re.search(r"font-weight:\s*(\d+)", body)
    if fam and w:
        faces.setdefault(fam.group(1), set()).add(int(w.group(1)))
check("the page declares its own font faces", bool(faces), "none found")

unanswerable = []
for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", html):
    sel, body = m.group(1).strip(), m.group(2)
    w = re.search(r"font-weight:\s*(\d+)", body)
    fam = re.search(r"font-family:\s*([^;]+);", body)
    if not (w and fam):
        continue
    for name, weights in faces.items():
        if name in fam.group(1) and int(w.group(1)) not in weights:
            unanswerable.append("%s asks %s for %s (have %s)"
                                % (sel.splitlines()[-1].strip(), name, w.group(1),
                                   ",".join(str(x) for x in sorted(weights))))
check("every font-weight has a face to answer it", not unanswerable,
      "; ".join(unanswerable))

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
    # These are absolute URLs inside a JSON data block, so neither the
    # local-reference resolver above nor a browser ever complains about one
    # that 404s -- only a crawler does, silently. The list survived a
    # screenshot refresh naming four files that no longer existed.
    ld_shots = [u for u in ld.get("screenshot", [])
                if not os.path.exists(
                    PUB + u.split("lightning-matrix.org", 1)[-1])]
    check("every JSON-LD screenshot resolves", not ld_shots,
          ", ".join(ld_shots))

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

# ---- motion ---------------------------------------------------------------
# THE MOTION LAYER IS GONE, and so are the five invariants that tested it.
#
# They asserted that the progress bar shipped empty, that the scroll sentinel
# existed, that the hero "arrived as a ladder", that the swatches cascaded and
# that panels were tagged for the spotlight -- every one of them a check on a
# decoration rather than on the product. The 2026-09-13 redesign deleted the
# decorations (eight keyframes, 35 scroll reveals, the marquee, the progress
# bar) because the application has none of them, and a page built from the
# app's own tokens should not either. releases.js already owns the two
# behaviours that were worth keeping -- the lightbox and the copy buttons --
# so motion.js went with them.


# ---- no cache skew between the HTML and the scripts that read it ----------
# releases.js reads the DOM the generator emits, so it may not outlive that
# DOM in a cache. This is the check that would have caught the bug where a
# new page ran an hour-old script. It is written as a loop over a tuple
# because the site has carried two such scripts before and may again.
for script in ("releases.js",):
    js_rule = re.search(r"^/%s\s*\n\s*Cache-Control:\s*(.+)$"
                        % re.escape(script), headers, re.M)
    policy = (js_rule.group(1).strip() if js_rule else "(no rule)")
    # A max-age above zero lets an old script run against new HTML.
    stale_ok = re.search(r"max-age=([1-9]\d*)", policy)
    check("%s is not cacheable past the HTML" % script, not stale_ok,
          "policy is %r; use no-cache" % policy)

print()
if failures:
    print("FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all checks passed")
