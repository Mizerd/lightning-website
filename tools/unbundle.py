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

_bold = "color: #fbeccd; font-weight: 700;"
doc = doc.replace(
    "and calls don't work yet.</span>",
    "and calls don't work yet.</span>"
    "<span class=\"lg-alpha-brief\">Alpha " + _ver + " \u2014 "
    "<strong style=\"%s\">no security audit</strong>, "
    "<strong style=\"%s\">no code signing</strong>, no calls yet.</span>"
    % (_bold, _bold), 1)

# 6. macOS. The artifact had a one-line card saying a macOS build existed but
#    would not be published until it could be signed. That is no longer the
#    plan -- it ships unsigned when it ships -- so the small card goes and a
#    real block takes its place, below the Linux and Windows columns.
#
#    Nothing here is wired to a release: there is no download button, no
#    package card and no entry in releases.json, so releases.js and
#    /api/latest never touch it. It is static copy until there is a build to
#    point at, at which point it becomes ordinary packages with os "macos".
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
    'font-weight: 700; letter-spacing: 0.04em; color: #9dbdf5;">Coming soon'
    '</span>\n'
    '        </div>\n'
    '        <p style="max-width: 780px; %s">A macOS build is in progress. '
    'There is nothing to download yet, and no date -- when there is a release '
    'it appears on the GitHub releases page with everything else.</p>\n'
    '\n'
    '        <div style="margin-top: 18px; padding: 18px 20px; border: 1px '
    'solid #4a3814; border-radius: 11px; background: #1c1609;">\n'
    '          <div style="font-size: 14.5px; font-weight: 600; color: '
    '#f0d6a0;">It will not be signed or notarised</div>\n'
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
    'line-height: 1.55; color: #7d8b9c;">On macOS 14 and earlier there is a '
    'shortcut: Control-click the app, choose '
    '<em style="font-style: normal; color: #9fadbd;">Open</em>, then '
    '<em style="font-style: normal; color: #9fadbd;">Open</em> again. macOS 15 '
    'removed it, so the route above is the one that always works.</p>\n'
    '      </div>\n'
    '\n') % (_BODY, _CARD, _STEP, _BODY, _CARD, _STEP, _BODY,
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
    'Linux and Windows</div>\n'
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
.lg-copybtn:hover {{ background: #17202b; color: #dbe6f2;
                    border-color: #35455a; }}
.lg-copybtn:active {{ transform: translateY(1px); }}

/* Two wordings of the alpha warning, one visible at a time. The brief one is
   for phones, where the full sentence wrapped to four lines in a bar that is
   sticky -- so it cost a sixth of the screen on every scroll. */
.lg-alpha-brief {{ display: none; }}

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
