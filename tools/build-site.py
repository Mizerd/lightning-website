#!/usr/bin/env python3
"""Write public/index.html for the Lightning site.

SAME BUILD. The page is made from the application's own design tokens and
shows nothing but the application, so it is the first piece of evidence for
its own claims. The test for any element: if it does not exist in the app, it
does not go on the site. The app has no gradient text, no glow, no marquee,
no scroll reveals and no uppercase tracked mono eyebrows -- it removed the
last of those deliberately (qml/MenuSectionLabel.qml) -- so none of them are
here either.

Colours are read from qml/AppTheme.qml: Indigo Night for the surfaces, the
Storm bolt for the one accent. The accent discipline is the app's own --
AppTheme confines bolt to "focus, checked state, ONE primary action, the Home
tile", so it appears a handful of times on this whole page and never as a
wash. Links get their own ink because the accent cannot carry AA at body
size; the app wrote that reasoning down and it holds here.
"""
import html
import json
import random
import os
import pathlib
import struct

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PUB = ROOT / "public"
# The self-hosted @font-face block, kept beside this script rather than inside
# it: it is 335 lines of Google-Fonts-shaped unicode-range declarations and
# nothing here ever edits it. It is the AUTHORITY on which weights exist --
# check.py compares every font-weight on the page against these rules, because
# a weight with no face paints as nothing rather than falling back.
FONTS = (HERE / "fontfaces.css").read_text(encoding="utf-8")

feed = json.loads((PUB / "releases.json").read_text(encoding="utf-8"))
VERSION = feed["version"]
RELEASED = feed["released"]
RELEASES_URL = feed["releases_url"]

# Read from the PNG headers, never written down: check.py asserts that the
# width/height the page declares are the file's real ones, and a hand-kept
# table here would be a second copy of that truth waiting to drift from it.
DEFAULT_THEME = "indigo-night"


def _png_size(rel):
    with open(PUB / "assets" / rel, "rb") as fh:
        return struct.unpack(">II", fh.read(24)[16:24])


# One entry per SCENARIO. Every scenario exists once per theme under
# assets/shots/<scenario>--<theme>.png, captured from the client's own
# screenshot-demo mode, so picking a theme changes the pictures too.
SCENARIOS = ("home-overview", "call-grid", "thread-view", "media-gallery",
             "find-in-room", "settings-themes", "community-overview")
SHOTS = {sc: _png_size(f"shots/{sc}--{DEFAULT_THEME}.png") for sc in SCENARIOS}

# The eleven themes, named as the app names them. The swatch colours are each
# theme's own accent from qml/AppTheme.qml. check.py cannot verify they are
# current -- it can only prove nobody quietly dropped one.
# The eleven palettes, extracted from the CLIENT's qml/AppTheme.qml by
# tools/extract-themes.py. Not a hand-kept table of accents any more: every
# token the page paints with, for every theme, so clicking a swatch repaints
# the page the way the application actually looks.
THEMES_DATA = json.loads((PUB / "themes.json").read_text(encoding="utf-8"))["themes"]


def _slug(name):
    return name.lower().replace(" ", "-")


def theme_css():
    """One [data-theme] block per theme, plus the default on bare :root.

    The default IS Indigo Night, so its block is emitted on `:root` as well --
    a page that has never been clicked must not depend on JavaScript having run
    to have colours.
    """
    out = []
    for t in THEMES_DATA:
        k = t["tokens"]
        decls = " ".join(
            f"--{tok}: {k[tok]};" for tok in
            ("page", "raised", "elevated", "hairline", "border",
             "text", "text-2", "text-3", "accent", "link"))
        decls += f" color-scheme: {'dark' if k['dark'] else 'light'};"
        decls += f" --sky-opacity: {0.16 if k["dark"] else 0.46};"
        out.append(f'[data-theme="{_slug(t["name"])}"] {{ {decls} }}')
    return "\n".join(out)


THEMES = [(t["name"], t["tokens"]["accent"]) for t in THEMES_DATA]


def _tok(name, token):
    return next(t["tokens"][token] for t in THEMES_DATA if t["name"] == name)


def shot(name, alt, cls=""):
    """One screenshot figure.

    `data-lg-shot` carries the scenario; releases.js rewrites the src when the
    theme changes, so the pictures follow the palette the reader picked. The
    baked src is the default theme, so a page without JavaScript still shows
    real screenshots rather than empty boxes.
    """
    w, h = SHOTS[name]
    extra = f" {cls}" if cls else ""
    return f'''<figure class="lg-shot{extra}">
  <button class="lg-shot-btn" data-lg-zoom type="button" aria-label="Open {alt} full size">
    <img src="/assets/shots/{name}--{DEFAULT_THEME}.png" data-lg-shot="{name}"
         alt="{alt}" width="{w}" height="{h}" loading="lazy" decoding="async">
    <span class="lg-zoomhint" data-lg-zoomhint hidden>Expand</span>
  </button>
</figure>'''


ASSET = feed["asset_url"]


def asset_href(fil, pkg=None):
    """The download URL, or a PINNED package's own absolute one.

    A pinned package is a deliberate exception: it belongs to an older release
    than the one this page is about, so the version template must not be
    applied to it. macOS is pinned at 0.9.4 because 0.9.5 has no macOS build.
    """
    if pkg and pkg.get("url"):
        return pkg["url"]
    return ASSET.replace("${version}", VERSION).replace("${file}", fil)


