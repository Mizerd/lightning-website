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
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "artifact", "Lightning.html")
OUT = os.path.join(ROOT, "public")

SITE_URL = "https://www.lightning-matrix.org"
# The project's one public repository. Named here because the JSON-LD below
# has to point at the same place correction 1 rewrites every link to.
REPO_URL = "https://github.com/Mizerd/lightning"

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
names = {}          # uuid -> path relative to public/
dropped = set()     # uuids deliberately not written out

# The React UMD builds and the x-dc runtime exist only to render <x-dc>. The
# static page has no <x-dc>, so none of them ship.
runtime_uuids = {e["uuid"] for e in ext_resources if e["id"].startswith("https://unpkg.com/")}
runtime_uuids |= {u for u, e in manifest.items()
                  if e["mime"] == "text/javascript" and u not in runtime_uuids}
dropped |= runtime_uuids

# Nor do the artifact's own four screenshots. They are a snapshot of whatever
# the client looked like the day the artifact was made, and 0.8.0 replaced the
# last of them: none is on the page any more. The pictures the site does show
# are maintained as real files under public/assets and listed in _SHOTS
# (correction 12), which reads each one's true size off disk -- so a
# replacement is measured as it actually is, and a missing file fails the
# build rather than reserving the wrong shape for it.
dropped |= {u for u, e in manifest.items() if e["mime"] == "image/png"}

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
    else:
        names[uuid] = "assets/%s.bin" % uuid[:8]

for uuid, rel in names.items():
    dest = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    # releases.json is maintained by hand for every release -- extracting it
    # over the top of a newer edit would silently roll the site back.
    keep = rel == "releases.json"
    if keep and os.path.exists(dest):
        print("  keep   %-52s %8d B   (existing, not overwritten)"
              % (rel, os.path.getsize(dest)))
        continue
    with open(dest, "wb") as fh:
        fh.write(payload(uuid))
    print("  asset  %-52s %8d B" % (rel, os.path.getsize(dest)))
for uuid in sorted(dropped):
    print("  drop   %-52s %8d B  (not used by the static page)"
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
    "donateUrl": donate_url,
}


