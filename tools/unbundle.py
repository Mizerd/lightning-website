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


def asset_url(pkg):
    """Direct download URL for one package, from the releases.json template.

    The template carries ${version} and ${file} rather than a bare base URL
    because GitHub's asset layout (/releases/download/<tag>/<name>) is not
    GitLab's. Returns "" when either the template or the package's filename is
    missing, which hides that card's button instead of emitting a dead link.
    """
    tpl = releases.get("asset_url", "")
    if not tpl or not pkg.get("file"):
        return ""
    return (tpl.replace("${version}", str(releases.get("version", "")))
               .replace("${file}", pkg["file"]))


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

        # A real download button per package, pointing straight at the release
        # asset. The first </div> in the card closes the format+label header
        # row, so this lands at the end of that row; margin-left:auto pushes it
        # to the right edge. data-lg-dl lets releases.js re-point it.
        url = asset_url(pkg)
        button = (
            '<a class="dlbtn" data-lg-dl%s href="%s"%s>Download</a>'
            % ("" if url else " hidden",
               html.escape(url or "#", quote=True),
               ' aria-label="Download %s"' % html.escape(pkg["file"], quote=True)
               if pkg.get("file") else "")
        )
        card = card.replace("</div>", button + "</div>", 1)

        # Tag the card's root element. data-lg-pkg groups the column (and
        # releases.js clones card zero as its prototype when a fetched feed
        # brings a different package set); format and file let the /api/latest
        # pass match this card to a GitHub asset and rewrite the filename
        # inside its install command.
        card = card.replace(
            "<div",
            '<div data-lg-pkg="%s" data-lg-format="%s" data-lg-file="%s"'
            % (os_key,
               html.escape(pkg.get("format", ""), quote=True),
               html.escape(pkg.get("file", ""), quote=True)),
            1)
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

# 3. The verify box tells you to run sha256sum against SHA256SUMS but gave you
#    no way to get the file. Link it, from the same release as the packages.
_sha = releases.get("asset_url", "")
if _sha:
    _sha = (_sha.replace("${version}", str(releases.get("version", "")))
                .replace("${file}", "SHA256SUMS"))
    _needle = '<div style="font-size: 14.5px; font-weight: 600;">Verify your download</div>'
    if _needle not in doc:
        raise SystemExit("verify-box heading not found")
    doc = doc.replace(
        _needle,
        _needle + '<a class="dlbtn" data-lg-dl-sha href="%s" '
                  'style="margin-left: 0; margin-top: 12px; display: inline-block;">'
                  'Get SHA256SUMS</a>' % html.escape(_sha, quote=True), 1)

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
# ------------------------------------------------------------ responsive pass
# The artifact was laid out for a desktop viewport only: on a 390 px screen the
# document measured 719 px wide, so the whole page sat squeezed against the
# left edge with the rest requiring a horizontal scroll. Measured causes, in
# order of damage:
#
#   1. the nav's seven links in a nowrap flex row  -> 719 px, the widest thing
#      on the page and the reason the viewport blew out at all
#   2. grids of repeat(auto-fit, minmax(>=300px, 1fr)) -> a 420 px column
#      inside a 326 px container (screenshots, downloads, status)
#   3. the "why" rows' 88px + 1fr + 1.15fr three-column grid, which kept all
#      three columns and wrapped the prose to roughly one word per line
#   4. desktop type sizes (68 px hero, 42 px section heads) at phone width
#
# Every style on this page is inline, so a stylesheet can only win with
# !important. Rather than scatter !important through attribute selectors, the
# elements that need to move get a class here and the media query below does
# the rest -- greppable, and it survives a re-bundle.
TAG_RE = re.compile(r"<(nav|section|div|figure|a|h1|h2|h3)((?:[^<>\"]|\"[^\"]*\")*)>")


def add_class(markup, cls, want):
    """Add `cls` to every opening tag whose attributes satisfy want(attrs)."""
    hits = [0]

    def sub(m):
        tag, attrs = m.group(1), m.group(2)
        if not want(attrs):
            return m.group(0)
        hits[0] += 1
        # Merge rather than add a second class attribute: hoverize has already
        # given some of these elements a class="hv-N".
        if re.search(r'\bclass="', attrs):
            attrs = re.sub(r'\bclass="([^"]*)"',
                           lambda c: 'class="%s %s"' % (c.group(1), cls), attrs, count=1)
        else:
            attrs += ' class="%s"' % cls
        return "<%s%s>" % (tag, attrs)

    return TAG_RE.sub(sub, markup), hits[0]


_counts = {}


def _mark(cls, want):
    global doc
    doc, n = add_class(doc, cls, want)
    _counts[cls] = n


# The nav row itself, and the five section links that overflow it. The brand
# and the Download button stay visible at every width.
_mark("lg-nav", lambda a: "<nav" == "<nav" and "display: flex" in a and "gap: 28px" in a
      and "max-width: 1180px" in a and "padding: 14px 32px" in a)
_NAVLINKS = ("#different", "#screenshots", "#features", "#privacy",
             "gitlab.smetonis.net/Mizerd/lightning\"")
