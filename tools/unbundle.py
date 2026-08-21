#!/usr/bin/env python3
"""Turn the Claude artifact bundle (Lightning.html) into a plain static site.

The artifact ships as one 2.7 MB HTML file: a base64 manifest of 24 assets that
JavaScript unpacks into blob: URLs at runtime, then renders through React 18 and
a proprietary `x-dc` runtime. That is ~280 KB of JavaScript doing 12 string
substitutions, two list loops and 39 hover styles -- and it renders nothing at
all without JavaScript, which is the wrong trade for a public project site.

This script does that work once, ahead of time:

  * writes every bundled asset out as a real file under public/
  * hoists <helmet> into <head> and drops the runtime <script> tags
  * expands the <sc-for> loops from releases.json
  * substitutes the {{ moustache }} bindings
  * rewrites style-hover="..." attributes into real CSS :hover rules

The output under public/ is the deployed site. Re-run this only if you get a
fresh artifact from Claude; day-to-day edits go to public/index.html directly.

Usage:  python3 tools/unbundle.py [path/to/Lightning.html]
"""

import base64
import gzip
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "artifact", "Lightning.html")
OUT = os.path.join(ROOT, "public")

SITE_URL = "https://www.lightning-matrix.org"

raw = open(SRC, encoding="utf-8").read()


def island(name):
    m = re.search(r'<script type="__bundler/%s">(.*?)\n?  </script>' % name, raw, re.S)
    return m.group(1) if m else None


manifest = json.loads(island("manifest"))
template = json.loads(island("template"))
ext_resources = json.loads(island("ext_resources") or "[]")


def payload(uuid):
    entry = manifest[uuid]
    data = base64.b64decode(entry["data"])
    return gzip.decompress(data) if entry.get("compressed") else data


# ---------------------------------------------------------------- asset names
# Screenshots are identified by the alt text they carry in the template, so the
# filenames survive a re-bundle that shuffles the uuids.
SHOT_NAMES = {
    "GIF picker open over the composer": "screenshot-rooms-and-gifs.png",
    "thread panel open beside": "screenshot-threads.png",
    "emoji picker open over the composer": "screenshot-emoji.png",
    "poll with four options": "screenshot-polls.png",
}

names = {}          # uuid -> path relative to public/
dropped = set()     # uuids deliberately not written out (the dead JS runtime)

# The React UMD builds and the x-dc runtime exist only to render <x-dc>. The
# static page has no <x-dc>, so none of them ship.
runtime_uuids = {e["uuid"] for e in ext_resources if e["id"].startswith("https://unpkg.com/")}
runtime_uuids |= {u for u, e in manifest.items()
                  if e["mime"] == "text/javascript" and u not in runtime_uuids}
dropped |= runtime_uuids

releases_uuid = next((e["uuid"] for e in ext_resources if e["id"] == "releasesFeed"), None)
_live = os.path.join(OUT, "releases.json")
if os.path.exists(_live):
    releases = json.load(open(_live, encoding="utf-8"))
elif releases_uuid:
    releases = json.loads(payload(releases_uuid))
else:
    releases = {}