def asset_url(pkg):
    """Direct download URL for one package, from the releases.json template.

    The template carries ${version} and ${file} rather than a bare base URL
    because GitHub puts assets under /releases/download/<tag>/<name>, with the
    tag in the path. Returns "" when either the template or the package's
    filename is missing, which hides that card's button rather than emitting a
    dead link.
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
        # data-lg-match is the suffix the /api/latest pass matches on, for the
        # cards whose displayed format is ambiguous. Since 0.7.5 two packages
        # ship a ".zip" -- the Windows portable and the macOS bundle -- and
        # without this both cards would take whichever .zip GitHub listed
        # first. Emitted only where the feed asks for it.
        match = pkg.get("match", "")
        card = card.replace(
            "<div",
            '<div data-lg-pkg="%s" data-lg-format="%s"%s data-lg-file="%s"'
            % (os_key,
               html.escape(pkg.get("format", ""), quote=True),
               (' data-lg-match="%s"' % html.escape(match, quote=True)) if match else "",
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

# The release link lives in href="..." where a <span> wrapper is invalid, so
# the anchor carries the binding name and the value goes in directly.
doc = doc.replace(
    '<a href="{{ releasesUrl }}"',
    '<a data-lg-href="releasesUrl" href="%s"'
    % html.escape(values["releasesUrl"], quote=True), 1)

# The artifact had a second release button beside that one, pointing at the
# GitLab release list. It goes -- see correction 1 below for why -- and it has
# to go here, while its href is still the literal {{ mirrorUrl }}: expand()
# would turn that into a <span>, which no href pattern would match.
doc, _n = re.subn(r'\s*<a href="\{\{ mirrorUrl \}\}"[^>]*>.*?</a>', "",
                  doc, count=1, flags=re.S)
if _n != 1:
    raise SystemExit("secondary (mirror) release button not found")

doc = expand(doc, values)

# ------------------------------------------------------- content corrections
# Fixes applied to the artifact's markup, re-applied on every rebuild.

# 1. GitHub only. The artifact was written when the canonical repository and
#    the release list both lived on a self-hosted GitLab. The project points
#    people at GitHub for everything now, so nothing on the page may link to
#    GitLab or name it. Each rewrite below asserts its own needle and the
#    sweep at the end of the block asserts the result, so a reworded artifact
#    fails the build instead of quietly reintroducing a link.

# The secondary release button is already gone (above). Nothing takes its
# place: the repository is linked from the nav, the hero and the Contribute
# card, so another button would only repeat them. The Contribute card offered
# the two repositories side by side; the GitLab one goes the same way.
doc, _n = re.subn(
    r'\s*<a href="https://gitlab\.smetonis\.net/Mizerd/lightning"[^>]*>'
    r'GitLab \(canonical\)</a>', "", doc, count=1, flags=re.S)
if _n != 1:
    raise SystemExit("GitLab repository button not found")

# Labels and prose. The wording keeps every claim the artifact made that is
# still true -- the manifest, not the host, is what defines a release -- and
# drops only the sentences whose subject was the old host.
_edits = [
    (">Releases (GitLab)<", ">Releases (GitHub)<"),
    (">GitHub (mirror)<", ">Open on GitHub<"),
    (">GitLab decides what a release is<",
     ">The signed manifest decides what a release is<"),
    ("Downloads come from the GitHub mirror first, to keep the traffic off "
     "the project's own server, and fall back to GitLab. Lightning never "
     "calls the GitHub API",
     "Downloads come from GitHub, but Lightning never calls the GitHub API"),
    ("The mirror's URL is part of the signed manifest",
     "The download URL is part of the signed manifest"),
    ("Someone who took over the mirror could break your download.",
     "Someone who took over the download host could break your download."),
    ("in the room or in the tracker on the mirror.",
     "in the room or in the issue tracker on GitHub."),
    ("It's all public, under GPL-3.0-or-later. GitLab is the real repository. "
     "GitHub is an automatic read-only mirror, so pull requests opened there "
     "don't reach anyone.",
     "It's all public, under GPL-3.0-or-later. The code, the full release "
     "history and the build scripts are all on GitHub."),
]
for _before, _after in _edits:
    if _before not in doc:
        raise SystemExit("expected text %r not found" % _before)
    doc = doc.replace(_before, _after, 1)

# What is left is plain repository links: the nav's "Source" and the hero's
# "Read the source". Correction 2 below relies on this having already run.
doc = doc.replace("https://gitlab.smetonis.net/Mizerd/lightning",
                  "https://github.com/Mizerd/lightning")

if "gitlab" in doc.lower():
    raise SystemExit("a GitLab reference survived the rewrite")

# 2. Code signing. The artifact said the SignPath Foundation application had
#    not been made; it has, and it is queued. This is the one claim on the page
#    that can quietly become a lie, so it asserts its own needle.
# The same box told Windows users to check the download "against the
# checksum". Correction 7 moves the only checksum command on the page into
# the Linux column, because it is a Linux command -- so point Windows readers
# at where the file came from instead, which is what actually protects them.
_ck = ("If you've checked the download against the checksum, pick ")
if _ck not in doc:
    raise SystemExit("SmartScreen checksum sentence not found")
doc = doc.replace(_ck, "If you got the file from the release page above, pick ", 1)

_before = ("Signing through the SignPath Foundation is something we'd like to "
           "do, but we <strong style=\"color: #f0d6a0; font-weight: 600;\">"
           "haven't even applied yet</strong>, so no release is signed today.")
_after = ("We've applied to the SignPath Foundation and the "
          "<strong style=\"color: #f0d6a0; font-weight: 600;\">application is "
          "in progress</strong>, so no release is signed today.")
if _before not in doc:
    raise SystemExit("SignPath sentence not found")
doc = doc.replace(_before, _after, 1)

# 3. The alpha banner named a release series ("0.7.x"), which nothing keeps
#    current. Bind it to the version instead, so it follows a GitHub release
#    like every other version on the page.
#
#    It also ran to four lines on a phone -- roughly a sixth of the screen,
#    above the fold, on every scroll, because the bar is sticky. A second,
#    shorter wording carries the same three warnings in one clause; exactly
#    one of the two is visible at any width (see .lg-alpha-* in the CSS).
#    Both are in the markup rather than one being rewritten by script, so the
#    warning is right with JavaScript off.
#
#    expand() has already run, so these emit the expanded <span data-lg-bind>
#    form directly -- a {{ version }} left here would never be substituted.
_ver = '<span data-lg-bind="version">%s</span>' % html.escape(
    str(releases.get("version", "")))
_pill = ("<span style=\"display: inline-flex; align-items: center; gap: 8px; "
         "font-family: 'JetBrains Mono', monospace; font-size: 11px; "
         "font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; "
         "color: #e8a33d;\">")
if _pill not in doc:
    raise SystemExit("alpha pill not found")
doc = doc.replace(_pill, _pill[:-1] + ' class="lg-alpha-pill">', 1)

_before = ("<span style=\"max-width: 780px;\">Lightning is in alpha (0.7.x). "
           "It works")
if _before not in doc:
    raise SystemExit("alpha banner sentence not found")
doc = doc.replace(
    _before,
    "<span style=\"max-width: 780px;\" class=\"lg-alpha-full\">Lightning is in "
    "alpha (" + _ver + "). It works", 1)

#    The third warning was "calls don't work yet". 0.8.0 made that false, and
#    a sticky bar is the worst place on the page to leave a stale claim -- it
#    is above the fold on every scroll. The two that are still true stay.
_bold = "color: #fbeccd; font-weight: 700;"
_calls_clause = ", and calls don't work yet.</span>"
if doc.count(_calls_clause) != 1:
    raise SystemExit("alpha banner calls clause not found")
# Two items left where there were three, so the serial comma before the
# packages has to become an "and" or the sentence reads as a splice.
_serial = "</strong>, the packages <strong"
if doc.count(_serial) != 1:
    raise SystemExit("alpha banner serial comma not found")
doc = doc.replace(_serial, "</strong> and the packages <strong", 1)
doc = doc.replace(
    _calls_clause,
    ".</span>"
    "<span class=\"lg-alpha-brief\">Alpha " + _ver + " \u2014 "
    "<strong style=\"%s\">no security audit</strong> and "
    "<strong style=\"%s\">no code signing</strong>.</span>"
    % (_bold, _bold), 1)

# 6. macOS. The artifact had a one-line card saying a macOS build existed but
#    would not be published until it could be signed. That is no longer the
#    plan -- it ships unsigned when it ships -- so the small card goes and a
#    real block takes its place, below the Linux and Windows columns.
#
#    Since 0.7.5 there IS a build, so the block carries a real package card
#    with os "macos" from releases.json, and releases.js and /api/latest keep
#    it current like any other. The Gatekeeper walkthrough around it stays
#    static copy: it is instruction, not release data.
_mac_card = (
    '        <div style="padding: 22px; border: 1px solid #1e2631; '
    'border-radius: 11px; background: #10151c;">\n'
    '          <div style="font-size: 15px; font-weight: 600;">macOS</div>\n'
    '          <p style="margin-top: 9px; font-size: 14px; line-height: 1.6; '
    "color: #8d99a8;\">Not supported yet. There's a macOS build in the "
    "pipeline, but it won't be published until it can be signed.</p>\n"
    '        </div>\n')
if _mac_card not in doc:
    raise SystemExit("macOS placeholder card not found")
doc = doc.replace(_mac_card, "", 1)

# The one real package card inside the macOS block. Built from releases.json
# like every other card, rather than typed out here, so a release only ever
# edits the feed. Absent from the feed, the block still renders -- with the
# walkthrough and no download, which is what "no macOS build" should look like.
def _macos_card():
    pkg = next((p for p in releases.get("packages", [])
                if p.get("os") == "macos"), None)
    if not pkg:
        return ""
    e = lambda v: html.escape(str(v), quote=True)
    match = pkg.get("match", "")
    return (
        '        <div data-lg-pkg="macos" data-lg-format="%s"%s '
        'data-lg-file="%s" style="margin-top: 16px; padding: 18px 20px; '
        'border: 1px solid #1e2631; border-radius: 11px; background: '
        '#10151c;" class="lg-card">\n'
        '          <div style="display: flex; flex-wrap: wrap; align-items: '
        'center; gap: 10px;">\n'
        '            <span style="padding: 3px 8px; border-radius: 5px; '
        "background: #1c2836; font-family: 'JetBrains Mono', monospace; "
        'font-size: 11.5px; font-weight: 700; color: #9dbdf5;">'
        '<span data-lg-bind="pkg.format">%s</span></span>\n'
        '            <span style="font-size: 14px; color: #b6c2d0;">'
        '<span data-lg-bind="pkg.label">%s</span></span>\n'
        '            <a class="dlbtn" data-lg-dl href="%s" '
        'aria-label="Download %s">Download</a></div>\n'
        '          <div style="margin-top: 13px; padding: 11px 13px; '
        'border-radius: 7px; background: #070a0e; border: 1px solid #1a212b; '
        "font-family: 'JetBrains Mono', monospace; font-size: 12px; "
        'line-height: 1.5; color: #a8d5bd; overflow-x: auto; '
        'white-space: pre;" class="lg-cmd">'
        '<span data-lg-bind="pkg.install">%s</span></div>\n'
        '        </div>\n'
    ) % (e(pkg.get("format", "")),
         (' data-lg-match="%s"' % e(match)) if match else "",
         e(pkg.get("file", "")), e(pkg.get("format", "")),
         e(pkg.get("label", "")), e(asset_url(pkg)), e(pkg.get("file", "")),
         e(pkg.get("install", "")))


_CARD = ("padding: 22px; border: 1px solid #1e2631; border-radius: 11px; "
         "background: #10151c;")
_BODY = "margin-top: 9px; font-size: 14px; line-height: 1.6; color: #8d99a8;"
_STEP = ("font-family: 'JetBrains Mono', monospace; font-size: 11.5px; "
         "font-weight: 700; color: #5f88cc;")

_macos = (
    '      <div style="margin-top: 24px; padding: 26px; border: 1px solid '
    '#1e2631; border-radius: 13px; background: linear-gradient(180deg, '
    '#141a23, #10151c);">\n'
    '        <div style="display: flex; flex-wrap: wrap; align-items: '
    'baseline; gap: 12px;">\n'
    '          <h3 style="font-size: 20px; font-weight: 600;">macOS</h3>\n'
    '          <span style="padding: 3px 9px; border-radius: 5px; background: '
    "#1c2836; font-family: 'JetBrains Mono', monospace; font-size: 11.5px; "
    'font-weight: 700; letter-spacing: 0.04em; color: #9dbdf5;">Apple Silicon'
    '</span>\n'
    '        </div>\n'
    '        <p style="max-width: 780px; %s">Two limits '
    'before you download, because neither is a choice -- both come from the '
    'Qt build the app links: it runs on <strong style="color: #c9d5e4; '
    'font-weight: 600;">Apple Silicon only</strong> (M1 and later, no Intel '
    'build exists), and it needs <strong style="color: #c9d5e4; font-weight: '
    '600;">macOS 26 or newer</strong>. On macOS 15 or earlier it will not '
    'launch at all.</p>\n'
    '\n'
    "%s"
    '\n'
    '        <div style="margin-top: 18px; padding: 18px 20px; border: 1px '
    'solid #4a3814; border-radius: 11px; background: #1c1609;">\n'
    '          <div style="font-size: 14.5px; font-weight: 600; color: '
    '#f0d6a0;">It is not signed or notarised</div>\n'
    '          <p style="margin-top: 9px; font-size: 14px; line-height: 1.6; '
    'color: #c4a874;">Notarising needs a paid Apple Developer account, and '
    'there is no company behind Lightning to hold one. macOS will refuse to '
    'open the app the first time and say it cannot check it for malicious '
    'software. That is expected. The three steps below clear it for good, '
    'and none of them needs the Terminal &mdash; but because you are the one '
    'vouching for the app, '
    '<strong style="color: #f0d6a0; font-weight: 600;">download it only from '
    'the GitHub releases page</strong> linked above.</p>\n'
    '        </div>\n'
    '\n'
    '        <div style="display: grid; grid-template-columns: repeat('
    'auto-fit, minmax(300px, 1fr)); gap: 16px; margin-top: 16px;">\n'
    '          <div style="%s">\n'
    '            <div style="%s">STEP 1</div>\n'
    '            <div style="margin-top: 8px; font-size: 15px; font-weight: '
    '600;">Try to open it, and let it fail</div>\n'
    '            <p style="%s">Drag Lightning into your Applications folder, '
    'then double-click it. macOS blocks it and offers you '
    '<em style="font-style: normal; color: #c9d5e4;">Done</em> or '
    '<em style="font-style: normal; color: #c9d5e4;">Move to Bin</em> &mdash; '
    'choose <em style="font-style: normal; color: #c9d5e4;">Done</em>. This '
    'step is not optional: the button in step 2 only appears once macOS has '
    'blocked the app at least once.</p>\n'
    '          </div>\n'
    '          <div style="%s">\n'
    '            <div style="%s">STEP 2</div>\n'
    '            <div style="margin-top: 8px; font-size: 15px; font-weight: '
    '600;">Click Open Anyway</div>\n'
    '            <p style="%s">Go to '
    '<em style="font-style: normal; color: #c9d5e4;">Apple menu &rarr; System '
    'Settings &rarr; Privacy &amp; Security</em> and scroll down to the '
    '<em style="font-style: normal; color: #c9d5e4;">Security</em> section. '
    'A line saying Lightning was blocked is waiting there with an '
    '<em style="font-style: normal; color: #c9d5e4;">Open Anyway</em> button '
    'next to it. Click it and confirm with Touch ID or your login '
    'password.</p>\n'
    '          </div>\n'
    '          <div style="%s">\n'
    '            <div style="%s">STEP 3</div>\n'
    '            <div style="margin-top: 8px; font-size: 15px; font-weight: '
    '600;">Confirm once, and never again</div>\n'
    '            <p style="%s">One last dialog asks whether you are sure. '
    'Click <em style="font-style: normal; color: #c9d5e4;">Open</em>. '
    'Lightning starts, and from then on it opens by double-click like any '
    'other app &mdash; you only do this the first time, and again after an '
    'update replaces the app.</p>\n'
    '          </div>\n'
    '        </div>\n'
    '\n'
    '        <p style="max-width: 780px; margin-top: 14px; font-size: 13.5px; '
    'line-height: 1.55; color: #7d8b9c;">On macOS 14 and earlier there was a '
    'shortcut -- Control-click the app, choose '
    '<em style="font-style: normal; color: #9fadbd;">Open</em> -- but macOS 15 '
    'removed it and this build needs macOS 26 anyway, so the route above is '
    'the one that works.</p>\n'
    '        <p style="max-width: 780px; margin-top: 10px; font-size: 13.5px; '
    'line-height: 1.55; color: #7d8b9c;">Three more things about the macOS '
    'build. It <strong style="color: #9fadbd; font-weight: 600;">does not '
    'update itself</strong>: Lightning will tell you a new version exists, '
    'but installing it means downloading the next file from this page. '
    '<strong style="color: #9fadbd; font-weight: 600;">Calls on macOS are '
    'untested</strong> -- the package carries the media engine and reports '
    'that it loaded, but nobody has placed a call from it. And '
    '<strong style="color: #9fadbd; font-weight: 600;">nobody has clicked '
    'through the app on a Mac</strong> at all -- the build is checked '
    'automatically, not used. If something is broken there, the release page '
    'is where to say so.</p>\n'
    '      </div>\n'
    '\n') % (_BODY, _macos_card(), _CARD, _STEP, _BODY, _CARD, _STEP, _BODY,
             _CARD, _STEP, _BODY)

_after_cols = ('      <div style="display: grid; grid-template-columns: '
               'repeat(auto-fit, minmax(260px, 1fr)); gap: 20px; '
               'margin-top: 32px;">\n')
if _after_cols not in doc:
    raise SystemExit("trailing download-notes grid not found")
doc = doc.replace(_after_cols, _macos + _after_cols, 1)

# 4. The "docs/build-and-test.md" link pointed at the repository root, so it
#    dropped you on the project home page instead of the document it names.
#    Point it at the file, in the same repository the other five doc links
#    already use. The bare repository URL here is what correction 1 left
#    behind; this must run after that sweep, not before it.
doc = doc.replace(
    '<a href="https://github.com/Mizerd/lightning">docs/build-and-test.md</a>',
    '<a href="https://github.com/Mizerd/lightning/blob/main/docs/build-and-test.md">'
    'docs/build-and-test.md</a>', 1)

# 5. The verify box tells you to run sha256sum against SHA256SUMS but gave you
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

# 7. `sha256sum` is a Linux command, and it was sitting in the Windows column
#    -- the one place it cannot be run. Windows and macOS users get no
#    terminal instructions at all now, so the verification card moves to the
#    Linux column, and what stays behind is the part that was always about
#    Windows: what the installers touch, and where to download from.
#
#    This runs after correction 5, so the "Get SHA256SUMS" button is already
#    inside the card and travels with it.
_vhead = '<div style="font-size: 14.5px; font-weight: 600;">Verify your download</div>'
if _vhead not in doc:
    raise SystemExit("verify card not found")
_vi = doc.index(_vhead)
_vstart = doc.rindex("<div ", 0, _vi)

# Walk to the matching close so the card can be moved whole.
_depth, _vend = 0, None
for _m in re.finditer(r"<div\b|</div>", doc[_vstart:]):
    _depth += 1 if _m.group(0) == "<div" else -1
    if _depth == 0:
        _vend = _vstart + _m.end()
        break
if _vend is None:
    raise SystemExit("verify card is unbalanced")
_card_html = doc[_vstart:_vend]

# The trailing paragraph is a Windows scope note, not verification. Split it
# off and leave it where it is.
_wp = re.search(r'<p style="[^"]*">All three Windows formats.*?</p>', _card_html, re.S)
if not _wp:
    raise SystemExit("Windows scope paragraph not found")
_verify_card = _card_html.replace(_wp.group(0), "").replace("\n\n", "\n")

_windows_card = (
    '<div style="margin-top: 16px; padding: 20px; border: 1px solid #1e2631; '
    'border-radius: 11px; background: #10151c;">\n'
    '            <div style="font-size: 14.5px; font-weight: 600;">What the '
    'installers touch</div>\n'
    '            ' + _wp.group(0) + '\n'
    '            <p style="margin-top: 12px; font-size: 13.5px; '
    'line-height: 1.55; color: #8d99a8;">Windows has no way to check a '
    'download against a checksum without a command prompt, so the thing that '
    'protects you here is where you get the file: use the release page linked '
    'above, and nothing that mirrors it.</p>\n'
    '          </div>')
doc = doc[:_vstart] + _windows_card + doc[_vend:]

# Drop it in at the end of the Linux column, before the column closes.
_lin_end = ('        </div>\n\n        <div>\n          <div style="display: '
            'flex; align-items: baseline; gap: 12px;">\n            '
            '<h3 style="font-size: 20px; font-weight: 600;">Windows</h3>')
if _lin_end not in doc:
    raise SystemExit("Linux/Windows column boundary not found")
doc = doc.replace(_lin_end, "          " + _verify_card + "\n" + _lin_end, 1)

# 8. The brand was missing from the page it belongs to. "Lightning" appeared
#    once, at 18px in the nav, and the hero opened on "Everything other Matrix
#    clients fake." -- a claim from a product that had not introduced itself.
#    The logo mark existed only as a 26px nav icon and a 14px chip.
#
#    So: a real lockup at the top of the hero, mark and wordmark at a size
#    that reads as a brand, with the one-line description that was already in
#    <title> but nowhere on the page. The h1 keeps its job as the pitch,
#    directly under a name that now means something.
_hero = ('<div style="position: relative; max-width: 1180px; margin: 0 auto; '
         'padding: 96px 32px 88px;">\n')
if _hero not in doc:
    raise SystemExit("hero content wrapper not found")

_lockup = (
    '      <div style="display: flex; align-items: center; gap: 22px; '
    'margin-bottom: 34px;" class="lg-brand">\n'
    '        <img src="/assets/lightning-mark.svg" alt="" width="88" '
    'height="88" style="display: block; flex: none;" class="lg-brandmark">\n'
    '        <div>\n'
    '          <div style="font-family: \'Space Grotesk\', sans-serif; '
    'font-size: 62px; line-height: 1; font-weight: 700; letter-spacing: '
    '-0.025em; color: #f2f6fb;" class="lg-brandname">Lightning</div>\n'
    '          <div style="margin-top: 10px; font-size: 17px; font-weight: '
    '500; color: #8d99a8;" class="lg-brandsub">A native Matrix client for '
    'Linux, Windows and macOS</div>\n'
    '        </div>\n'
    '      </div>\n')
doc = doc.replace(_hero, _hero + _lockup, 1)

# 9. The architecture diagram was laid out by hand for one width: each layer
#    carried literal <br> tags and runs of &nbsp; to indent its continuation
#    lines. On a phone those breaks land in the wrong places and the natural
#    wrapping adds its own, so some lines are indented and some are flush
#    left, and the vertical connectors stop lining up with anything.
#
#    Replace the manual breaks with a hanging indent, which produces the same
#    shape at any width: the first line starts at the margin and every
#    continuation line is indented under it. Nothing is hard-coded to a
#    column count, so it reflows instead of breaking.
_arch_box = ('<div style="margin-top: 16px; padding: 20px; border: 1px solid '
             '#1e2631; border-radius: 10px; background: #0a0d12; font-family: '
             "'JetBrains Mono', monospace; font-size: 12px; line-height: 1.85; "
             'color: #8d99a8; overflow-x: auto;">')
if _arch_box not in doc:
    raise SystemExit("architecture diagram not found")

_ai = doc.index(_arch_box)
_depth, _aend = 0, None
for _m in re.finditer(r"<div\b|</div>", doc[_ai:]):
    _depth += 1 if _m.group(0) == "<div" else -1
    if _depth == 0:
        _aend = _ai + _m.end()
        break
if _aend is None:
    raise SystemExit("architecture diagram is unbalanced")
_arch = doc[_ai:_aend]

# The artifact left this one layer unfinished -- every other line describes
# what it does, this one trailed off mid-sentence.
_arch = _arch.replace("FFI to&hellip;", "FFI between C++ and the SDK")
_arch = _arch.replace("FFI to…", "FFI between C++ and the SDK")

# Drop the hand-placed breaks and indents.
_arch = re.sub(r"<br>(?:&nbsp;)*", " ", _arch)
_arch = re.sub(r"(?:&nbsp;)+", " ", _arch)
_arch = re.sub(r"  +", " ", _arch)

# Hanging indent on the layer rows, so a wrapped description sits under the
# description rather than under the layer name. The connector rows are left
# alone -- they are one character wide.
_arch = _arch.replace(
    "<div><span", '<div style="padding-left: 7ch; text-indent: -7ch;" '
                  'class="lg-archrow"><span')
# Nothing overflows once it wraps, so the scrollbar goes with the breaks.
_arch = _arch.replace(" overflow-x: auto;\">", '" class="lg-arch">', 1)
doc = doc[:_ai] + _arch + doc[_aend:]

# 10. The Matrix room address is one unbroken token, so at 390px it ran 15px
#     past the card that holds it. Tag it so mobile can break it.
_room = '<a href="https://matrix.to/#/%23lightning%3Amatrix.smetonis.net"'
if _room not in doc:
    raise SystemExit("Matrix room link not found")
doc = doc.replace(_room, _room + ' class="lg-room"', 1)

# 11. Copy buttons on the Linux install commands. Only Linux: the Windows
#     boxes say "double-click ..." and "run the installer", which are not
#     commands, and the macOS block has none at all.
#
#     The button is a sibling of the command box, not a child, so reading the
#     box's textContent gives the command and nothing else. It ships `hidden`
#     and releases.js reveals it, so a reader without JavaScript is never
#     shown a button that cannot work. Clicks are handled by delegation --
#     releases.js rebuilds these cards with cloneNode, which does not copy
#     event listeners, so a per-button listener would die on every clone.
_lin_i = doc.index(">Linux</h3>")
_win_i = doc.index(">Windows</h3>")
_col = doc[_lin_i:_win_i]

_BTN = ("flex: none; padding: 6px 10px; border-radius: 6px; "
        "border: 1px solid #24303f; background: #10161e; color: #9fb0c4; "
        "font-family: 'JetBrains Mono', monospace; font-size: 10.5px; "
        "font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; "
        "line-height: 1.4; cursor: pointer;")

def _addcopy(m):
    style, body = m.group(1), m.group(2)
    # The button is a flex sibling, not an overlay. Absolute positioning put
    # it on top of the box, and reserving room with padding-right does not
    # help: the box scrolls (white-space: pre, overflow-x: auto), so that
    # padding sits at the end of the scrollable content rather than at the
    # right edge of what you can see. A long command -- the AppImage one --
    # ran straight under the button at scroll position zero.
    #
    # The box's own top margin moves to the row, or the button would sit that
    # much higher than the box it belongs to.
    _mt = re.match(r"margin-top: [\d.]+px;\s*", style)
    row_margin = _mt.group(0) if _mt else ""
    box_style = style[_mt.end():] if _mt else style

    box = ('<div style="%s flex: 1 1 240px; min-width: 0;" data-lg-copy>%s'
           '</div>' % (box_style, body))
    # flex-wrap lets the button drop to its own line rather than squeeze the
    # command when there is no room for both.
    return ('<div style="%s display: flex; flex-wrap: wrap; '
            'align-items: center; gap: 8px;">%s'
            '<button type="button" data-lg-copybtn hidden class="lg-copybtn" '
            'style="%s">Copy</button></div>' % (row_margin, box, _BTN))

_col, _n = re.subn(
    r'<div style="([^"]*white-space: pre;)">((?:(?!</?div\b).)*)</div>',
    _addcopy, _col, flags=re.S)
if _n != 6:
    raise SystemExit("expected 6 Linux command boxes, wrapped %d" % _n)
doc = doc[:_lin_i] + _col + doc[_win_i:]

# 12. The screenshots: the set the page shows, sized and openable.
#
#     The grid is rebuilt from _SHOTS rather than patched in place. The
#     artifact's own four pictures are several releases stale and not one of
#     them is on the page any anymore -- they are not even written out, see
#     the extraction pass above -- and patching four fixed slots is what
#     produced the state 0.8.0 inherited: a file called screenshot-threads.png
#     holding a picture of the theme editor, under a caption for a GIF picker
#     that was not in the shot. _SHOTS is now the one place a refresh touches:
#     drop the PNG into public/assets, name it here, write its caption.
#
#     width/height are read from each file's IHDR rather than typed in. The
#     images are loading="lazy", so without them the box is zero pixels tall
#     until the file arrives -- the caption sits under nothing and the grid
#     jumps as they land -- and a typed-in number would reserve the WRONG
#     shape after a re-export, which is worse than reserving none at all.
#
#     Each is wrapped in a <button> so releases.js can open it full screen.
#     A button rather than a click handler on the <img>: that way it is in the
#     tab order, activates on Enter and Space, and is announced as something
#     you can press. All three are free with a button and all three have to be
#     rebuilt by hand without one.
_SHOTS = [
    # file, alt, caption lead, caption body
    ("screenshot-call.png",
     "A four-person call at the top of a room: participant tiles, the call "
     "controls, and the room's timeline underneath",
     "Calls.",
     "A group call inside the room — camera, screen sharing, raised "
     "hands and per-person volume, talking to Element Call."),
    ("screenshot-channels.png",
     "The Channels layout: a Spaces rail, a Space's own room list, and the "
     "Space's front page listing the rooms in it",
     "Channels.",
     "The other conversation column: a Spaces rail, and one view per Space "
     "holding its rooms in the order the Space itself sets."),
    ("screenshot-timeline.png",
     "A room timeline with replies, reactions, an image and a typing "
     "indicator, beside the conversation list",
     "Rooms and messages.",
     "Replies, reactions, images and typing indicators, next to the "
     "conversation list."),
    ("screenshot-thread-panel.png",
     "A thread panel open beside the main timeline, with a thread summary "
     "card in the room",
     "Threads.",
     "Their own panel next to the room, with summary cards in the timeline."),
    ("screenshot-emoji-and-polls.png",
     "The emoji picker open over the composer, above a poll with four "
     "options and live vote counts",
     "Emoji and polls.",
     "Categories, search and a preview, over a poll counting votes live."),
    ("screenshot-theme-editor.png",
     "The theme editor: a live sample window, the list of colour roles, and "
     "a colour picker",
     "Your own theme.",
     "Click any part of the sample window to recolour it, then share the "
     "result as text."),
]


def _png_size(name):
    """(width, height) from a PNG's IHDR, which is always the first chunk."""
    path = os.path.join(OUT, "assets", name)
    if not os.path.exists(path):
        raise SystemExit("screenshot missing, cannot size it: %s" % path)
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise SystemExit("not a PNG: %s" % path)
    return struct.unpack(">II", head[16:24])


