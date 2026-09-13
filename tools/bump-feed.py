#!/usr/bin/env python3
"""Point public/releases.json at a release GitHub has actually published.

    python3 tools/bump-feed.py            # newest release on GitHub
    python3 tools/bump-feed.py v0.9.5     # a specific tag
    python3 tools/bump-feed.py v0.9.5 -n  # print the diff, write nothing

Then rebuild and check:

    python3 tools/build-site.py && python3 tools/check.py
    python3 tools/check-assets.py

WHY THIS EXISTS. The README says editing `releases.json` by hand is the whole
release procedure, and for a version number it is. The filenames are the
problem: the Windows and macOS assets embed the release commit's SHORT SHA, so
"replace 0.9.4 with 0.9.5" leaves three cards naming files that do not exist,
and the page keeps looking perfect because the JavaScript pass quietly repairs
it for anyone running JavaScript. The reader without it gets a 404.

The second thing it handles is a package that is simply NOT THERE. macOS is
`allow_failure` in the release pipeline -- deliberately, so one sleeping Mac
cannot block a release -- and at 0.9.5 it was absent for an unrelated reason
(the bundle's artifact upload is refused by a 100 MB limit in front of the
GitLab host). A card for an asset GitHub never received is a dead download
button, so a package with no matching asset is DROPPED from the feed, and
`build-site.py` then omits that platform's block entirely.

It never invents a filename: every name written here came back from the
GitHub API. What it keeps from the existing feed is the human part -- the
label, the format badge, the install command's SHAPE and the match token --
because those are editorial and this script has no opinion about them.
"""
import argparse
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "public")
FEED = os.path.join(PUB, "releases.json")
REPO = "Mizerd/lightning"


def github_release(tag):
    url = ("https://api.github.com/repos/%s/releases/latest" % REPO if not tag
           else "https://api.github.com/repos/%s/releases/tags/%s" % (REPO, tag))
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as fh:
        return json.load(fh)


def asset_for(pkg, names):
    """The published asset this card names, by the same rule releases.js uses.

    `match` wins where it exists, because the format badge a reader sees is
    not always enough: two cards ship a ".zip" (the Windows portable and the
    macOS bundle) and matching on the badge alone hands both of them whichever
    .zip GitHub happened to list first.
    """
    suffix = (pkg.get("match") or pkg.get("format") or "").lower()
    if not suffix:
        return None
    for name in names:
        if name.lower().endswith(suffix):
            return name
    return None


def rewrite_install(command, old_file, new_file, old_version, new_version):
    """Swap the filename inside an install command, keeping its shape.

    The AppImage command deliberately GLOBS its suffix
    (`Lightning-0.9.5-x86_64.*pp[Ii]mage`) because a browser once saved the
    asset lower-cased; `bbcc525` records that, and records that widening the
    glob to `Lightning-*` is a defect because two versions in one directory
    expand to both and the OLDER becomes the command. So the substitution is
    on the version string when the literal filename is not present, which
    preserves whatever globbing the command already had.
    """
    if not command:
        return command
    if old_file and old_file in command:
        return command.replace(old_file, new_file)
    if old_version and old_version != new_version:
        return command.replace(old_version, new_version)
    return command


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?", default="",
                    help="release tag (default: newest on GitHub)")
    ap.add_argument("-n", "--dry-run", action="store_true")
    args = ap.parse_args()

    feed = json.load(open(FEED, encoding="utf-8"))
    rel = github_release(args.tag)
    tag = rel.get("tag_name", "")
    if not tag.startswith("v"):
        sys.exit("bump-feed: unexpected tag %r" % tag)
    version = tag[1:]
    names = [a["name"] for a in rel.get("assets", [])]
    if not names:
        sys.exit("bump-feed: %s has no assets" % tag)

    old_version = feed["version"]
    print("%s -> %s   (%d assets on GitHub)" % (old_version, version, len(names)))

    kept, dropped = [], []
    for pkg in feed["packages"]:
        name = asset_for(pkg, names)
        if not name:
            dropped.append("%s (%s)" % (pkg.get("format"), pkg.get("os")))
            continue
        old_file = pkg.get("file", "")
        pkg = dict(pkg)
        pkg["file"] = name
        pkg["install"] = rewrite_install(pkg.get("install", ""), old_file, name,
                                         old_version, version)
        if old_file != name:
            print("  %-10s %s -> %s" % (pkg.get("format", ""), old_file, name))
        kept.append(pkg)

    for d in dropped:
        print("  DROPPED  %s -- no asset in %s" % (d, tag))

    feed["version"] = version
    feed["packages"] = kept
    published = (rel.get("published_at") or "")[:10]
    if published:
        feed["released"] = published
        print("  released %s" % published)

    if args.dry_run:
        print("\n(dry run, nothing written)")
        return
    with open(FEED, "w", encoding="utf-8") as fh:
        json.dump(feed, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("\nwrote %s -- now run build-site.py, check.py and check-assets.py"
          % os.path.relpath(FEED, os.path.dirname(HERE)))


if __name__ == "__main__":
    main()