def pkg_card(p):
    """One package card, GENERATED FROM THE FEED so the two cannot disagree.

    Hand-writing these is how the page ends up naming a file the feed does
    not — check.py compares them for exactly that reason, and generating them
    makes the comparison trivially true instead of a thing somebody has to
    remember. releases.js then clones card zero per OS at runtime, so every
    per-card attribute it overwrites has to exist here or the clone keeps card
    zero's value; that was the bug that once served the .deb from every Linux
    button.
    """
    fil = p.get("file", "")
    match = f' data-lg-match="{p["match"]}"' if p.get("match") else ""
    # The AppImage command carries `&&`, so the text is escaped rather than
    # interpolated raw -- a bare `&` in HTML is a malformed entity reference
    # that a copy button would hand the reader back verbatim only by luck.
    install = html.escape(p.get("install", ""))
    inner = ""
    if p["os"] == "linux":
        # data-lg-bind="pkg.install" is LOAD-BEARING and lives on the same
        # element as data-lg-copy: releases.js rebuilds these cards by cloning
        # card zero, and a command without the bind keeps card zero's text --
        # every Linux card then showed the AppImage command. It is also how
        # pass 2 rewrites the filename inside the command when GitHub's
        # published asset name differs from the feed's.
        inner = f"""  <div class="lg-cmdrow">
    <code class="lg-cmd" data-lg-copy data-lg-bind="pkg.install">{install}</code>
    <button class="lg-copy" data-lg-copybtn hidden type="button" aria-label="Copy command">Copy</button>
  </div>"""
    else:
        inner = f'  <p class="lg-pkg-note" data-lg-bind="pkg.install">{install}</p>'
    # A pinned card is excluded from the /api/latest pass: that pass resolves a
    # card against the NEWEST release's assets, and this one deliberately names
    # an older release's file. Without the marker it would find no macOS asset
    # and hide the button -- removing the only macOS download there is.
    pinned = f' data-lg-pinned="{html.escape(p["pinned"])}"' if p.get("pinned") else ""
    ver = (f'<span class="lg-pkg-ver">{html.escape(p["pinned"])}</span>'
           if p.get("pinned") else "")
    return f'''<div data-lg-pkg="{p["os"]}" data-lg-format="{p["format"]}" data-lg-file="{fil}"{match}{pinned} class="lg-pkg">
  <div class="lg-pkg-head">
    <span class="lg-pkg-fmt" data-lg-bind="pkg.format">{html.escape(p["format"])}</span>
    <span class="lg-pkg-label" data-lg-bind="pkg.label">{html.escape(p["label"])}</span>{ver}
    <a class="lg-pkg-dl" data-lg-dl href="{asset_href(fil, p)}">Download</a>
  </div>
{inner}
</div>'''


def cards_for(os_name):
    return "\n".join(pkg_card(p) for p in feed["packages"] if p["os"] == os_name)


def platform_block(os_name, heading, hint, note=""):
    """One <div class="lg-plat">, or NOTHING if the feed has no such package.

    macOS is `allow_failure` in the release pipeline -- deliberately, so one
    sleeping Mac cannot block a release -- and it has already been absent from
    a release for an unrelated reason (the 413 on the artifact upload). A
    hard-coded block would then print an empty "macOS" heading over nothing,
    and its card would link at an asset GitHub never received. The page is
    generated from the feed; a platform the feed does not list is a platform
    the page does not claim.
    """
    cards = cards_for(os_name)
    if not cards:
        return ""
    tail = "\n      " + note if note else ""
    return (f'    <div class="lg-plat">\n'
            f'      <h3>{heading} <span class="hint">{hint}</span></h3>\n'
            f'{cards}{tail}\n'
            f'    </div>')


# The hero claimed "six Linux formats" over FIVE cards: the pipeline builds two
# .debs (Debian and Ubuntu) and the page offers one, so the lane count and the
# download count are different numbers. Counted off the feed, which is what the
# reader can actually see.
_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
          7: "seven", 8: "eight", 9: "nine", 10: "ten"}
_n_linux = sum(1 for p in feed["packages"] if p["os"] == "linux")
LINUX_COUNT_WORD = _WORDS.get(_n_linux, str(_n_linux))

_has_macos = any(p["os"] == "macos" for p in feed["packages"])
_macos_pinned = next((p.get("pinned") for p in feed["packages"]
                      if p["os"] == "macos" and p.get("pinned")), "")
MACOS_LIMIT = (
    f"<b>macOS is not available for {VERSION}.</b> It returns in 0.9.6; the "
    f"download above is {_macos_pinned}. It is effectively untested either "
    "way \u2014 nobody has sat down and used it."
    if _macos_pinned else
    "<b>macOS is effectively untested.</b> It builds and it is published. "
    "Nobody has sat down and used it."
    if _has_macos else
    "<b>There is no macOS download in this release.</b>")

LINUX_BLOCK = platform_block(
    "linux", "Linux",
    "AppImage and Flatpak carry their own Qt and run anywhere",
    '<p class="lg-pkg-note">Needs Qt 6.8+. Neither <code>.deb</code> installs on'
    ' Ubuntu 24.04, Mint 22.x or Pop!_OS 24.04, nor the <code>.rpm</code> on'
    ' Fedora 43 \u2014 older Qt. Use the AppImage or the Flatpak there; both'
    ' carry their own.</p>')
WINDOWS_BLOCK = platform_block(
    "windows", "Windows", "unsigned \u2014 Windows will warn you")
