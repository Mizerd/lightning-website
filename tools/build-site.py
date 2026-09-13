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
def _png_size(name):
    with open(PUB / "assets" / name, "rb") as fh:
        return struct.unpack(">II", fh.read(24)[16:24])


SHOTS = {name: _png_size(name) for name in (
    "screenshot-thread-panel.png",
    "screenshot-call.png",
    "screenshot-channels.png",
    "screenshot-timeline.png",
    "screenshot-emoji-and-polls.png",
    "screenshot-theme-editor.png",
)}

# The eleven themes, named as the app names them. The swatch colours are each
# theme's own accent from qml/AppTheme.qml. check.py cannot verify they are
# current -- it can only prove nobody quietly dropped one.
THEMES = [
    ("Indigo Night", "#4A4EED"), ("Moss Light", "#1F7A4C"),
    ("Deep Teal", "#12A594"), ("Storm", "#FFD447"),
    ("Lightning Light", "#3B7FF0"), ("Lightning Dark", "#5B8DEF"),
    ("Graphite", "#7C8497"), ("Midnight", "#4C6FFF"),
    ("Nordic", "#5E81AC"), ("Purple Dusk", "#9D7CD8"),
    ("Warm", "#D98A4B"),
]


def shot(name, alt, cls=""):
    w, h = SHOTS[name]
    extra = f" {cls}" if cls else ""
    return f'''<figure class="lg-shot{extra}">
  <button class="lg-shot-btn" data-lg-zoom type="button" aria-label="Open {alt} full size">
    <img src="/assets/{name}" alt="{alt}" width="{w}" height="{h}" loading="lazy" decoding="async">
    <span class="lg-zoomhint" data-lg-zoomhint hidden>Expand</span>
  </button>
</figure>'''


ASSET = feed["asset_url"]


