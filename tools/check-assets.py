#!/usr/bin/env python3
"""Every download card resolves to its own asset, against a REAL release.

check.py proves the page is internally consistent. This proves the thing that
actually breaks: `/api/latest` matches a card to a GitHub asset by SUFFIX, and
whether that lands on the right file depends on what the release published, not
on anything in this repository.

It is the check that would have caught the 0.7.5 hazard before it shipped —
the Windows portable and the macOS bundle are both ".zip", so without a
longer `data-lg-match` suffix both cards take whichever .zip GitHub listed
first. The page looks perfect while doing it: the hrefs baked into the HTML
are all correct, and only the JavaScript pass goes wrong.

    python3 tools/check-assets.py            # newest release on GitHub
    python3 tools/check-assets.py v0.7.5     # a specific tag
    python3 tools/check-assets.py --feed     # offline: names from releases.json

Mirrors assetFor() in releases.js exactly: case-insensitive suffix match,
first asset wins.
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "public")
REPO = "Mizerd/lightning"

errors = []


def check(name, ok, detail=""):
    print("  %-4s %s%s" % ("ok" if ok else "FAIL", name,
                           "" if ok else "  -- " + detail))
    if not ok:
        errors.append(name)


def github_assets(tag):
    url = ("https://api.github.com/repos/%s/releases/latest" % REPO if not tag
           else "https://api.github.com/repos/%s/releases/tags/%s" % (REPO, tag))
    # A plain urlopen is fine here: this is api.github.com, not the GitLab
    # package registry whose reverse proxy 403s a default Python user-agent.
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as fh:
        data = json.load(fh)
    return data.get("tag_name", ""), [a["name"] for a in data.get("assets", [])]


def main():
    args = [a for a in sys.argv[1:]]
    feed = json.load(open(os.path.join(PUB, "releases.json"), encoding="utf-8"))
    if "--feed" in args:
        tag = "v" + feed["version"]
        assets = [p["file"] for p in feed["packages"]] + ["SHA256SUMS"]
        print("release %s (from releases.json), %d assets" % (tag, len(assets)))
    else:
        tag = next((a for a in args if a.startswith("v")), "")
        tag, assets = github_assets(tag)
        print("release %s (from GitHub), %d assets" % (tag, len(assets)))
    check("the release published assets", bool(assets))

    html = open(os.path.join(PUB, "index.html"), encoding="utf-8").read()
    cards = []
    for tag_html in re.findall(r'<div data-lg-pkg="[^"]*"[^>]*>', html):
        def attr(name):
            m = re.search(name + r'="([^"]*)"', tag_html)
            return m.group(1) if m else None
        cards.append((attr("data-lg-pkg"), attr("data-lg-format"),
                      attr("data-lg-match"), attr("data-lg-file")))
    check("the page has download cards", bool(cards))

    # Mirrors assetFor() in releases.js, INCLUDING its resolution order: the
    # longest match token goes first and the asset it claims is removed from
    # the pool. Suffix matching alone cannot separate `lightning_X_amd64.deb`
    # from `lightning_X_ubuntu2604_amd64.deb` -- every suffix of the first is
    # also a suffix of the second -- and 0.9.5 is the first release to publish
    # both. If this file and releases.js ever disagree about the order, this
    # check stops predicting what a visitor's browser will do, which is its
    # only job.
    taken = set()

    def asset_for(token):
        low = token.lower()
        for name in assets:
            if name in taken:
                continue
            if name.lower().endswith(low):
                return name
        return None

    ordered = sorted(cards, key=lambda c: -len(c[2] or ""))
    for os_key, fmt, match, named in ordered:
        token = match or fmt or ""
        got = asset_for(token)
        if got is not None:
            taken.add(got)
        check("%s card (%s) resolves to one asset" % (os_key, token),
              got is not None, "no asset ends with %r" % token)
        if got is not None:
            # The card names a file too (the no-JavaScript path). If the suffix
            # pass and the baked filename disagree, one of the two is wrong and
            # a visitor sees a different download depending on whether their
            # JavaScript ran.
            check("%s card agrees with its own filename" % os_key,
                  got == named, "suffix -> %s, card names %s" % (got, named))

    # ---- and the answer must not depend on the order GitHub listed them ----
    #
    # This is the half a plain resolution check cannot see. With two .deb
    # assets the cards resolved correctly at 0.9.5 ONLY because GitHub happened
    # to list the Debian one first; drop the most-specific-first ordering and
    # every assertion above still passes. The page "looks perfect while doing
    # it" -- which is the sentence this whole file was written around.
    #
    # So resolve a second time against the REVERSED asset list and require the
    # same answers. An ordering-dependent result fails here and nowhere else.
    def resolve(asset_list):
        seen, out = set(), {}
        for os_key, fmt, match, named in sorted(cards, key=lambda c: -len(c[2] or "")):
            token = (match or fmt or "").lower()
            got = next((n for n in asset_list
                        if n not in seen and n.lower().endswith(token)), None)
            if got is not None:
                seen.add(got)
            out[(os_key, match or fmt)] = got
        return out

    forward, backward = resolve(assets), resolve(list(reversed(assets)))
    flipped = sorted("%s/%s: %s vs %s" % (k[0], k[1], forward[k], backward[k])
                     for k in forward if forward[k] != backward[k])
    check("resolution does not depend on the asset listing order", not flipped,
          "; ".join(flipped))

    if errors:
        print("\nFAILED: %s" % ", ".join(errors), file=sys.stderr)
        return 1
    print("\nall %d cards resolve to their own asset, in either listing order"
          % len(cards))
    return 0


if __name__ == "__main__":
    sys.exit(main())