_macos_note = feed.get("macos_note", "")
MACOS_BLOCK = platform_block(
    "macos", "macOS", "Apple Silicon, macOS 26+, ad-hoc signed",
    f'<p class="lg-pkg-note">{html.escape(_macos_note)}</p>' if _macos_note else "")

LD = {
    "@context": "https://schema.org", "@type": "SoftwareApplication",
    "name": "Lightning", "url": "https://www.lightning-matrix.org/",
    "applicationCategory": "CommunicationApplication",
    "applicationSubCategory": "Matrix client",
    "operatingSystem": "Linux, Windows, macOS",
    "softwareVersion": VERSION, "softwareRequirements": "Qt 6.8 or later",
    "license": "https://www.gnu.org/licenses/gpl-3.0.html",
    "isAccessibleForFree": True,
    "description": ("A native Matrix desktop client written in Qt 6 on top of "
                    "the official Rust Matrix SDK, with group calls, threads, "
                    "Spaces and search inside encrypted rooms."),
    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
    "sameAs": ["https://github.com/Mizerd/lightning"],
    "codeRepository": "https://github.com/Mizerd/lightning",
    "screenshot": [f"https://www.lightning-matrix.org/assets/shots/{n}--{DEFAULT_THEME}.png"
                   for n in SHOTS],
    "author": {"@type": "Person", "name": "Rokas Smetonis"},
}