def asset_href(fil):
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
    return f'''<div data-lg-pkg="{p["os"]}" data-lg-format="{p["format"]}" data-lg-file="{fil}"{match} class="lg-pkg">
  <div class="lg-pkg-head">
    <span class="lg-pkg-fmt" data-lg-bind="pkg.format">{html.escape(p["format"])}</span>
    <span class="lg-pkg-label" data-lg-bind="pkg.label">{html.escape(p["label"])}</span>
    <a class="lg-pkg-dl" data-lg-dl href="{asset_href(fil)}">Download</a>
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
MACOS_LIMIT = (
    "<b>macOS is effectively untested.</b> It builds and it is published. "
    "Nobody has sat down and used it."
    if _has_macos else
    "<b>There is no macOS download in this release.</b> The bundle builds and "
    "passes its checks on a real Mac; uploading it to the release server does "
    "not. It would be effectively untested in any case \u2014 nobody has sat "
    "down and used it.")

LINUX_BLOCK = platform_block(
    "linux", "Linux",
    "AppImage and Flatpak carry their own Qt and run anywhere",
    '<p class="lg-pkg-note">Lightning needs Qt 6.8 or newer. The <code>.deb</code>'
    ' will not install on Ubuntu 24.04, Mint 22.x or Pop!_OS 24.04, and the'
    ' <code>.rpm</code> will not on Fedora 43 \u2014 their Qt is older than that.'
    ' Use the AppImage or the Flatpak there.</p>')
WINDOWS_BLOCK = platform_block(
    "windows", "Windows", "unsigned \u2014 Windows will warn you")
MACOS_BLOCK = platform_block(
    "macos", "macOS", "Apple Silicon, macOS 26+, ad-hoc signed")

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
    "screenshot": [f"https://www.lightning-matrix.org/assets/{n}" for n in SHOTS],
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
  --page:     #0E0E14;   /* _indRail */
  --raised:   #1F1D26;   /* _indBg */
  --card:     #2A2833;
  --hairline: #2A2733;
  --border:   #423E4E;   /* _indBorder */
  --text:     #E8E8EF;   /* _indTextPrimary */
  --text-2:   #A4A6B8;   /* _indTextSecondary */
  --text-3:   #8A8C9E;   /* lifted from _indTextDisabled to clear AA */
  --bolt:     #FFD447;   /* _stoBolt -- the brand accent and the logo's gold */
  --bolt-ink: #0A0F24;   /* _stoBoltInk */
  --link:     #93C5FD;   /* _indLink. NOT the accent: white-on-accent is
                            pinned at 3:1, which caps the accent's luminance
                            below what an AA link needs. The app hit this and
                            gave links their own ink; so does this page. */
  --r-sm: 4px; --r-md: 8px; --r-lg: 12px; --r-pill: 999px;
  color-scheme: dark;
}

*, *::before, *::after { box-sizing: border-box; }
[hidden] { display: none !important; }

html { -webkit-text-size-adjust: 100%; }
html, body { overflow-x: clip; }
body {
  margin: 0;
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

/* ---- header --------------------------------------------------------------- */
.lg-top {
  border-bottom: 1px solid var(--hairline);
  position: sticky; top: 0; z-index: 20;
  background: rgba(14,14,20,0.92);
}
.lg-top .wrap { display: flex; align-items: center; gap: 20px; height: 58px; }
.lg-brand { display: flex; align-items: center; gap: 9px; font-weight: 700; color: var(--text); text-decoration: none; }
.lg-brand img { width: 20px; height: 20px; }
.lg-nav { margin-left: auto; display: flex; gap: 22px; }
.lg-nav a { color: var(--text-2); text-decoration: none; font-size: 14px; font-weight: 500; }
.lg-nav a:hover { color: var(--text); }

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
.lg-btn kbd {
  font-size: 11px; padding: 1px 5px; border-radius: var(--r-sm);
  border: 1px solid currentColor; opacity: 0.55; font-weight: 500;
}
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
  background: var(--raised); border: 1px solid var(--border); border-radius: var(--r-lg);
  overflow: hidden; position: relative;
  transition: border-color 120ms ease;
}
.lg-shot-btn:hover { border-color: var(--text-3); }
.lg-zoomhint {
  position: absolute; right: 10px; bottom: 10px;
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
  padding: 3px 8px; border-radius: var(--r-sm);
  background: rgba(14,14,20,0.86); color: var(--text-2); border: 1px solid var(--border);
}

/* ---- themes --------------------------------------------------------------- */
.lg-swatches { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 26px; }
.lg-swatch {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 7px 12px 7px 8px; border-radius: var(--r-pill);
  border: 1px solid var(--border); background: var(--raised);
  font-size: 13px; color: var(--text-2);
}
.lg-swatch i { width: 12px; height: 12px; border-radius: var(--r-pill); display: block; }

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
  background: rgba(8,8,12,0.94); padding: 28px; cursor: zoom-out;
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


def build():
    nl = "\n"
    swatches = nl.join(
        f'  <span class="lg-swatch"><i style="background:{c}"></i>{n}</span>'
        for n, c in THEMES)

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
<meta property="og:image" content="https://www.lightning-matrix.org/assets/og-card.png">
<link rel="canonical" href="https://www.lightning-matrix.org/">
<link rel="icon" href="/assets/lightning-mark.svg">
<script type="application/ld+json">{json.dumps(LD, separators=(",", ":"))}</script>
<style>
{FONTS}
{CSS}</style>
</head>
<body>

<header class="lg-top">
  <div class="wrap">
    <a class="lg-brand" href="/"><img src="/assets/lightning-mark.svg" alt="">Lightning</a>
    <nav class="lg-nav">
      <a href="#build">How it works</a>
      <a href="#features">Features</a>
      <a href="#download">Download</a>
      <a href="#limits">Limits</a>
      <a href="https://github.com/Mizerd/lightning">Source</a>
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
        <a class="lg-btn primary" href="#download">Download <span data-lg-bind="version">{VERSION}</span> <kbd>D</kbd></a>
        <a class="lg-btn" href="https://github.com/Mizerd/lightning">Read the source <kbd>S</kbd></a>
      </div>
      <p class="lg-meta">no telemetry&nbsp; ·&nbsp; no server of ours&nbsp; ·&nbsp; {LINUX_COUNT_WORD}&nbsp;Linux&nbsp;formats</p>
    </div>
    {shot("screenshot-thread-panel.png", "Lightning showing a room timeline with a thread panel open")}
  </div>
</section>

<section id="build">
  <div class="wrap">
    <h2>How it is put together</h2>
    <p class="lg-lede">Most of what a Matrix client gets wrong is cryptography and synchronisation. Lightning writes neither.</p>
    <div class="lg-stack">
<b>Qt 6 / QML</b>          <span class="k">interface, layout, themes, accessibility</span><br>
<b>C++20</b>              <span class="k">application state, models, routing, policy</span><br>
<b>matrix-rust-sdk</b>    <span class="k">Matrix, E2EE, sync, threads, media</span><br>
<b>GStreamer</b>          <span class="k">voice, video, screen capture</span>
    </div>
    <div class="lg-cols">
      <div>
        <h3>No cryptography of its own</h3>
        <p>Olm, Megolm, cross-signing, key backup and verification are the official Rust SDK's, called through an FFI bridge. Lightning implements none of it and is not permitted to — the rule is written into the project's own development guide.</p>
      </div>
      <div>
        <h3>Not a webview</h3>
        <p>No Electron, no Chromium, no web frontend in a native window. The interface is QML compiled into the binary — no JavaScript engine to boot, no browser to host it — which is why it looks and behaves like the rest of your desktop.</p>
      </div>
      <div>
        <h3>Calls are native</h3>
        <p>MatrixRTC is spoken directly through GStreamer and webrtcbin rather than by embedding Element Call in a widget. That is what lets a screen share run on the GPU and a call survive on a laptop.</p>
      </div>
    </div>
  </div>
</section>

<section id="features">
  <div class="wrap">
    <h2>Five things that are unusual</h2>
    <p class="lg-lede">Not a feature list — the client does the ordinary things too. These are the ones worth the paragraph.</p>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>Group calls, with screen sharing</h3>
        <p>Voice and video over MatrixRTC, interoperable with Element Call. Share a whole screen or one window; the scaling runs on the GPU. Per-participant volume, raise-hand, and a call that keeps running while you read another room.</p>
      </div>
      {shot("screenshot-call.png", "A group call in Lightning")}
    </div>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>Search inside encrypted rooms</h3>
        <p>A server cannot search what it cannot read. Lightning keeps a local index so encrypted rooms are searchable at all — the one place it deliberately stores decrypted text, documented in the open rather than glossed over.</p>
      </div>
      {shot("screenshot-timeline.png", "A room timeline in Lightning")}
    </div>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>Spaces, and a Channels layout</h3>
        <p>Spaces in a rail you can drag, drop one onto another to make a folder, and edit properly — name, topic, avatar, join rule, address and the full power-level matrix. Or switch to the Channels layout if that is how your brain works.</p>
      </div>
      {shot("screenshot-channels.png", "The Channels layout in Lightning")}
    </div>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>Threads that are actually threads</h3>
        <p>Real <code>m.thread</code> relations through the SDK's own thread timelines, with summary cards on the root and per-thread unread state. Replies never leak into the main timeline, which is the part most clients get wrong.</p>
      </div>
      {shot("screenshot-emoji-and-polls.png", "Reactions and a poll in Lightning")}
    </div>

    <div class="lg-row">
      <div class="lg-row-copy">
        <h3>A theme editor, not a theme setting</h3>
        <p>Pick a colour for any part of the window and watch a sample room repaint as you go. Eleven themes ship, all checked for WCAG-AA contrast, and each one is per-account.</p>
      </div>
      {shot("screenshot-theme-editor.png", "The theme editor in Lightning")}
    </div>
  </div>
</section>

<section id="themes">
  <div class="wrap">
    <h2>Eleven themes</h2>
    <p class="lg-lede">These swatches are the application's own accents, read from the same file the client reads. The page you are on uses two of them.</p>
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

    <p class="lg-pkg-note">Every release ships a <code>SHA256SUMS</code> file, and the manifest the updater reads is signed.</p>
  </div>
</section>

<section id="limits">
  <div class="wrap">
    <h2>What it cannot do yet</h2>
    <p class="lg-lede">Lightning is alpha. This section is part of the pitch, not a disclaimer under it — it is the same list the project keeps for itself.</p>
    <ul class="lg-list">
      <li>{MACOS_LIMIT}</li>
      <li><b>Nobody has listened to a call.</b> Audio is proven to flow both ways and to reach the audio engine; no human has confirmed it sounds like anything.</li>
      <li><b>Recovery and key backup are verified by reading the code, not by using them.</b> Exercising them puts a recovery key on screen, so the audit is the evidence. Four known rough edges are listed in the release notes.</li>
      <li><b>Screen sharing and the camera are untested on the Snap</b> — the test machine has no desktop portal for a confined app to talk to.</li>
      <li><b>Some distributions ship a Qt too old for the native packages.</b> Named above, with the versions.</li>
    </ul>
  </div>
</section>

<section id="privacy">
  <div class="wrap">
    <h2>Privacy, checkably</h2>
    <p class="lg-lede">Each of these names the thing that implements it, so it can be checked — and shown to be wrong if it ever drifts.</p>
    <ul class="lg-list">
      <li><b>No telemetry, no analytics, no crash reporting.</b> Lightning talks to your homeserver, and to our release server when it checks for an update — that request carries a version number and nothing else.</li>
      <li><b>Message content is stored on your disk unencrypted.</b> Once the SDK decrypts a message it keeps the plain text in its cache and in the search index, as plain SQLite in your account's directory — readable only by your user, deleted with the account. Full-disk encryption is what protects it at rest today. An encrypted store is open work, not a shipped feature.</li>
      <li><b>Keys, tokens, recovery keys and message bodies never reach the logs.</b> The diagnostics you can copy out carry hashed account identifiers and no paths.</li>
      <li><b>Access tokens go to your OS secret service</b> — libsecret, Windows Credential Manager — with a clearly flagged insecure fallback where there is none.</li>
      <li><b>GIF search is the one thing that leaves.</b> Your search term goes to the provider you picked, and nothing else does: no Matrix IDs, no room or event IDs, no message text.</li>
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