# The frame div already clips to a radius, so the button only has to stop
# being a button: no chrome, full width, and the image left to size itself.
_ZOOM_BTN = ("display: block; width: 100%; margin: 0; padding: 0; border: 0; "
             "background: none; font: inherit; color: inherit; "
             "position: relative; cursor: zoom-in; -webkit-appearance: none;")

# The affordance is visible at rest rather than on hover: a phone has no
# hover, and this is the one control on the page a touch reader would
# otherwise have no way of guessing. releases.js unhides it, so it never
# promises something that JavaScript is not there to deliver.
_ZOOM_HINT = ("position: absolute; right: 10px; bottom: 10px; "
              "padding: 5px 9px; border-radius: 6px; "
              "border: 1px solid rgba(157,189,245,0.30); "
              "background: rgba(8,12,18,0.82); color: #cfe0ff; "
              "font-family: 'JetBrains Mono', monospace; font-size: 10px; "
              "font-weight: 700; letter-spacing: 0.08em; "
              "text-transform: uppercase; line-height: 1; opacity: 0.72; "
              "transition: opacity 0.25s ease; pointer-events: none;")

# The frame and figure styles are the artifact's own, kept verbatim so the
# hover pass and the responsive pass treat a rebuilt figure exactly like the
# ones they were written against. style-hover is rewritten into a real :hover
# rule further down; leaving it here is what keeps that automatic.
_SHOT_FIG = (
    '<figure style="margin: 0; animation: lgRise 0.8s '
    'cubic-bezier(0.16,1,0.3,1) both; animation-timeline: view(); '
    'animation-range: entry 0%% cover 25%%;">\n'
    '          <div style="border: 1px solid #1e2631; border-radius: 12px; '
    'overflow: hidden; background: #0e1319; box-shadow: 0 20px 50px '
    'rgba(0,0,0,0.45); transition: transform 0.45s cubic-bezier(0.16,1,0.3,1), '
    'border-color 0.45s ease, box-shadow 0.45s ease;" style-hover="transform: '
    'translateY(-6px); border-color: #35496a; box-shadow: 0 30px 64px '
    'rgba(0,0,0,0.6), 0 0 0 1px rgba(59,127,240,0.18);">\n'
    '            <button type="button" class="lg-zoom" data-lg-zoom '
    'aria-label="Open this screenshot full screen" style="%s">'
    '<img src="/assets/%s" alt="%s" loading="lazy" width="%d" height="%d" '
    'style="display: block; width: 100%%; height: auto;">'
    '<span class="lg-zoomhint" data-lg-zoomhint hidden style="%s">Expand'
    '</span></button>\n'
    '          </div>\n'
    '          <figcaption style="margin-top: 14px; font-size: 14.5px; '
    'line-height: 1.55; color: #8d99a8;">'
    '<strong style="color: #dde5f0; font-weight: 600;">%s</strong> %s'
    '</figcaption>\n'
    '        </figure>')