CSS = """
/* ---- tokens, read from qml/AppTheme.qml ---------------------------------
   Surfaces are Indigo Night, the app's flagship dark theme since 2026-08-25.
   The accent is Storm's bolt, which is also the logo's gold -- and it is the
   only palette in this category nobody else owns.

   Surfaces are separated by a HAIRLINE, not a fill step. AppTheme records
   that Indigo's page-to-raised ladder is only 1.156:1 and that a sub-1.25
   ladder was a defect they had to rebuild Storm to fix; repeating it here
   would repeat the bug. */
:root {
  /* Indigo Night, the default -- the SAME values theme_css() emits for it, so
     a page whose JavaScript never runs still has the right colours. The two
     are generated from one source; do not edit either by hand. */
{INDIGO_TOKENS}
  --bolt:     #FFD447;   /* _stoBolt -- the brand accent and the logo's gold */
  --bolt-ink: #0A0F24;   /* _stoBoltInk */
  --card:     var(--elevated);
  --r-sm: 4px; --r-md: 8px; --r-lg: 12px; --r-pill: 999px;
}
/* Every theme, from the client's own palettes. Clicking a swatch sets
   data-theme on <html>; nothing else on the page needs to know. */
{THEME_CSS}
/* The tokens are what change; everything below reads them, so a theme switch
   is one attribute write and no reflow of anything structural. */
html { transition: background-color 260ms ease; }
body, .lg-pkg, .lg-shot-btn, .lg-swatch, .lg-btn, .lg-card {
  transition: background-color 260ms ease, border-color 260ms ease,
              color 260ms ease;
}
@media (prefers-reduced-motion: reduce) {
  html, body, .lg-pkg, .lg-shot-btn, .lg-swatch, .lg-btn, .lg-card {
    transition: none;
  }
}

*, *::before, *::after { box-sizing: border-box; }
[hidden] { display: none !important; }

html { -webkit-text-size-adjust: 100%; }
html, body { overflow-x: clip; }
body {
  margin: 0;
  position: relative;   /* the containing block for .lg-sky */
  background: var(--page);
  color: var(--text);
  font-family: 'Manrope', system-ui, -apple-system, 'Segoe UI', sans-serif;
  font-size: 16px;
  line-height: 1.6;
  font-weight: 400;
}
img { max-width: 100%; height: auto; display: block; }
a { color: var(--link); text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { color: var(--text); }
code, kbd, .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; }

/* One visible focus treatment, and it is the app's: the bolt. */
:focus-visible { outline: 2px solid var(--bolt); outline-offset: 2px; border-radius: var(--r-sm); }

.wrap { width: 100%; max-width: 1080px; margin: 0 auto; padding: 0 24px; }

/* ---- the sky ---------------------------------------------------------------
   Fixed behind everything, pointer-transparent, and coloured by currentColor
   so it inverts with the theme instead of being pale dust on the light three.
   Low enough that you notice it only once you look for it. */
.lg-sky {
  /* ABSOLUTE, not fixed, and stretched over the whole document by top/bottom
     rather than a percentage height (body's height is auto, so a percentage
     would not resolve). Being part of the document is what makes the stars
     move EXACTLY as far as the page does -- a fixed layer dragged along by a
     scroll handler always lags or leads, and reads as the background being out
     of sync rather than as depth. It also needs no JavaScript at all. */
  position: absolute; left: 0; right: 0; top: 0; bottom: 0;
  z-index: 0; pointer-events: none;
  color: var(--text);
  /* Per theme: the light palettes need roughly double. A dark dot at 16% on a
     cream ground is a smudge -- the stars were being swallowed exactly where
     the ground is brightest. */
  opacity: var(--sky-opacity, 0.16);
}
.lg-sky circle { fill: currentColor; }
.lg-sky line { stroke: currentColor; stroke-width: 0.5; opacity: 0.45; }
.lg-sky-mark { fill: var(--accent); opacity: 0.9; }
/* Everything real sits above it. */
.lg-top, main, footer { position: relative; z-index: 1; }

/* ---- header --------------------------------------------------------------- */
.lg-top {
  border-bottom: 1px solid var(--hairline);
  position: sticky; top: 0; z-index: 20;
  background: color-mix(in srgb, var(--page) 92%, transparent);
}
.lg-top .wrap { display: flex; align-items: center; gap: 20px; height: 58px; }
.lg-brand { display: flex; align-items: center; gap: 9px; font-weight: 700; color: var(--text); text-decoration: none; }
.lg-brand img { width: 20px; height: 20px; }
.lg-nav { margin-left: auto; display: flex; align-items: center; gap: 22px; }
.lg-nav a { color: var(--text-2); text-decoration: none; font-size: 14px; font-weight: 500; }
.lg-nav a:hover { color: var(--text); }
/* Source is the only item here that LEAVES the site -- the other four are
   in-page anchors -- and nothing said so. The mark names the destination
   rather than decorating the word; the negative margin keeps the pill from
   changing the header's height. */
.lg-nav a.lg-src {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 5px 11px; margin: -5px 0;
  border: 1px solid var(--border); border-radius: var(--r-pill);
}
.lg-nav a.lg-src:hover { border-color: var(--text-3); }
.lg-nav a.lg-src svg { width: 15px; height: 15px; fill: currentColor; display: block; }

/* ---- hero: copy left, product right, same scroll position ---------------- */
.lg-hero { padding: 72px 0 64px; }
.lg-hero-grid { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1.05fr); gap: 48px; align-items: center; }
.lg-chip {
  display: inline-flex; align-items: center; gap: 9px;
  font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-3);
}
.lg-chip .dot { width: 6px; height: 6px; border-radius: var(--r-pill); background: var(--bolt); }
.lg-chip a { color: var(--text-3); }
.lg-chip a:hover { color: var(--text); }
h1 {
  margin: 18px 0 0;
  font-size: clamp(34px, 4.2vw, 46px);
  line-height: 1.08;
  letter-spacing: -0.02em;
  font-weight: 600;
}
h1 .l2 { display: block; color: var(--text-2); }
.lg-sub { margin: 18px 0 0; font-size: 18px; color: var(--text-2); max-width: 46ch; }
.lg-cta { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }
.lg-btn {
  display: inline-flex; align-items: center; gap: 9px;
  padding: 10px 16px; border-radius: var(--r-md);
  font-size: 14px; font-weight: 600; text-decoration: none;
  border: 1px solid var(--border); color: var(--text); background: var(--raised);
  transition: border-color 120ms ease, color 120ms ease, background 120ms ease;
}
.lg-btn:hover { border-color: var(--text-3); color: var(--text); }
/* The ONE primary action on the page carries the accent. */
.lg-btn.primary { background: var(--bolt); border-color: var(--bolt); color: var(--bolt-ink); }
.lg-btn.primary:hover { background: #FFDE6E; border-color: #FFDE6E; color: var(--bolt-ink); }
.lg-meta { margin-top: 22px; font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-3); }

/* ---- sections ------------------------------------------------------------- */
section { padding: 64px 0; border-top: 1px solid var(--hairline); }
h2 { margin: 0; font-size: 28px; line-height: 1.2; letter-spacing: -0.02em; font-weight: 600; }
.lg-lede { margin: 14px 0 0; color: var(--text-2); max-width: 62ch; }
h3 { margin: 0; font-size: 18px; font-weight: 600; }

/* ---- the stack diagram: mono is legitimate here -------------------------- */
.lg-stack {
  margin-top: 28px; padding: 22px 24px;
  border: 1px solid var(--border); border-radius: var(--r-lg); background: var(--raised);
  font-family: 'JetBrains Mono', monospace; font-size: 13px; line-height: 2;
  color: var(--text-2); overflow-x: auto;
}
.lg-stack b { color: var(--text); font-weight: 500; }
.lg-stack .k { color: var(--bolt); }
.lg-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 28px; margin-top: 28px; }
.lg-cols p { margin: 8px 0 0; color: var(--text-2); font-size: 14px; }

/* ---- alternating feature rows -------------------------------------------- */
.lg-row { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1.15fr); gap: 40px; align-items: center; margin-top: 44px; }
.lg-row:nth-child(even) .lg-row-copy { order: 2; }
.lg-row p { margin: 10px 0 0; color: var(--text-2); font-size: 15px; }

/* ---- screenshots ---------------------------------------------------------- */
.lg-shot { margin: 0; }
.lg-shot-btn {
  display: block; width: 100%; padding: 0; cursor: zoom-in;
  background: var(--raised); border: 3px solid var(--border); border-radius: var(--r-lg);
  overflow: hidden; position: relative;
  /* A screenshot of a dark UI on a dark page has no edge of its own, and on
     the light palettes the pale chrome dissolves into the ground. The frame
     is the edge. 3px reads as a deliberate mount rather than a hairline that
     lost an argument with the background. */
  box-shadow: 0 1px 0 color-mix(in srgb, var(--text) 8%, transparent) inset;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}
.lg-shot-btn:hover { border-color: var(--text-3); }
.lg-zoomhint {
  position: absolute; right: 10px; bottom: 10px;
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
  padding: 3px 8px; border-radius: var(--r-sm);
  background: color-mix(in srgb, var(--page) 86%, transparent);
  color: var(--text-2); border: 1px solid var(--border);
}

/* ---- themes --------------------------------------------------------------- */
.lg-swatches { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 26px; }
/* Each swatch is painted in ITS OWN theme's colours, so the row reads as
   eleven miniature themes rather than eleven labels. That is the affordance:
   you can see they are different things and that one of them is currently on,
   without a word of instruction. */
.lg-swatch {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 7px 12px 7px 8px; border-radius: var(--r-pill);
  border: 1px solid var(--border); background: var(--raised);
  font-size: 13px; color: var(--text-2); font-family: inherit;
  cursor: pointer; position: relative;
  transition: transform 160ms cubic-bezier(0.2,0.7,0.3,1),
              box-shadow 160ms ease, border-color 160ms ease;
}
/* The lift. Commet's author bubbles do this and it is the whole reason a
   static chip reads as pressable: it moves before you commit to it. */
.lg-swatch:hover { transform: translateY(-3px); }
.lg-swatch:active { transform: translateY(-1px); }
.lg-swatch:focus-visible { outline: 2px solid var(--link); outline-offset: 2px; }
.lg-swatch i {
  width: 12px; height: 12px; border-radius: var(--r-pill); display: block;
  transition: transform 160ms cubic-bezier(0.2,0.7,0.3,1);
}
.lg-swatch:hover i { transform: scale(1.35); }
/* The one that is on. A ring rather than a tick, so it reads at a glance
   across eleven of them. */
.lg-swatch[aria-pressed="true"] { box-shadow: 0 0 0 2px var(--sw-accent); }

/* ---- downloads ------------------------------------------------------------ */
.lg-relhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 14px; margin-top: 22px;
  font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--text-3); }
.lg-relhead .v { color: var(--text); font-size: 16px; font-weight: 500; }
.lg-plat { margin-top: 38px; }
.lg-plat > h3 { display: flex; align-items: baseline; gap: 10px; }
.lg-plat > h3 .hint { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-3); font-weight: 400; }
.lg-pkg { border: 1px solid var(--border); border-radius: var(--r-lg); background: var(--raised); padding: 16px 18px; margin-top: 12px; }
.lg-pkg-head { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.lg-pkg-fmt { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text); border: 1px solid var(--border); border-radius: var(--r-sm); padding: 2px 7px; }
.lg-pkg-label { color: var(--text-2); font-size: 14px; }
.lg-pkg-ver { font-family: 'JetBrains Mono', monospace; font-size: 11.5px;
  color: var(--text-3); border: 1px solid var(--hairline);
  border-radius: var(--r-sm); padding: 1px 6px; }
.lg-pkg-dl { margin-left: auto; font-size: 13px; font-weight: 600; text-decoration: none; color: var(--link); white-space: nowrap; }
.lg-pkg-dl:hover { color: var(--text); }
.lg-pkg-note { margin: 10px 0 0; color: var(--text-3); font-size: 13px; }
.lg-cmdrow { display: flex; align-items: stretch; gap: 8px; margin-top: 12px; }
.lg-cmd {
  flex: 1; min-width: 0; overflow-x: auto; white-space: pre;
  background: var(--page); border: 1px solid var(--hairline); border-radius: var(--r-md);
  padding: 9px 12px; font-size: 12.5px; color: var(--text-2);
}
/* The command overflows on any narrow window, and a default scrollbar there
   is a bright white bar across a dark card -- the single loudest thing on the
   page at 390px. Both spellings, because Firefox has no ::-webkit-scrollbar
   and WebKit/Blink ignored scrollbar-color until recently. */
.lg-cmd { scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
.lg-cmd::-webkit-scrollbar { height: 8px; }
.lg-cmd::-webkit-scrollbar-track { background: transparent; }
.lg-cmd::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
.lg-cmd::-webkit-scrollbar-thumb:hover { background: var(--text-3); }
/* 500, not 600: JetBrains Mono is self-hosted at 400/500/700 ONLY, and a
   weight with no @font-face renders as NOTHING here -- the button was an empty
   rounded rectangle on the live page while its DOM said "Copy" the whole time.
   tools/check.py now compares every declared weight against the faces. */
.lg-copy {
  border: 1px solid var(--border); background: var(--raised); color: var(--text-2);
  border-radius: var(--r-md); padding: 0 12px; font-size: 12px; font-weight: 500; cursor: pointer;
  font-family: 'JetBrains Mono', monospace;
  transition: border-color 120ms ease, color 120ms ease;
}
.lg-copy:hover { border-color: var(--text-3); color: var(--text); }

/* ---- the room --------------------------------------------------------------
   One card, not a section: it is an invitation, not a chapter. It renders only
   when releases.json carries a `support` block -- an address is not something
   this generator may invent, and a dead matrix.to link is worse than no card. */
.lg-room {
  margin-top: 40px; padding: 24px 26px;
  border: 1px solid var(--border); border-radius: var(--r-lg);
  background: var(--raised);
  display: flex; align-items: center; gap: 22px; flex-wrap: wrap;
}
.lg-room-body { flex: 1 1 320px; min-width: 0; }
.lg-room h3 { margin: 0; font-size: 19px; font-weight: 600; letter-spacing: -0.01em; }
.lg-room p { margin: 7px 0 0; color: var(--text-2); font-size: 15px; }
.lg-room .alias {
  display: inline-block; margin-top: 10px;
  font-family: 'JetBrains Mono', monospace; font-size: 12.5px; color: var(--text-3);
}
.lg-room-join {
  flex: none; padding: 11px 20px; border-radius: var(--r-pill);
  background: var(--bolt); color: var(--bolt-ink);
  font-weight: 700; font-size: 14.5px; text-decoration: none;
  transition: transform 160ms cubic-bezier(0.2,0.7,0.3,1), filter 160ms ease;
}
.lg-room-join:hover { transform: translateY(-2px); filter: brightness(1.06); }
@media (max-width: 860px) { .lg-room { gap: 16px; } }

/* ---- limits and privacy --------------------------------------------------- */
.lg-list { margin: 26px 0 0; padding: 0; list-style: none; }
.lg-list li { padding-left: 20px; position: relative; margin-top: 14px; color: var(--text-2); }
.lg-list li::before { content: ""; position: absolute; left: 0; top: 11px; width: 7px; height: 1px; background: var(--bolt); }
.lg-list b { color: var(--text); font-weight: 600; }

/* ---- footer --------------------------------------------------------------- */
footer { border-top: 1px solid var(--hairline); padding: 44px 0 60px; color: var(--text-3); font-size: 13px; }
.lg-flinks { display: flex; flex-wrap: wrap; gap: 20px; }
.lg-colophon { margin: 26px 0 0; max-width: 66ch; line-height: 1.75; }
.lg-colophon code { font-size: 12px; color: var(--text-2); }

/* ---- lightbox ------------------------------------------------------------- */
.lg-lightbox {
  position: fixed; inset: 0; z-index: 50; display: flex; align-items: center; justify-content: center;
  background: color-mix(in srgb, var(--page) 94%, #000);
  padding: 28px; cursor: zoom-out;
}
.lg-lightbox img { max-width: 100%; max-height: 100%; border-radius: var(--r-md); }

@media (max-width: 860px) {
  .lg-hero-grid, .lg-row { grid-template-columns: 1fr; gap: 28px; }
  /* Commet's move: on a narrow screen the product arrives before the words. */
  .lg-hero-grid .lg-shot { order: -1; }
  .lg-row:nth-child(even) .lg-row-copy { order: 0; }
  .lg-nav { display: none; }
  .lg-hero { padding: 44px 0 40px; }
  section { padding: 48px 0; }
}
"""


