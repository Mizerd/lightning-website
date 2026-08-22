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

    def asset_for(token):
        low = token.lower()
        for name in assets:
            if name.lower().endswith(low):
                return name
        return None

    for os_key, fmt, match, named in cards:
        token = match or fmt or ""
        got = asset_for(token)
        check("%s card (%s) resolves to one asset" % (os_key, token),
              got is not None, "no asset ends with %r" % token)
        if got is not None:
            # The card names a file too (the no-JavaScript path). If the suffix
            # pass and the baked filename disagree, one of the two is wrong and
            # a visitor sees a different download depending on whether their
            # JavaScript ran.
            check("%s card agrees with its own filename" % os_key,
                  got == named, "suffix -> %s, card names %s" % (got, named))

    if errors:
        print("\nFAILED: %s" % ", ".join(errors), file=sys.stderr)
        return 1
    print("\nall %d cards resolve to their own asset" % len(cards))
    return 0


if __name__ == "__main__":
    sys.exit(main())