def _figure(shot):
    name, alt, lead, body = shot
    w, h = _png_size(name)
    return _SHOT_FIG % (_ZOOM_BTN, name, html.escape(alt, quote=True), w, h,
                        _ZOOM_HINT, html.escape(lead), body)


# gap: 26px is what tells the screenshot grid apart from the privacy grid
# (gap: 1px) and the status grid (gap: 20px), which share its column rule.
_grid_open = ('<div style="display: grid; grid-template-columns: '
              'repeat(auto-fit, minmax(420px, 1fr)); gap: 26px; '
              'margin-top: 44px;">')
if doc.count(_grid_open) != 1:
    raise SystemExit("screenshot grid not found, or not unique")
_gi = doc.index(_grid_open)
_depth, _gend = 0, None
for _m in re.finditer(r"<div\b|</div>", doc[_gi:]):
    _depth += 1 if _m.group(0) == "<div" else -1
    if _depth == 0:
        _gend = _gi + _m.end()
        break
if _gend is None:
    raise SystemExit("screenshot grid is unbalanced")

_grid = (_grid_open + "\n        "
         + "\n        ".join(_figure(s) for s in _SHOTS)
         + "\n      </div>")
doc = doc[:_gi] + _grid + doc[_gend:]

# Nothing may still point at an artifact screenshot: those payloads are not
# written out, so a surviving reference would be a dead <img> that no
# resolve-every-local-reference check could see through a bare uuid.
_orphan = [u[:8] for u in dropped
           if manifest[u]["mime"] == "image/png" and u in doc]
if _orphan:
    raise SystemExit("artifact screenshot still referenced: %s"
                     % ", ".join(_orphan))

# 13. Eleven themes, shown rather than claimed.
#
#     The page said "Eleven themes" in a feature card and "eleven WCAG-AA
#     themes" in the meta description, and then showed none of them: 8,800px
#     of one slate palette and a single blue accent. Each swatch is a
#     miniature of the client -- rail, two received bubbles, one sent bubble
#     in the accent -- so the strip reads as the app in eleven outfits rather
#     than as a paint chart.
#
#     THE COLOURS ARE NOT DECORATIVE. Every value below is copied from
#     qml/AppTheme.qml in the client repo (the `_light`, `_dark`, `_graphite`
#     ... palette objects, resolved through their colour literals). If a
#     palette changes there, it has to be changed here too -- this repo
#     cannot see that one at build time. Order and names follow the
#     SettingsManager::Theme enum, ids 1-11; id 0 is "System", which is not a
#     palette but a choice between two of these.
_THEMES = [
    # name,             background, surface,   accent,    border
    ("Lightning Light", "#EBF0F7", "#FFFFFF", "#1D57FF", "#C4D2E7"),
    ("Lightning Dark",  "#0D1117", "#161C26", "#1D57FF", "#212A39"),
    ("Graphite",        "#1A1A1D", "#26262B", "#2E6EEB", "#37373E"),
    ("Midnight",        "#0F172A", "#192332", "#1D57FF", "#334155"),
    ("Nordic",          "#2E3440", "#3B4252", "#4D6D95", "#434C5E"),
    ("Purple Dusk",     "#1E1B2E", "#2A2440", "#7C5CD6", "#3A3255"),
    ("Warm",            "#F6F1E7", "#FFFDF8", "#C2410C", "#DCD0B8"),
    ("Moss Light",      "#F1F9F3", "#FFFFFF", "#12A67F", "#DEE8E0"),
    ("Indigo Night",    "#101016", "#1B1B24", "#4A4EED", "#23232D"),
    ("Deep Teal",       "#031919", "#0C2526", "#27C2AD", "#193535"),
    ("Storm",           "#02051D", "#202473", "#FFD447", "#303C80"),
]