def indigo_tokens():
    """The default theme's tokens, indented for the :root block."""
    k = next(t["tokens"] for t in THEMES_DATA if t["name"] == "Indigo Night")
    pad = "  "
    lines = [f"{pad}--{tok}: {k[tok]};" for tok in
             ("page", "raised", "elevated", "hairline", "border",
              "text", "text-2", "text-3", "accent", "link")]
    lines.append(f"{pad}color-scheme: {'dark' if k['dark'] else 'light'};")
    lines.append(f"{pad}--sky-opacity: {0.16 if k["dark"] else 0.46};")
    return "\n".join(lines)


CSS = (CSS.replace("{INDIGO_TOKENS}", indigo_tokens())
          .replace("{THEME_CSS}", theme_css()))

def sky_svg():
    """The constellation layer: a fixed, seeded starfield behind the page.

    SEEDED, so the layout is identical on every build. A random one would make
    every rebuild a noisy diff of meaningless coordinates, and nobody could
    tell a deliberate change from the generator rolling again.

    It takes its colour from `currentColor`, which is `--text`, so it inverts
    with the theme by itself -- pale stars on the dark palettes, faint ink on
    Warm, Moss Light and Lightning Light. A fixed white starfield would look
    like dust on the light three.

    The ONE accent star is the barely-noticeable detail: a single point in the
    theme's own accent, slightly larger, with a faint halo. Nothing points at
    it and nothing explains it.
    """
    rng = random.Random(0x11667)
    # A TALL field, not a viewport-sized one. The layer spans the whole
    # document now, so the viewBox has to be the document's rough aspect or
    # `slice` would scale a square field up by five and leave a handful of
    # enormous stars. 1000x5000 at ~1400px wide is about right for this page,
    # and the star count scales with the area so the density is unchanged.
    W, H = 1000, 5000
    stars = []
    while len(stars) < 230:
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        # Keep off the centre column where the text lives, so the field reads
        # as sky around the content rather than noise behind it.
        if 300 < x < 700:
            continue
        stars.append((round(x, 1), round(y, 1), round(rng.uniform(0.7, 1.7), 2)))

    # Only SHORT hops, or a link reads as a streak across the page.
    MAX2 = 150 ** 2
    lines = []
    for seed_i in range(4, len(stars), 14):
        a = stars[seed_i]
        near = sorted(stars, key=lambda s: (s[0] - a[0]) ** 2 + (s[1] - a[1]) ** 2)[1:5]
        prev = a
        for b in near:
            if (prev[0] - b[0]) ** 2 + (prev[1] - b[1]) ** 2 > MAX2:
                continue
            lines.append((prev[0], prev[1], b[0], b[1]))
            prev = b

    parts = [f'<svg class="lg-sky" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice" aria-hidden="true">']
    for x1, y1, x2, y2 in lines:
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    for x, y, r in stars:
        parts.append(f'<circle cx="{x}" cy="{y}" r="{r}"/>')
    # The one accent star, a third of the way down where it will be seen.
    ax, ay, _ = stars[70]
    parts.append(f'<circle class="lg-sky-mark" cx="{ax}" cy="{ay}" r="2.6"/>')
    parts.append('</svg>')
    return "".join(parts)