# --------------------------------------------------------------------- fonts
# Each @font-face block is preceded by a /* subset */ comment. These are
# variable fonts: Google Fonts emits one @font-face per weight (400/500/700)
# but all three point at the SAME woff2, so 54 blocks resolve to 15 files.
# The weight therefore has no place in the filename -- family + subset is the
# real identity.
font_css = re.search(r"<style>(.*?)</style>", template, re.S).group(1)
face_re = re.compile(
    r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{(.*?)\}", re.S)
for subset, block in face_re.findall(font_css):
    u = re.search(r'url\("([0-9a-f-]{36})"\)', block)
    fam = re.search(r"font-family:\s*'([^']+)'", block)
    if not (u and fam):
        continue
    slug = fam.group(1).lower().replace(" ", "-")
    # Fonts live at /fonts/, NOT under /assets/. Cloudflare's _headers applies
    # EVERY matching rule and merges the results, so a nested /assets/fonts/*
    # rule under an /assets/* rule emits two Cache-Control values in one
    # header and the browser takes the first -- silently capping the fonts at
    # the shorter age. Disjoint prefixes are the only reliable fix.
    names[u.group(1)] = "fonts/%s-%s.woff2" % (slug, subset)

# ------------------------------------------------------- everything remaining
for uuid, entry in manifest.items():
    if uuid in names or uuid in dropped:
        continue
    if uuid == releases_uuid:
        names[uuid] = "releases.json"
    elif entry["mime"] == "image/svg+xml":
        names[uuid] = "assets/lightning-mark.svg"
    elif entry["mime"] == "image/png":
        alt = re.search(r'<img src="%s"[^>]*alt="([^"]*)"' % uuid, template)
        alt = alt.group(1) if alt else ""
        names[uuid] = "assets/" + next(
            (v for k, v in SHOT_NAMES.items() if k in alt), "image-%s.png" % uuid[:8])
    else:
        names[uuid] = "assets/%s.bin" % uuid[:8]

for uuid, rel in names.items():
    dest = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    # releases.json is maintained by hand for every release -- extracting it
    # over the top of a newer edit would silently roll the site back.
    if rel == "releases.json" and os.path.exists(dest):
        print("  keep   %-52s %8s     (existing, not overwritten)" % (rel, ""))
        continue
    with open(dest, "wb") as fh:
        fh.write(payload(uuid))
    print("  asset  %-52s %8d B" % (rel, os.path.getsize(dest)))
for uuid in sorted(dropped):
    print("  drop   %-52s %8d B  (runtime, not needed by the static page)"
          % (uuid[:8] + " " + manifest[uuid]["mime"], len(payload(uuid))))

# ------------------------------------------------------------ rewrite the doc
doc = template

# uuid -> real relative path, everywhere it appears (fonts, <img>, favicon).
for uuid, rel in names.items():
    doc = doc.replace(uuid, "/" + rel)

# The runtime's own <script src="..."> survived as a dangling path; drop it
# along with the x-dc logic script.
doc = re.sub(r'<script src="[^"]*"></script>\s*', "", doc)
doc = re.sub(r'<script type="text/x-dc".*?</script>', "", doc, flags=re.S)

# ------------------------------------------------------------------ moustache
donate_url = releases.get("donate_url", "")
values = {
    "version": releases.get("version", ""),
    "released": releases.get("released", ""),
    "releasesUrl": releases.get("releases_url", ""),
    "mirrorUrl": releases.get("mirror_url", ""),
    "donateUrl": donate_url,
}


def expand(fragment, ctx):
    """Substitute {{ bindings }}, leaving a hook releases.js can re-target.

    Every value is wrapped in <span data-lg-bind="key">, which is what keeps
    the artifact's original design intact: drop a new releases.json in and the
    version, date and package list update themselves with no HTML edit. The
    difference from the artifact is that the page is already correct before
    that fetch resolves, instead of being blank until it does.
    """
    def sub(m):
        key = m.group(1).strip()
        if key not in ctx:
            raise KeyError("unbound binding {{ %s }}" % key)
        return '<span data-lg-bind="%s">%s</span>' % (
            key, html.escape(str(ctx[key]), quote=False))
    return re.sub(r"\{\{([^}]*)\}\}", sub, fragment)


# <sc-for list="{{ linux }}" as="pkg"> ... </sc-for>  ->  one copy per package
def unroll(m):
    listname, asname, body = m.group(1).strip(), m.group(2), m.group(3)
    os_key = {"linux": "linux", "windows": "windows"}[listname]
    pkgs = [p for p in releases.get("packages", []) if p.get("os") == os_key]
    out = []
    for pkg in pkgs:
        ctx = {"%s.%s" % (asname, k): v for k, v in pkg.items()}
        card = expand(body, ctx)
        # Tag the card's root element; releases.js clones card zero as its
        # prototype when a fetched feed brings a different package set.
        card = card.replace("<div", '<div data-lg-pkg="%s"' % os_key, 1)
        out.append(card)
    return "".join(out)


doc = re.sub(
    r'<sc-for list="\{\{([^}]*)\}\}" as="(\w+)"[^>]*>(.*?)</sc-for>',
    unroll, doc, flags=re.S)
# The Donate button has no real destination yet. Per the maintainer's call the
# markup stays put -- hidden, with href neutralised so it cannot be clicked
# through to Liberapay's homepage. Set "donate_url" in releases.json and it
# unhides itself (statically here on the next build, and at runtime via
# releases.js for a site that is already deployed).
if not donate_url:
    doc = doc.replace(
        '<a href="{{ donateUrl }}"',
        '<a data-lg-href="donateUrl" hidden href="#"', 1)
else:
    doc = doc.replace(
        '<a href="{{ donateUrl }}"',
        '<a data-lg-href="donateUrl" href="%s"' % html.escape(donate_url, quote=True), 1)

# The two release links live in href="..." where a <span> wrapper is invalid,
# so the anchor carries the binding name and the value goes in directly.
for _key in ("releasesUrl", "mirrorUrl"):
    doc = doc.replace(
        '<a href="{{ %s }}"' % _key,
        '<a data-lg-href="%s" href="%s"' % (_key, html.escape(values[_key], quote=True)), 1)

doc = expand(doc, values)

# ------------------------------------------------------- content corrections
# Fixes applied to the artifact's markup, re-applied on every rebuild.

# 1. Downloads come from GitHub, not GitLab. releases.json already points the
#    prominent (blue) button at the GitHub release assets and the secondary one
#    at GitLab; these are the labels that go with that swap. GitLab remains the
#    canonical source repository -- only the download path moved.
_labels = [(">Releases (GitLab)<", ">Releases (GitHub)<"),
           (">GitHub mirror<", ">Releases (GitLab)<")]
for _before, _after in _labels:
    if _before not in doc:
        raise SystemExit("expected download label %r not found" % _before)
    doc = doc.replace(_before, _after, 1)

# 2. The "docs/build-and-test.md" link pointed at the repository root, so it
#    dropped you on the project home page instead of the document it names.
#    Point it at the file, on the mirror the other five doc links already use.
doc = doc.replace(
    '<a href="https://gitlab.smetonis.net/Mizerd/lightning">docs/build-and-test.md</a>',
    '<a href="https://github.com/Mizerd/lightning/blob/main/docs/build-and-test.md">'
    'docs/build-and-test.md</a>', 1)

# ------------------------------------------------------------- style-hover CSS
hover_rules = []


def hoverize(m):
    decls = m.group(1).strip().rstrip(";")
    cls = "hv-%d" % len(hover_rules)
    hover_rules.append(".%s:hover { %s; }" % (cls, decls))
    return ' class="%s"' % cls


doc = re.sub(r'\s+style-hover="([^"]*)"', hoverize, doc)
print("  hover  %d style-hover attributes -> CSS :hover rules" % len(hover_rules))

# --------------------------------------------------------------- head / body
helmet = re.search(r"<helmet>(.*?)</helmet>", doc, re.S).group(1)
doc = re.sub(r"<helmet>.*?</helmet>", "", doc, flags=re.S)

# Fonts are served from our own origin now, so the Google Fonts preconnects are
# dead weight that also leaks a hint to a third party.
helmet = re.sub(r'<link rel="preconnect"[^>]*>\s*', "", helmet)

body = re.search(r"<x-dc>(.*?)</x-dc>", doc, re.S).group(1)

extra_head = """
<link rel="canonical" href="{site}/">
<meta name="theme-color" content="#0c0f14">
<meta property="og:url" content="{site}/">
<meta property="og:site_name" content="Lightning">
<meta property="og:image" content="{site}/assets/screenshot-rooms-and-gifs.png">
<meta property="og:image:alt" content="Lightning's room timeline with the GIF picker open over the composer">
<meta name="twitter:card" content="summary_large_image">
<style>
/* The `hidden` attribute gets its display:none from the UA stylesheet, which
   an inline style="display: inline-block" outranks -- and every element on
   this page is styled inline. Without this rule, hiding anything (the Donate
   button, for one) silently does nothing. */
[hidden] {{ display: none !important; }}
{hover}
</style>
""".format(site=SITE_URL, hover="\n".join(hover_rules))

page = (
    "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
    + helmet.strip() + "\n" + extra_head.strip()
    + "\n<script src=\"/releases.js\" defer></script>\n"
    + "</head>\n<body>\n" + body.strip() + "\n</body>\n</html>\n"
)

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
    fh.write(page)
print("  page   %-52s %8d B" % ("index.html", len(page.encode())))