def _swatch(name, bg, surface, accent, border):
    bar = ('<span style="display: block; height: 7px; border-radius: 4px; '
           'background: %s; width: %s;"></span>')
    return (
        '<figure style="margin: 0;">'
        '<span class="lg-swatch" aria-hidden="true" style="display: flex; '
        'gap: 5px; height: 58px; padding: 7px; border-radius: 9px; '
        'background: %s; border: 1px solid %s;">'
        '<span style="flex: 0 0 12px; border-radius: 4px; background: %s;">'
        '</span>'
        '<span style="flex: 1; min-width: 0; display: flex; '
        'flex-direction: column; justify-content: flex-end; gap: 5px;">'
        '%s%s'
        '<span style="display: block; height: 7px; border-radius: 4px; '
        'background: %s; width: 58%%; align-self: flex-end;"></span>'
        '</span></span>'
        '<figcaption style="margin-top: 9px; font-family: '
        "'JetBrains Mono', monospace" '; font-size: 10px; line-height: 1.4; '
        'color: #7d8b9c;">%s</figcaption>'
        '</figure>'
    ) % (bg, border, surface, bar % (surface, "82%"), bar % (surface, "60%"),
         accent, html.escape(name))


_strip = (
    '\n      <div style="margin-top: 56px; padding-top: 34px; '
    'border-top: 1px solid #1b222c;" class="lg-themes">\n'
    '        <div style="display: flex; flex-wrap: wrap; align-items: '
    'baseline; gap: 10px 20px; justify-content: space-between;">\n'
    '          <h3 style="font-size: 21px; font-weight: 600; '
    'letter-spacing: -0.01em;">Eleven themes, and a twelfth that follows your '
    'desktop</h3>\n'
    '          <p style="max-width: 430px; font-size: 13.5px; line-height: '
    '1.6; color: #7d8b9c;">Set per account, so a work login and a personal '
    'one do not have to look the same. Every one is checked for WCAG-AA '
    'contrast on every surface.</p>\n'
    '        </div>\n'
    '        <div style="display: grid; grid-template-columns: '
    'repeat(11, minmax(0, 1fr)); gap: 18px 12px; '
    'margin-top: 26px;" class="lg-swatches">\n          '
    + "\n          ".join(_swatch(*t) for t in _THEMES)
    + '\n        </div>\n      </div>\n')

# Inside the screenshots section, after the picture grid closes. Anchored on
# the last figure correction 12 emitted, so a reordered or resized _SHOTS
# carries this with it rather than dropping the strip into the wrong section
# -- or hunting for a caption that no longer exists.
_last = ('%s</figcaption>\n        </figure>\n      </div>\n' % _SHOTS[-1][3])
if doc.count(_last) != 1:
    raise SystemExit("end of the screenshot grid not found")
doc = doc.replace(_last, _last.rstrip("\n") + _strip, 1)

# 14. Motion. The artifact already had a vocabulary -- lgRise on scroll,
#     drifting hero glows, a marquee, a light strike -- so this adds what was
#     missing rather than a second style of movement:
#
#       * a scroll progress bar across the header
#       * a ladder on the hero, which arrived all at once
#       * a cascade across the eleven theme swatches
#       * a class on the panels so a pointer can light them
#
#     Everything here is CSS. `motion.js` only sets state (which section is in
#     view, where the pointer is); it animates nothing itself, so the whole
#     lot is still silenced by the artifact's existing
#     `prefers-reduced-motion` rule.

# ---- the progress bar ------------------------------------------------------
# Inside the header, so it sits on the border between the header and the page
# and rides the sticky wrapper. `lgWipe` was already defined in the artifact
# and never used.
_hdr = '<header style="backdrop-filter: blur(14px);'
if doc.count(_hdr) != 1:
    raise SystemExit("header not found")
doc = doc.replace(
    _hdr, '<header style="position: relative; backdrop-filter: blur(14px);', 1)

_navclose = "    </nav>\n  </header>"
if doc.count(_navclose) != 1:
    raise SystemExit("end of nav not found")
doc = doc.replace(
    _navclose,
    '    </nav>\n'
    '    <div class="lg-progress" aria-hidden="true" style="position: absolute;'
    ' left: 0; right: 0; bottom: -1px; height: 2px; transform: scaleX(0);'
    ' transform-origin: 0 50%; background: linear-gradient(90deg, #3b7ff0,'
    ' #7fd1a6); pointer-events: none;"></div>\n  </header>', 1)

# A sentinel above the header. motion.js watches it rather than listening to
# scroll: an IntersectionObserver fires twice in the life of the page, a
# scroll listener fires on every frame of every scroll.
if doc.count("<div style=\"min-height: 100vh; background: #0c0f14;\">") != 1:
    raise SystemExit("page wrapper not found")
doc = doc.replace(
    "<div style=\"min-height: 100vh; background: #0c0f14;\">",
    "<div style=\"min-height: 100vh; background: #0c0f14;\">\n"
    "  <div data-lg-top aria-hidden=\"true\" style=\"position: absolute; "
    "top: 0; height: 1px; width: 1px;\"></div>", 1)

# ---- the hero ladder -------------------------------------------------------
# The h1 and the paragraph were already staggered (0s and 0.09s); everything
# else in the hero appeared at once, so the lockup and the buttons landed
# before the heading they belong to. One ladder over the whole block instead.
_RISE = "animation: lgRise 0.9s cubic-bezier(0.16,1,0.3,1) %ss both;"


def _delay(needle, secs, label):
    """Give one hero element its rung of the ladder."""
    global doc
    if doc.count(needle) != 1:
        raise SystemExit("hero %s not found (%d matches)" % (label,
                                                             doc.count(needle)))
    doc = doc.replace(needle, needle[:-1] + " " + (_RISE % secs) + '"', 1)


# The two that already animate are rewritten rather than appended to.
_h1_old = "letter-spacing: -0.035em; animation: lgRise 0.9s cubic-bezier(0.16,1,0.3,1) both;"
if doc.count(_h1_old) != 1:
    raise SystemExit("hero h1 animation not found")
doc = doc.replace(_h1_old,
                  "letter-spacing: -0.035em; " + (_RISE % "0.12"), 1)

_p_old = "color: #a4b1c2; animation: lgRise 0.9s cubic-bezier(0.16,1,0.3,1) 0.09s both;"
if doc.count(_p_old) != 1:
    raise SystemExit("hero paragraph animation not found")
doc = doc.replace(_p_old, "color: #a4b1c2; " + (_RISE % "0.19"), 1)

_delay('style="display: flex; align-items: center; gap: 22px; '
       'margin-bottom: 34px;"', "0", "brand lockup")
_delay('font-size: 11.5px; letter-spacing: 0.06em; color: #9dbdf5;"',
       "0.06", "version pill")
_delay('style="display: flex; flex-wrap: wrap; gap: 14px; margin-top: 38px;"',
       "0.26", "button row")
_delay("style=\"display: flex; flex-wrap: wrap; gap: 10px 30px; "
       "margin-top: 34px; font-family: 'JetBrains Mono', monospace; "
       "font-size: 12.5px; color: #7d8b9c;\"", "0.33", "licence line")
_delay('style="display: grid; grid-template-columns: repeat(auto-fit, '
       'minmax(190px, 1fr)); gap: 1px; margin-top: 72px; background: #1b222c; '
       'border: 1px solid #1b222c; border-radius: 12px; overflow: hidden;"',
       "0.40", "hero cards")

# ---- the swatch cascade ----------------------------------------------------
# A scroll-driven animation takes its progress from the scroll position, so
# `animation-delay` does nothing to it -- the whole row would light up at
# once. The stagger has to be in `animation-range`: each swatch finishes a
# little later than the one before it, which reads as a sweep left to right.
_sw_old = '<figure style="margin: 0;"><span class="lg-swatch"'
_n_sw = doc.count(_sw_old)
if _n_sw != 11:
    raise SystemExit("expected 11 swatches to stagger, found %d" % _n_sw)
for _i in range(11):
    doc = doc.replace(
        _sw_old,
        '<figure style="margin: 0; animation: lgRise 0.6s '
        'cubic-bezier(0.16,1,0.3,1) both; animation-timeline: view(); '
        'animation-range: entry 0%% cover %d%%;"><span class="lg-swatch"'
        % (14 + _i * 2), 1)


# 16. What 0.8.0 made true, and what it made false.
#
#     The artifact was written for a client that could not place a call and
#     had one conversation list. Both of those changed, and the page said
#     otherwise in nine places. Everything in this block is either a claim a
#     release has since falsified, or one the page had no way of making.
#
#     Each edit asserts its own needle, so a reworded artifact fails the
#     build rather than quietly leaving the old sentence up.


def _swap(before, after, label, count=1):
    """Replace exact text, or fail the build saying which claim went missing."""
    global doc
    n = doc.count(before)
    if n != count:
        raise SystemExit("0.8.0 pass: %s -- expected %d match(es), found %d"
                         % (label, count, n))
    doc = doc.replace(before, after, count)


# ---- the platform list ----------------------------------------------------
# macOS has shipped since 0.7.5. The title, the meta description, the Open
# Graph description, the hero button and the licence line all still said
# "Linux and Windows"; so did the JSON-LD, which was corrected by hand for
# 0.7.6 and which this generator then put straight back. That is the reason
# these live here and not in public/index.html.
_swap("<title>Lightning — a native Matrix desktop client for Linux and "
      "Windows</title>",
      "<title>Lightning — a native Matrix desktop client for Linux, Windows "
      "and macOS</title>", "the title")