def room_card():
    """The support room, or nothing.

    Driven by a `support` block in releases.json -- alias plus url -- and
    ABSENT when that block is. The generator has no business inventing a room
    address, and a Join button that leads nowhere is worse than a page that
    does not mention a room at all.
    """
    sup = feed.get("support") or {}
    alias, url = sup.get("alias", ""), sup.get("url", "")
    if not (alias and url):
        return ""
    blurb = sup.get("blurb") or ("A chill space. Ask questions, report what broke, "
                                 "or watch the thing get built.")
    return f'''    <div class="lg-room">
      <div class="lg-room-body">
        <h3>{html.escape(sup.get("title", "The Lightning room"))}</h3>
        <p>{html.escape(blurb)}</p>
        <span class="alias">{html.escape(alias)}</span>
      </div>
      <a class="lg-room-join" href="{html.escape(url)}">Join</a>
    </div>'''

def build():
    nl = "\n"
    swatches = nl.join(
        f'  <button type="button" class="lg-swatch" data-lg-theme="{_slug(n)}"'
        f' aria-pressed="{str(_slug(n) == "indigo-night").lower()}"'
        f' style="background:{_tok(n, "raised")};border-color:{_tok(n, "border")};'
        f'color:{_tok(n, "text-2")};--sw-accent:{c}">'
        f'<i style="background:{c}"></i>{n}</button>'
        for n, c in THEMES)

    SKY = sky_svg()
    ROOM_CARD = room_card()
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lightning — a native Matrix client for the desktop</title>
<meta name="description" content="A native desktop Matrix client in Qt 6 and C++20, built on the official Rust Matrix SDK. Group calls with screen sharing, real threads, Spaces, and search inside encrypted rooms. Linux and NixOS first. GPL-3.0-or-later.">
<meta property="og:title" content="Lightning — a native Matrix client for the desktop">
<meta property="og:description" content="Lightning writes the interface. The Rust SDK writes the Matrix. Qt 6, C++20, real end-to-end encryption, group calls that reach Element Call. Linux and NixOS first.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://www.lightning-matrix.org/">
<meta property="og:site_name" content="Lightning">
<meta property="og:image" content="https://www.lightning-matrix.org/assets/og-card.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://www.lightning-matrix.org/">
<link rel="icon" href="/assets/lightning-mark.svg">
<script type="application/ld+json">{json.dumps(LD, separators=(",", ":"))}</script>
<style>
{FONTS}
{CSS}</style>
</head>
<body>
{SKY}