_mark("lg-navlink", lambda a: 'font-size: 14px; font-weight: 500; color: #93a0b1;' in a
      and any(h in a for h in _NAVLINKS))

# Section inner wrappers: 88px vertical / 32px horizontal is a lot of a phone.
_mark("lg-shell", lambda a: "padding: 88px 32px" in a)

# Grids whose minimum column is wider than a phone's content box.
_mark("lg-grid", lambda a: re.search(r"minmax\((?:3\d\d|4\d\d)px, 1fr\)", a) is not None)

# The three-column "why" rows.
_mark("lg-rows", lambda a: "88px minmax(0, 1fr) minmax(0, 1.15fr)" in a)

# The install-command boxes. white-space:pre gives each a max-content width of
# ~624px, and because grid and flex children default to min-width:auto that
# demand propagates up through every ancestor and inflates the whole download
# section. Tagged here so the media query can let them wrap instead.
_mark("lg-cmd", lambda a: "overflow-x: auto" in a and "white-space: pre" in a)

# The hero's version pill. At 11.5px the line runs ~319px, so on a 390px screen
# it breaks after "matrix-rust-sdk" and leaves "0.18" alone on a second line.
_mark("lg-pill", lambda a: "border-radius: 100px" in a and "inline-flex" in a
      and "JetBrains Mono" in a)

# Type scale, keyed off the desktop size so nothing is guessed.
for _cls, _px in (("lg-t1", "68px"), ("lg-t2", "42px"),
                  ("lg-t3", "34px"), ("lg-t4", "27px")):
    _mark(_cls, lambda a, _p=_px: ("font-size: %s;" % _p) in a)
_mark("lg-t4", lambda a: "font-size: 26px;" in a)

print("  resp   " + ", ".join("%s=%d" % (k, v) for k, v in _counts.items()))

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

/* Per-package download buttons. One shared class rather than the generated
   per-element hv-N classes, so eight identical rules do not ship. */
.dlbtn {{
  margin-left: auto;
  padding: 7px 13px;
  border-radius: 7px;
  border: 1px solid #35496a;
  background: #16202e;
  color: #9dbdf5;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  text-decoration: none;
  transition: background 0.25s ease, border-color 0.25s ease, color 0.25s ease;
}}
.dlbtn:hover {{ background: #1d2c40; border-color: #4a648f; color: #cfe0ff; }}
.dlbtn:focus-visible {{ outline: 2px solid #5590f5; outline-offset: 2px; }}

/* ---- phones and small tablets -------------------------------------------
   Overrides for the desktop-only inline styles. !important is unavoidable:
   an inline style beats any stylesheet rule without it. See the responsive
   pass in tools/unbundle.py for what each class is attached to. */
@media (max-width: 760px) {{
  /* The nav's seven links in a nowrap row were the widest element on the
     page (719px at a 390px viewport) and what forced the horizontal scroll.
     Brand + Download stay; the five in-page links go, since every one of
     them is reachable by scrolling and duplicated in the footer. */
  .lg-navlink {{ display: none !important; }}
  .lg-nav {{ gap: 12px !important; padding: 12px 18px !important; }}

  /* A shorter header needs a shorter anchor offset. */
  section[id] {{ scroll-margin-top: 108px !important; }}

  .lg-shell {{ padding: 52px 20px !important; }}

  /* One column, rather than a 420px column in a 326px box. */
  .lg-grid, .lg-rows {{ grid-template-columns: 1fr !important; }}
  /* The row number ("01") reads as a label above the heading once stacked. */
  .lg-rows {{ gap: 10px !important; }}

  /* Desktop type at phone width: 68px of hero is about four words a line. */
  .lg-t1 {{ font-size: 38px !important; line-height: 1.06 !important; }}
  .lg-t2 {{ font-size: 27px !important; }}
  .lg-t3 {{ font-size: 23px !important; }}
  .lg-t4 {{ font-size: 20px !important; }}

  /* Let a long command wrap inside its card instead of demanding 624px and
     forcing every ancestor wide. Wrapping beats a horizontal scroll inside a
     card you are already scrolling vertically. */
  .lg-cmd {{
    white-space: pre-wrap !important;
    overflow-x: visible !important;
    overflow-wrap: anywhere !important;
  }}

  /* Stop any remaining max-content demand from propagating up a grid. */
  .lg-grid > *, .lg-rows > * {{ min-width: 0 !important; }}

  pre, code {{ overflow-wrap: anywhere; }}

  /* Give the pill room for one line instead of orphaning the SDK version. */
  .lg-pill {{ font-size: 10.5px !important; gap: 7px !important; letter-spacing: 0.03em !important; }}

  /* One consistent full-width tap target per card. Without this the button
     sits inline after short labels (".msi") and on its own line after long
     ones, which reads as a mistake down a column of eight. */
  .dlbtn {{
    margin-left: 0 !important;
    flex-basis: 100% !important;
    text-align: center !important;
    padding: 10px 13px !important;
  }}
}}

/* Nothing on this page is allowed to widen the document. Every known cause is
   fixed above; this is the backstop so a future edit degrades into a clipped
   element rather than shoving the whole layout sideways again. */
html, body {{ overflow-x: clip; }}
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