_swap('content="Lightning is a native Qt 6 Matrix desktop client built on the '
      'official Rust Matrix SDK. Real GIF browsing, voice messages, working '
      'threads, multi-account, eleven WCAG-AA themes. GPL-3.0-or-later."',
      'content="Lightning is a native Qt 6 Matrix desktop client built on the '
      'official Rust Matrix SDK. Group calls that work with Element Call, GIF '
      'browsing, voice messages, real threads, eleven WCAG-AA themes. '
      'GPL-3.0-or-later."', "the meta description")
_swap('content="Everything other Matrix clients fake. Native Qt 6, official '
      'Rust Matrix SDK, real E2EE. Linux and Windows."',
      'content="Everything other Matrix clients fake. Native Qt 6, official '
      'Rust Matrix SDK, real E2EE, group calls. Linux, Windows and macOS."',
      "the Open Graph description")
_swap(">Download for Linux or Windows<", ">Download for Linux, Windows or macOS<",
      "the hero download button")
# A fourth item in the licence row rather than a longer third one: the row is
# flex-wrap, so it costs nothing, and "Linux + Windows x86-64 + macOS arm64"
# in one span is a line nobody reads.
_swap("<span>Linux + Windows x86-64</span>",
      "<span>Linux + Windows x86-64</span>\n        "
      "<span>macOS Apple Silicon</span>", "the licence line")

# ---- the hero pitch -------------------------------------------------------
_swap("GIF search, voice messages, threads that work properly, and several "
      "accounts signed in at the same time.",
      "Group calls, GIF search, voice messages, threads that work properly, "
      "and several accounts signed in at the same time.", "the hero paragraph")

# ---- a fifth "why" row, for calls -----------------------------------------
# Calls are the headline of 0.8.0 and this is the section the page uses to
# say what other clients do not do, so they belong in it rather than in a
# bullet halfway down the feature grid.
_swap("All four of these work today.", "All five of these work today.",
      "the why-section intro")

_ROW = ("display: grid; grid-template-columns: 88px minmax(0, 1fr) "
        "minmax(0, 1.15fr); align-items: start; gap: 28px 40px; "
        "padding: 34px 12px 34px 0; border-bottom: 1px solid #1c232d; "
        "transition: background 0.4s ease; animation: lgRise 0.7s "
        "cubic-bezier(0.16,1,0.3,1) both; animation-timeline: view(); "
        "animation-range: entry 0% cover 22%;")
_calls_row = (
    '        <div style="%s" style-hover="background: linear-gradient(90deg, '
    'rgba(59,127,240,0.07), rgba(59,127,240,0));">\n'
    "          <div style=\"font-family: 'JetBrains Mono', monospace; "
    'font-size: 34px; font-weight: 700; line-height: 1; color: #1f2b3d; '
    'letter-spacing: -0.03em;">05</div>\n'
    '          <h3 style="font-size: 27px; line-height: 1.16; font-weight: '
    '600; letter-spacing: -0.02em;">Calls that reach<br>Element Call</h3>\n'
    '          <div>\n'
    '            <p style="font-size: 15.5px; line-height: 1.65; color: '
    '#97a4b4;">Join the call in a room and you get audio, camera and screen '
    'sharing, with per-person volume and a raised hand the other side can '
    'see. The media is <strong style="color: #cfd9e6; font-weight: 600;">'
    'encrypted per participant</strong> before it leaves your machine, so '
    'the server forwarding it cannot read it.</p>\n'
    '            <p style="margin-top: 14px; padding-left: 15px; border-left: '
    '2px solid #2b3a52; font-size: 14.5px; line-height: 1.6; color: '
    '#7d8b9c;">On Windows you can share one window instead of a whole '
    'screen. Lightning asks that window to draw itself rather than cropping '
    'the screen, so nothing stacked on top of it is shared by accident.</p>\n'
    '          </div>\n'
    '        </div>\n'
    '\n') % _ROW

# Straight after row 04, which is the last thing before the rows container
# closes and the marquee begins.
_row4_end = ("It can't name a command to run.</p>\n          </div>\n"
             "        </div>\n\n      </div>\n")
_swap(_row4_end,
      _row4_end.replace("        </div>\n\n      </div>\n",
                        "        </div>\n\n" + _calls_row + "      </div>\n"),
      "the end of why-row 04")

# ---- the marquee ----------------------------------------------------------
# Both copies, or the -50% translate stops looping seamlessly: the second one
# exists only to be identical to the first.
_swap("<span>Threads</span><span style=\"color: #2b3a52;\">✦</span>"
      "<span>Polls</span>",
      "<span>Group calls</span><span style=\"color: #2b3a52;\">✦</span>"
      "<span>Screen sharing</span><span style=\"color: #2b3a52;\">✦</span>"
      "<span>Channels layout</span><span style=\"color: #2b3a52;\">✦</span>"
      "<span>Threads</span><span style=\"color: #2b3a52;\">✦</span>"
      "<span>Polls</span>", "the marquee", count=2)

# ---- the feature grid -----------------------------------------------------
# Six columns, and they have to stay six: the grid is auto-fit minmax(300px)
# in a 1116px shell, so it lays out three across and a seventh column would
# strand one item on a row of its own. Calls therefore take the slot Media
# was borrowing, and Media joins Messaging, which is where it reads better
# anyway.
_H3 = ("padding-bottom: 12px; border-bottom: 1px solid #232b35; "
       "font-size: 17px; font-weight: 600; color: #e8edf5;")
_H3_STACKED = ("padding-bottom: 12px; border-bottom: 1px solid #232b35; "
               "margin-top: 36px; font-size: 17px; font-weight: 600; "
               "color: #e8edf5;")
_UL = ("display: flex; flex-direction: column; gap: 13px; margin-top: 18px; "
       "font-size: 14.5px; line-height: 1.55; color: #94a1b1;")
_B = 'color: #cfd9e6; font-weight: 600;'

_media_head = '\n\n          <h3 style="%s">Media</h3>' % _H3_STACKED
if doc.count(_media_head) != 1:
    raise SystemExit("0.8.0 pass: the Media heading is not where it was")
_mi = doc.index(_media_head)
_me = doc.index("</ul>", _mi) + len("</ul>")
_media_block = doc[_mi:_me]
doc = doc[:_mi] + doc[_me:]

_msg_end = ("it assumes it is.</li>\n          </ul>")
_swap(_msg_end, _msg_end + _media_block, "the end of the Messaging column")

_calls_col = (
    '<h3 style="%s">Calls</h3>\n'
    '          <ul style="%s">\n'
    '            <li><strong style="%s">Group calls</strong> in a room, over '
    'MatrixRTC: audio, camera and screen sharing, all of it interoperating '
    'with Element Call.</li>\n'
    '            <li>Media is <strong style="%s">encrypted per participant'
    '</strong> in the same format Element Call uses, so the server that '
    'forwards it cannot read it. In an encrypted room a call that cannot '
    'encrypt its media is refused, not quietly downgraded.</li>\n'
    '            <li>The call server is <strong style="%s">discovered, never '
    'assumed</strong> — from your homeserver, or from the people already in '
    'the call. Lightning ships no address of its own.</li>\n'
    '            <li>A spotlight or grid stage, per-person volume, a member '
    'list grouped by power level, raised hands that Element sees, and a '
    'marker in the conversation list where a call is already running.</li>\n'
    '            <li>On Windows, share a single window rather than a whole '
    'screen, picked from a grid of live previews that names the application '
    'each one belongs to.</li>\n'
    '          </ul>\n'
    '\n          <h3 style="%s">Threads</h3>'
) % (_H3, _UL, _B, _B, _B, _H3_STACKED)
_swap('<h3 style="%s">Threads</h3>' % _H3, _calls_col, "the Threads heading")

# Channels: the second conversation column, and the rail that drives it.
_spaces_li = ("<li>Spaces, including <strong style=\"%s\">subspaces inside "
              "them</strong>, indented in the rail and browsable from a "
              "Space's front page.</li>" % _B)
_swap(_spaces_li,
      _spaces_li + '\n            '
      '<li><strong style="%s">Two conversation layouts</strong>, one per '
      'account: the classic activity-ordered list, or <strong style="%s">'
      'Channels</strong> — a Spaces rail with Home, Direct Messages and a '
      'view for each Space, holding that Space\'s rooms in the order the '
      'Space sets rather than by activity.</li>\n            '
      '<li>Drag the Spaces in the rail into the order you want; drop one on '
      'another and it becomes a folder. That grouping is <strong style="%s">'
      'local to your device</strong> and writes nothing to Matrix.</li>'
      % (_B, _B, _B), "the Spaces bullet")

_swap("<li>Pickers you can resize, which stay the size you left them, "
      "layouts that hold up from narrow to wide, and keyboard navigation "
      "everywhere.</li>",
      '<li><strong style="%s">Rebindable keyboard shortcuts</strong>, '
      'including the awkward case: Ctrl+B is Bold inside the message box and '
      'toggles the conversation list everywhere else.</li>\n            '
      "<li>Pickers you can resize, which stay the size you left them, "
      "layouts that hold up from narrow to wide, and keyboard navigation "
      "everywhere.</li>" % _B, "the Desktop experience list")

# ---- privacy --------------------------------------------------------------
# "the only outside services ... are the GIF providers" stopped being true
# twice over: link previews are fetched by Lightning itself (the page already
# says so two cards down), and a call reaches an SFU.
_swap("Apart from the homeserver you signed in to, the only outside services "
      "Lightning talks to are the GIF providers, and only while the GIF "
      "picker is open.",
      "Apart from the homeserver you signed in to, Lightning only reaches "
      "outside for things you ask for: a GIF search while the picker is "
      "open, a link preview you have switched on, and the call server when "
      "you join a call.", "the privacy lead")

# Four cards laid out two across; six keeps that a rectangle. Both additions
# are facts the page was already relying on elsewhere without stating.
_PCARD = ('<div style="padding: 26px; background: #10151c;">\n'
          '          <h3 style="font-size: 16px; font-weight: 600;">%s</h3>\n'
          '          <p style="margin-top: 10px; font-size: 14px; '
          'line-height: 1.6; color: #8d99a8;">%s</p>\n'
          '        </div>')