<header class="lg-top">
  <div class="wrap">
    <a class="lg-brand" href="/"><img src="/assets/lightning-mark.svg" alt="">Lightning</a>
    <nav class="lg-nav">
      <a href="#build">How it works</a>
      <a href="#features">Features</a>
      <a href="#download">Download</a>
      <a href="#limits">Limits</a>
      <a class="lg-src" href="https://github.com/Mizerd/lightning"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>Source</a>
    </nav>
  </div>
</header>

<main>

<section class="lg-hero" style="border-top:0">
  <div class="wrap lg-hero-grid">
    <div>
      <p class="lg-chip"><span class="dot"></span>v<span data-lg-bind="version">{VERSION}</span>&nbsp; ·&nbsp; <a href="#limits">alpha</a>&nbsp; ·&nbsp; GPL-3.0-or-later</p>
      <h1>Lightning writes the interface.<span class="l2">The Rust SDK writes the Matrix.</span></h1>
      <p class="lg-sub">A native desktop Matrix client in Qt&nbsp;6 and C++20. Group calls with screen sharing that reach Element Call, real threads, Spaces, and search that works inside encrypted rooms. Linux and NixOS first.</p>
      <div class="lg-cta">
        <a class="lg-btn primary" href="#download">Download <span data-lg-bind="version">{VERSION}</span></a>
        <a class="lg-btn" href="https://github.com/Mizerd/lightning">Read the source</a>
      </div>
      <p class="lg-meta">no telemetry&nbsp; ·&nbsp; no server of ours&nbsp; ·&nbsp; {LINUX_COUNT_WORD}&nbsp;Linux&nbsp;formats</p>
    </div>
    {shot("home-overview", "Lightning showing a room timeline, direct messages and an invite")}
  </div>
</section>

<section id="build">
  <div class="wrap">
    <h2>How it is put together</h2>
    <p class="lg-lede">Most of what a Matrix client gets wrong is cryptography and synchronisation. Lightning writes neither of them.</p>
    <div class="lg-stack">
<b>Qt 6 / QML</b>          <span class="k">interface, layout, themes, accessibility</span><br>
<b>C++20</b>              <span class="k">application state, models, routing, policy</span><br>
<b>matrix-rust-sdk</b>    <span class="k">Matrix, E2EE, sync, threads, media</span><br>
<b>GStreamer</b>          <span class="k">voice, video, screen capture</span>
    </div>
    <div class="lg-cols">
      <div>
        <h3>No cryptography of its own</h3>
        <p>Olm, Megolm, cross-signing, key backup and verification are the official Rust SDK's, through an FFI bridge. Lightning implements none of it and is not permitted to.</p>
      </div>
      <div>
        <h3>Not a webview</h3>
        <p>No Electron, no Chromium, no web frontend in a native window. QML compiled into the binary — no JavaScript engine to boot, no browser to host it.</p>
      </div>
      <div>
        <h3>Calls are native</h3>
        <p>MatrixRTC spoken directly through GStreamer and webrtcbin, not Element Call in a widget. That is what puts a screen share on the GPU.</p>
      </div>
    </div>
  </div>
</section>

<section id="features">
  <div class="wrap">
    <h2>Six things that are unusual</h2>
    <p class="lg-lede">It does the ordinary things too. These are the ones worth a paragraph.</p>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>Group calls, with screen sharing</h3>
        <p>MatrixRTC, interoperable with Element Call. Share a screen or one window, scaled on the GPU. Per-participant volume, raised hands, and a call that survives you reading another room.</p>
      </div>
      {shot("call-grid", "A four-person call in Lightning")}
    </div>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>Search inside encrypted rooms</h3>
        <p>A server cannot search what it cannot read, so Lightning keeps a local index. It is the one place decrypted text is stored on purpose, and it is documented rather than glossed over.</p>
      </div>
      {shot("find-in-room", "Searching inside a room in Lightning")}
    </div>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>Spaces, and a Channels layout</h3>
        <p>Drag Spaces in the rail, drop one on another to make a folder, edit every setting down to the power-level matrix. Or switch to the Channels layout instead.</p>
      </div>
      {shot("community-overview", "A Space and its rooms in Lightning")}
    </div>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>Threads that are actually threads</h3>
        <p>Real <code>m.thread</code> relations on the SDK's own thread timelines, with summary cards and per-thread unread state. Replies never leak into the main timeline — the part most clients get wrong.</p>
      </div>
      {shot("thread-view", "A thread panel open beside a room timeline in Lightning")}
    </div>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>A theme editor, not a theme setting</h3>
        <p>Pick a colour for any part of the window and watch a sample room repaint as you go. Eleven themes ship, all WCAG-AA checked, each one per-account.</p>
      </div>
      {shot("settings-themes", "The appearance settings in Lightning")}
    </div>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>Pictures, video, audio and files</h3>
        <p>Inline images, video with a real poster frame, playable voice messages, and attachments that keep their captions. Encrypted rooms included — decrypted through the media bridge, never a bare URL.</p>
      </div>
      {shot("media-gallery", "Images, video and files in a Lightning room")}
    </div>
  </div>
</section>

<section id="themes">
  <div class="wrap">
    <h2>Eleven themes</h2>
    <p class="lg-lede">Every one is the client's own palette, read from its own theme file. Pick one and the page repaints.</p>
    <div class="lg-swatches">
{swatches}
    </div>
  </div>
</section>

<section id="download">
  <div class="wrap">
    <h2>Download</h2>
    <p class="lg-relhead">
      <span class="v">{VERSION}</span>
      <span data-lg-bind="released">{RELEASED}</span>
      <a href="{RELEASES_URL}" data-lg-href="releasesUrl">Release notes →</a>
    </p>

{LINUX_BLOCK}

{WINDOWS_BLOCK}

{MACOS_BLOCK}

    <p class="lg-pkg-note">Every release ships <code>SHA256SUMS</code>, and the updater's manifest is signed.</p>
{ROOM_CARD}
  </div>
</section>

<section id="limits">
  <div class="wrap">
    <h2>What it cannot do yet</h2>
    <p class="lg-lede">Alpha. This is the same list the project keeps for itself.</p>
    <ul class="lg-list">
      <li>{MACOS_LIMIT}</li>
      <li><b>Nobody has listened to a call.</b> Audio provably reaches the far end and the audio engine. No human has confirmed it sounds like anything.</li>
      <li><b>Recovery and key backup are verified by reading the code, not by using it.</b> Exercising it puts a recovery key on screen. Four known rough edges are in the release notes.</li>
      <li><b>Screen sharing and the camera are untested on the Snap</b> — no desktop portal on the test machine.</li>
      <li><b>Some distributions ship a Qt too old for the native packages.</b> Named above.</li>
    </ul>
  </div>
</section>

<section id="privacy">
  <div class="wrap">
    <h2>Privacy, checkably</h2>
    <p class="lg-lede">Each names the thing that implements it, so it can be checked.</p>
    <ul class="lg-list">
      <li><b>No telemetry, no analytics, no crash reporting.</b> It talks to your homeserver, and to the release server when checking for updates — a version number, nothing else.</li>
      <li><b>Message content is stored on your disk unencrypted.</b> Decrypted text sits in the SDK cache and the search index as plain SQLite in your account directory — your user only, deleted with the account. Full-disk encryption is what protects it today. An encrypted store is open work, not a feature.</li>
      <li><b>Keys, tokens, recovery keys and message bodies never reach the logs.</b> Copyable diagnostics carry hashed identifiers and no paths.</li>
      <li><b>Access tokens go to your OS secret service</b> — libsecret, Windows Credential Manager — with a flagged insecure fallback where there is none.</li>
      <li><b>GIF search is the one thing that leaves.</b> Your search term goes to the provider you picked. Nothing else does — no Matrix IDs, no room or event IDs, no message text.</li>
    </ul>
  </div>
</section>

</main>

<footer>
  <div class="wrap">
    <div class="lg-flinks">
      <a href="https://github.com/Mizerd/lightning">Source</a>
      <a href="{RELEASES_URL}">Releases</a>
      <a href="https://github.com/Mizerd/lightning/blob/main/docs/privacy.md">Privacy</a>
      <a href="https://github.com/Mizerd/lightning/issues">Issues</a>
      <a href="https://matrix.org/">What is Matrix?</a>
    </div>
    <p class="lg-colophon">Set in Manrope and JetBrains Mono, the same faces the application bundles. Colours are Indigo Night and Storm, read from <code>qml/AppTheme.qml</code>. Screenshots come from Lightning's own demo mode, generated from fictional <code>*.example</code> accounts so they cannot drift from the client. Built by one person. GPL-3.0-or-later.</p>
  </div>
</footer>

<script src="/releases.js" defer></script>
</body>
</html>
"""
    (PUB / "index.html").write_text(html, encoding="utf-8")
    print("wrote", (PUB / "index.html"), len(html.splitlines()), "lines")


if __name__ == "__main__":
    build()