_upd_card = _PCARD % (
    "Update checks send a version",
    "Just <code style=\"color: #9dbdf5;\">Lightning/&lt;version&gt;</code>. "
    "No Matrix ID, homeserver, device ID, token or room data, and there's no "
    "tracking ID to send in the first place. It's on by default and you can "
    "switch it off.")
if doc.count(_upd_card) != 1:
    raise SystemExit("0.8.0 pass: the update-check privacy card moved")
_swap(_upd_card, _upd_card + "\n        " + (_PCARD % (
    "Call media is encrypted",
    "A call's audio and video are encrypted for the other people in it "
    "before they leave your machine, so the server forwarding them cannot "
    "read them. That server is not one we chose: it comes from your "
    "homeserver, or from whoever is already in the call.")) + "\n        "
    + (_PCARD % (
        "GIF search sends the search box",
        "Only the words you typed, and only to the provider you picked. Not "
        "your Matrix ID, not the room, not a message.")),
    "the privacy card grid")

# ---- project status -------------------------------------------------------
# The card that has to change every time this claim does. Calls are no longer
# switched off; what is still true is which platforms anyone has made one on.
_swap('<h3 style="font-size: 16.5px; font-weight: 600; color: #f0d6a0;">'
      "Calls don't work yet</h3>\n"
      '          <p style="margin-top: 11px; font-size: 14.5px; line-height: '
      '1.6; color: #b9a476;">There\'s a 1:1 voice stack in the code, with '
      'MSC2746 signalling and a WebRTC engine, but it\'s switched off on '
      'purpose. Nobody has confirmed an answered call over a real network '
      'yet, so the button says "coming soon" instead of pretending '
      'otherwise.</p>',
      '<h3 style="font-size: 16.5px; font-weight: 600; color: #f0d6a0;">'
      "Calls are new</h3>\n"
      '          <p style="margin-top: 11px; font-size: 14.5px; line-height: '
      '1.6; color: #b9a476;">Audio, camera and screen sharing work against '
      'Element Call — used by hand on Linux and on a packaged Windows build. '
      '<strong style="color: #f0d6a0; font-weight: 600;">Nobody has made a '
      'call on macOS.</strong> The Windows camera runs at about ten frames a '
      'second, and on Linux a distribution without GStreamer gets an honest '
      'refusal rather than a call.</p>', "the calls status card")


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
             "github.com/Mizerd/lightning\"")
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

# The sticky alpha bar. The "ALPHA" pill inside it is a <span>, which _mark()
# cannot reach (TAG_RE covers nav/section/div/figure/a/h1-h3 only) -- a
# predicate for it here matched an unrelated amber label in the status section
# instead, so the pill is tagged by hand in correction 3.
_mark("lg-alpha-bar", lambda a: "background: #241c0d" in a
      and "padding: 11px 24px" in a)

# The hero's version pill. At 11.5px the line runs ~319px, so on a 390px screen
# it breaks after "matrix-rust-sdk" and leaves "0.18" alone on a second line.
_mark("lg-pill", lambda a: "border-radius: 100px" in a and "inline-flex" in a
      and "JetBrains Mono" in a)

# Type scale, keyed off the desktop size so nothing is guessed.
for _cls, _px in (("lg-t1", "68px"), ("lg-t2", "42px"),
                  ("lg-t3", "34px"), ("lg-t4", "27px")):
    _mark(_cls, lambda a, _p=_px: ("font-size: %s;" % _p) in a)
_mark("lg-t4", lambda a: "font-size: 26px;" in a)

# Panels the pointer can light (correction 14). One background colour
# identifies every panel on the page. The amber warning boxes are a different
# colour and are deliberately left out: a blue highlight sweeping over a "this
# is not signed" box would read as decoration on a warning.
_mark("lg-card", lambda a: "background: #10151c;" in a)

print("  resp   " + ", ".join("%s=%d" % (k, v) for k, v in _counts.items()))

helmet = re.search(r"<helmet>(.*?)</helmet>", doc, re.S).group(1)
doc = re.sub(r"<helmet>.*?</helmet>", "", doc, flags=re.S)

# Fonts are served from our own origin now, so the Google Fonts preconnects are
# dead weight that also leaks a hint to a third party.
helmet = re.sub(r'<link rel="preconnect"[^>]*>\s*', "", helmet)

body = re.search(r"<x-dc>(.*?)</x-dc>", doc, re.S).group(1)

# Structured data. This exists for one reason: Google had already picked
# https://github.com/Mizerd/lightning as the canonical page for this content,
# because the domain used to redirect there and a redirect is the strongest
# duplicate signal there is. The self-referencing <link rel="canonical">
# below says "this URL is the original". `sameAs` says the rest of it: the
# GitHub repository is the same project, not a competing copy of this page.
#
# It is a <script type="application/ld+json"> data block, which is never
# executed, so `script-src 'self'` does not have to be loosened to carry it.
_ld = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": "Lightning",
    "url": SITE_URL + "/",
    "applicationCategory": "CommunicationApplication",
    "applicationSubCategory": "Matrix client",
    # macOS has been a published download since 0.7.5 and the page says so in
    # seven other places; this was the one surface still contradicting it.
    "operatingSystem": "Linux, Windows, macOS",
    "softwareVersion": str(releases.get("version", "")),
    "softwareRequirements": "Qt 6.5 or later",
    "license": "https://www.gnu.org/licenses/gpl-3.0.html",
    "isAccessibleForFree": True,
    "description": (
        "A native Matrix desktop client written in Qt 6 on top of the "
        "official Rust Matrix SDK, with group calls, GIF search, voice "
        "messages, threads and several accounts signed in at once."),
    "offers": {"@type": "Offer", "price": "0",
               "priceCurrency": "USD"},
    "sameAs": [REPO_URL],
    "codeRepository": REPO_URL,
    # From _SHOTS, so a screenshot that is renamed or dropped cannot leave a
    # 404 behind in the structured data. Nothing else looks at these URLs:
    # they are in content=, which the resolve-every-local-reference check in
    # check.py does not see.
    "screenshot": [SITE_URL + "/assets/" + s[0] for s in _SHOTS],
    "author": {"@type": "Person", "name": "Rokas Smetonis"},
}

extra_head = """
<link rel="canonical" href="{site}/">
<meta name="theme-color" content="#0c0f14">
<meta property="og:url" content="{site}/">
<meta property="og:site_name" content="Lightning">
<meta property="og:image" content="{site}/assets/og-card.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:type" content="image/png">
<meta property="og:image:alt" content="The Lightning lockup beside a screenshot of a group call running at the top of a room">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{ld}</script>
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
.lg-copybtn:hover {{ background: #17202b; color: #dbe6f2;
                    border-color: #35455a; }}
.lg-copybtn:active {{ transform: translateY(1px); }}

@keyframes lgBreathe {{
  0%, 100% {{ filter: drop-shadow(0 0 0 rgba(59,127,240,0)); }}
  50% {{ filter: drop-shadow(0 0 14px rgba(93,148,255,0.42)); }}
}}

/* ---- screenshots open full screen ---------------------------------------
   The trigger is a <button> wrapping the <img> (see correction 12), so it
   already focuses and activates on Enter and Space. All that is left is to
   look like it. */
.lg-zoom:focus-visible {{ outline: 2px solid #5590f5; outline-offset: 3px; }}
.lg-zoom:hover .lg-zoomhint,
.lg-zoom:focus-visible .lg-zoomhint {{ opacity: 1; }}

/* The overlay. z-index 2000 against the sticky header's 60, which is the
   only other stacking context the page creates. */
.lg-lightbox {{
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
  padding: 30px;
  background: rgba(4, 7, 12, 0.94);
  /* Stops a flick at the top or bottom of the overlay from scrolling the
     page behind it once the overlay itself has nowhere left to go. */
  overscroll-behavior: contain;
  /* Not decoration: iOS only dispatches click for a plain <div> when it
     looks interactive, and a cursor is what makes it look interactive.
     Without this the backdrop swallows the tap and nothing closes. */
  cursor: zoom-out;
}}
/* 100dvh, not 100vh: on a phone the browser chrome is counted in vh, so vh
   would size the image to a viewport taller than the one you can see and
   crop the bottom of it behind the address bar. */
.lg-lightbox img {{
  max-width: 100%;
  max-height: calc(100dvh - 150px);
  width: auto;
  height: auto;
  object-fit: contain;
  border-radius: 10px;
  border: 1px solid #1e2631;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
  cursor: default;
}}
.lg-lightbox figcaption {{
  max-width: 640px;
  text-align: center;
  font-size: 14px;
  line-height: 1.55;
  color: #93a0b0;
  cursor: default;
}}
.lg-lbclose {{
  position: absolute;
  top: 14px;
  right: 14px;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border-radius: 9px;
  border: 1px solid #24303f;
  background: #10161e;
  color: #cfe0ff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
}}
.lg-lbclose:hover {{ background: #1a2432; border-color: #3a4a61; }}
.lg-lbclose:focus-visible {{ outline: 2px solid #5590f5; outline-offset: 2px; }}
/* Held while the overlay is open, so the page behind it cannot be scrolled
   away underneath. Both elements, because which one scrolls is not the same
   on every browser. */
html.lg-lbopen, body.lg-lbopen {{ overflow: hidden !important; }}

/* A theme swatch is a miniature of the client: rail, two received bubbles,
   one sent bubble in the accent. Nothing here sets a colour -- every one is
   inline, per theme, from the palette table in unbundle.py. */
.lg-swatch {{ transition: transform 0.3s cubic-bezier(0.16,1,0.3,1); }}
figure:hover > .lg-swatch {{ transform: translateY(-3px); }}

/* ---- scrollbars ---------------------------------------------------------
   The install boxes scroll horizontally (`white-space: pre`), and the
   AppImage command is long enough to always show a bar. The platform default
   is light, which on a #070a0e box looks like a rendering fault rather than
   a control. `color-scheme` is the part that does the real work -- it also
   darkens the page's own scrollbar and any form control -- and the explicit
   colours make the ones inside the code boxes thinner and quieter than the
   page's. */
:root {{ color-scheme: dark; }}
.lg-cmd, [data-lg-copy] {{
  scrollbar-width: thin;
  scrollbar-color: #2b3a52 transparent;
}}
.lg-cmd::-webkit-scrollbar, [data-lg-copy]::-webkit-scrollbar {{
  height: 8px;
}}
.lg-cmd::-webkit-scrollbar-track, [data-lg-copy]::-webkit-scrollbar-track {{
  background: transparent;
}}
.lg-cmd::-webkit-scrollbar-thumb, [data-lg-copy]::-webkit-scrollbar-thumb {{
  background: #2b3a52;
  border-radius: 4px;
}}
.lg-cmd::-webkit-scrollbar-thumb:hover,
[data-lg-copy]::-webkit-scrollbar-thumb:hover {{ background: #3d5175; }}

/* ---- scroll progress ----------------------------------------------------
   The obvious way to do this is `animation-timeline: scroll(root block)`,
   which runs off the main thread. It is not used, because Firefox does not
   support scroll-driven animations -- and Firefox is not a rounding error
   for a Linux Matrix client. motion.js drives the transform instead, so the
   bar works in every browser. The inline scaleX(0) is what it looks like
   before any script runs, and if none ever does it stays invisible. */
.lg-progress {{ will-change: transform; }}

/* ---- the header reacts to leaving the top ------------------------------
   Only colour and shadow. Changing its height here would move every anchor
   on the page, because `section[id]` offsets its scroll-margin by the height
   of this bar. */
header {{ transition: background 0.35s ease, box-shadow 0.35s ease,
                     border-color 0.35s ease; }}
header.lg-stuck {{
  background: rgba(9, 12, 16, 0.94);
  border-bottom-color: #26303d;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.36);
}}

/* ---- the nav follows the page ------------------------------------------
   An underline that grows from the left, so moving between sections reads as
   the marker travelling rather than blinking on and off. */
.lg-navlink {{ position: relative; transition: color 0.25s ease; }}
.lg-navlink::after {{
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: -6px;
  height: 2px;
  border-radius: 2px;
  background: #3b7ff0;
  transform: scaleX(0);
  transform-origin: 0 50%;
  transition: transform 0.32s cubic-bezier(0.16, 1, 0.3, 1);
}}
.lg-navlink.lg-here {{ color: #dbe6f5; }}
.lg-navlink.lg-here::after {{ transform: scaleX(1); }}

/* ---- panels follow the pointer -----------------------------------------
   `background-image` rather than an overlay element: the panels set
   `background` inline as a shorthand, which resets background-image, so this
   needs !important either way -- and doing it on the element itself avoids a
   pseudo-element that would have to be kept off the text.

   Fine pointers only. On a touch screen there is no pointer to follow, and
   the highlight would stick wherever the last tap landed. */
/* Registered at the top level, not inside the query below: @property is a
   registration rather than a style, and nesting it in a conditional group is
   not reliably honoured. Registering it is what makes --lg-spot a <number>
   the browser can interpolate -- an unregistered custom property is a string
   and would snap from 0 to 1 instead of fading. */
@property --lg-spot {{
  syntax: "<number>";
  inherits: false;
  initial-value: 0;
}}

@media (hover: hover) and (pointer: fine) {{
  .lg-card {{
    background-image: radial-gradient(320px circle at var(--lg-mx, 50%) var(--lg-my, 0%),
                      rgba(93, 148, 255, calc(0.10 * var(--lg-spot))),
                      transparent 42%) !important;
    transition: --lg-spot 0.4s ease, border-color 0.3s ease,
                transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  }}
  .lg-card:hover {{ --lg-spot: 1; }}
}}

/* ---- the mark idles ------------------------------------------------------
   The 14px chip in the pill already flickers. The 88px hero mark gets a
   slower breath instead -- the same idea at a size where a flicker would be
   a distraction rather than a detail. */
.lg-brandmark {{ animation: lgBreathe 6.5s ease-in-out infinite; }}

/* ---- buttons ------------------------------------------------------------- */
/* The arrow is decorative: every download button carries an aria-label, which
   replaces the accessible name entirely, so nothing reads "downwards arrow".
*/
.dlbtn::after {{
  content: "↓";
  display: inline-block;
  margin-left: 7px;
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}}
.dlbtn:hover::after {{ transform: translateY(2px); }}
.lg-copybtn {{ transition: background 0.2s ease, color 0.2s ease,
                          border-color 0.2s ease; }}
.lg-copybtn.lg-copied {{
  border-color: #2f6b4d !important;
  background: #10201a !important;
  color: #7fd1a6 !important;
}}

/* ---- the overlay arrives ------------------------------------------------
   `hidden` cannot be transitioned -- display:none has no intermediate state
   -- so releases.js unhides first and adds .lg-lbon on the next frame, and
   on the way out waits out the duration before hiding again. */
.lg-lightbox {{
  opacity: 0;
  transition: opacity 0.22s ease;
}}
.lg-lightbox.lg-lbon {{ opacity: 1; }}
.lg-lightbox img, .lg-lightbox figcaption {{
  transform: scale(0.97);
  opacity: 0;
  transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1),
              opacity 0.28s ease;
}}
.lg-lightbox.lg-lbon img, .lg-lightbox.lg-lbon figcaption {{
  transform: none;
  opacity: 1;
}}

/* Smooth scrolling is in the artifact's own reset; the reduced-motion block
   there covers animation and transition but not this, and a smooth scroll is
   exactly the kind of movement that rule exists to stop. */
@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior: auto !important; }}
  .lg-progress {{ display: none !important; }}
}}

/* Two wordings of the alpha warning, one visible at a time. The brief one is
   for phones, where the full sentence wrapped to four lines in a bar that is
   sticky -- so it cost a sixth of the screen on every scroll. */
.lg-alpha-brief {{ display: none; }}

/* Eleven across needs about 1,080px of window. Below that they go two
   rows deep (6 + 5) rather than orphaning the last two, which is what
   auto-fit did: nine in a row and a stranded pair underneath. */
@media (max-width: 1080px) {{
  /* !important, because the grid is an inline style on the element and
     an inline style beats any stylesheet rule without it. Same reason
     as every override in the phone block below. */
  .lg-swatches {{ grid-template-columns: repeat(6, minmax(0, 1fr))
                 !important; }}
}}

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

  /* Swap the two wordings, and drop the "ALPHA" pill -- the brief sentence
     opens with the same word, so the pill is only a wasted row. */
  .lg-alpha-full, .lg-alpha-pill {{ display: none !important; }}

  /* Drop the flex row for a plain block of running text. As flex items the
     warning and the "what's missing" link were forced onto separate rows --
     flex blockifies its children, so `display: inline` on the span computes
     to `block` -- which cost a whole row to a 126px link. Flowing them as one
     paragraph lets the link finish the last line instead. */
  .lg-alpha-bar {{
    display: block !important;
    text-align: center !important;
    padding: 8px 14px !important;
    font-size: 12.5px !important;
    line-height: 1.4 !important;
  }}
  .lg-alpha-brief {{ display: inline !important; }}
  .lg-alpha-bar a {{ margin-left: 6px !important; }}

  /* The lockup is the first thing on the page; keep it a brand, not a
     banner. The mark shrinks less than the wordmark -- it is the part that
     survives at small sizes. */
  .lg-brand {{ gap: 14px !important; margin-bottom: 24px !important; }}
  .lg-brandmark {{ width: 58px !important; height: 58px !important; }}
  .lg-brandname {{ font-size: 38px !important; }}
  .lg-brandsub {{ font-size: 13.5px !important; }}

  /* "#lightning:matrix.smetonis.net" has no spaces, so it cannot wrap and it
     ran 15px past its card. Let it break rather than spill. */
  .lg-room {{ overflow-wrap: anywhere !important; }}

  /* Four to a row on a phone: 4 + 4 + 3. At 320px that is a 62px column,
     so the longer names ("Lightning Light") wrap -- reserving both lines
     everywhere keeps the strip a grid instead of a ragged edge, and costs
     one line of nothing on the short names. */
  .lg-swatches {{ grid-template-columns: repeat(4, minmax(0, 1fr))
                 !important; gap: 14px 10px !important; }}
  .lg-swatches figcaption {{ min-height: 2.8em !important; }}
  .lg-swatch {{ height: 46px !important; padding: 5px !important; }}

  /* Edge to edge, and less furniture around the picture: a phone screen is
     mostly the picture or it is not worth opening. */
  .lg-lightbox {{ padding: 14px !important; gap: 12px !important; }}
  .lg-lightbox img {{ max-height: calc(100dvh - 130px) !important; }}
  .lg-lightbox figcaption {{ font-size: 12.5px !important; }}

  /* A 7ch hanging indent is a fair slice of a 30-character line, so the
     architecture diagram gets a shallower one and slightly tighter type. */
  .lg-arch {{ font-size: 11.5px !important; line-height: 1.75 !important;
             padding: 16px !important; }}
  .lg-archrow {{ padding-left: 2ch !important; text-indent: -2ch !important; }}

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
""".format(site=SITE_URL, hover="\n".join(hover_rules),
           ld=json.dumps(_ld, separators=(",", ":")))

page = (
    "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
    + helmet.strip() + "\n" + extra_head.strip()
    + "\n<script src=\"/releases.js\" defer></script>\n"
    # Separate from releases.js on purpose: this one has nothing to do with
    # releases, and keeping the release feed's script free of page furniture
    # means a change to either cannot break the other. Same cache rule
    # though -- see _headers.
    + "<script src=\"/motion.js\" defer></script>\n"
    + "</head>\n<body>\n" + body.strip() + "\n</body>\n</html>\n"
)

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
    fh.write(page)
print("  page   %-52s %8d B" % ("index.html", len(page.encode())))
