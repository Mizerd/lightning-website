# lightning-website

The official website for [Lightning](https://github.com/Mizerd/lightning),
a native Matrix desktop client for Linux and Windows.

Live at **https://www.lightning-matrix.org**, hosted on Cloudflare Workers.

It is a single static page. There is no build step, no framework and no
JavaScript required to read it — one optional 70-line script keeps a deployed
page in step with `releases.json`.

## Layout

```
public/              <- everything Cloudflare serves (the assets directory)
  index.html         <- the site; hand-editable
  releases.json      <- the release feed; edit this to cut a release
  releases.js        <- optional: refreshes a live page from releases.json
  motion.js          <- optional: scroll state, nav marker, pointer, reveals
  404.html
  robots.txt
  sitemap.xml
  _headers           <- Cloudflare: CSP, security headers, cache policy
  _redirects         <- Cloudflare: same-site path redirects (relative URLs only)
  assets/
    lightning-mark.svg
    screenshot-*.png
    og-card.png        <- 1200x630 link preview; source in tools/og-card.html
  fonts/*.woff2      <- Manrope, JetBrains Mono, Space Grotesk (self-hosted)

wrangler.jsonc       <- Cloudflare config: serve public/, 404.html on miss
src/
  worker.js          <- one route, GET /api/latest (newest release from GitHub)
artifact/
  Lightning.html     <- the original Claude artifact this site was built from
tools/
  unbundle.py        <- converts that artifact into public/
  check.py           <- invariant checks; run after editing public/
  og-card.html       <- source for assets/og-card.png; NOT deployed
  lightbox-test.js   <- jsdom test for the screenshot overlay (needs jsdom)
```

Nothing outside `public/` is deployed.

## Cutting a release

Edit **`public/releases.json`** and push. That is the whole procedure — the
version, release date, and every package card on the page come from that file.

```jsonc
{
  "version":  "0.7.5",
  "released": "2026-09-01",          // ISO date, shown as "Released ..."
  "releases_url": "https://github.com/Mizerd/lightning/releases",
  "donate_url":   "",                // empty hides the Donate button
  "asset_url": "https://github.com/Mizerd/lightning/releases/download/v${version}/${file}",
  "packages": [
    { "os": "linux", "label": "...", "format": ".deb",
      "file": "lightning_0.7.5_amd64.deb",
      "install": "sudo apt install ./lightning_0.7.5_amd64.deb",
      "remove": "sudo apt remove lightning" }
  ]
}
```

`os` must be `linux` or `windows`; those two lists become the two download
columns. The Windows filenames embed the build's short commit sha, so they
change every release — copy them from the GitHub release page rather than
editing by hand:

```sh
gh release view v0.7.5 --repo Mizerd/lightning --json assets \
  --jq '.assets[].name'
```

The alpha bar at the top of the page names the version too. It used to read
"0.7.x", which nothing kept current; it is now bound like every other version
on the page, so it follows a release on its own.

`index.html` also ships the current values baked in, so the page is correct
before `releases.js` runs and stays correct if it never does. Those baked-in
values only refresh when the page is rebuilt (below) — for a normal release,
editing `releases.json` alone is enough and the live page follows.

### Download buttons

Every package card has a button pointing straight at its release asset. The URL
comes from the `asset_url` template, with `${version}` and `${file}` filled in,
so no version is written into the HTML.

In practice you may not need to touch anything: **`GET /api/latest` reports
whatever GitHub has actually published, and the page prefers it** over
`releases.json`. Cut a release on GitHub and this site follows within the
route's five-minute cache — the version, the date, every download URL, and the
filenames inside the install commands.

Each card is matched to its asset by file extension (`data-lg-format`), which
works because every release publishes exactly one asset per format. Add a
second `.deb` and the first one wins — give the new one a distinct format if
that ever happens.

The `file` values in `releases.json` are still worth keeping accurate: they are
what a visitor with JavaScript disabled sees, and what the buttons fall back to
if GitHub is unreachable.

### Copy buttons

The Linux install commands each carry a copy button. Windows and macOS get
none — their boxes hold GUI actions ("double-click ..."), not commands.

Three things about it are deliberate. The button is a **sibling** of the
command box rather than a child, so `textContent` yields the command with no
button label mixed in. Clicks are handled by **delegation** on `document`, not
by a listener per button, because `packages()` rebuilds these cards with
`cloneNode` — which does not copy event listeners, so per-button listeners
would die on every rebuild.

And the button is a **flex item beside the box, never an overlay**. The first
version positioned it absolutely over the box and reserved room with
`padding-right`, which does not work: the box scrolls (`white-space: pre`,
`overflow-x: auto`), so that padding sits at the end of the scrollable content
rather than at the right edge of what you can see. The AppImage command — the
longest one — ran straight under the button at scroll position zero. The row
is `flex-wrap: wrap`, so on a phone the button drops to its own line instead
of squeezing the command.

The buttons ship `hidden` and `releases.js` reveals them, so a reader without
JavaScript is never shown a button that cannot work.

### The Donate button

The markup is in `index.html` but is hidden, because there is no donation
account to point it at yet. Put a real URL in `donate_url` and it appears by
itself — no HTML edit. Leaving it empty keeps it hidden and unclickable.

## Editing the page

Edit `public/index.html` directly. It is plain HTML with inline styles.

`tools/unbundle.py` exists only to regenerate the site from a **fresh Claude
artifact**, and it overwrites `public/index.html`:

```sh
python3 tools/unbundle.py                 # reads artifact/Lightning.html
python3 tools/unbundle.py path/to/New.html
```

It will not overwrite `public/releases.json` if one already exists, so a
rebuild never rolls the published version backwards.

The original artifact was a 2.7 MB self-extracting bundle: a base64 manifest
that JavaScript unpacked into `blob:` URLs at runtime, rendered through React
18 and a proprietary `x-dc` runtime. That is ~280 KB of JavaScript to perform
12 string substitutions, and it rendered *nothing at all* without JavaScript.
The script does that work ahead of time instead — unpacking the assets to real
files, expanding the loops, and rewriting `style-hover` attributes into real
CSS `:hover` rules. The published page needs no framework.

## Checking a change

```sh
python3 tools/check.py
```

Verifies the things that have actually broken: every local reference resolves,
every package card has its own button pointing at its own asset, the baked-in
version agrees with `releases.json`, every screenshot declares the size the
file actually is, the theme strip still has eleven swatches, the canonical and
the JSON-LD agree with the page, nothing served mentions GitLab, and
`releases.js` is not cacheable for longer than the HTML it rewrites. Exits
non-zero, so it works in a pre-push hook.

A check that cannot fail is decoration. When adding one, inject the defect it
is meant to catch, watch it fail, then restore — all of the above have been
put through that.

That last check exists because of a real bug. `releases.js` was served with
`max-age=3600` while `index.html` was `must-revalidate`, so a visitor could run
**new HTML against an hour-old script**. The old script rebuilt the package
cards by cloning card zero and knew nothing about the download buttons, so
every clone inherited card zero's href: every Linux button served the `.deb`
and every Windows button the `.msi`. The links in the HTML were all correct —
which is why this could not be found by inspecting the page or the URLs.

The lesson generalises: **any script that rewrites the generated DOM must not
outlive that DOM in a cache.** `releases.js` is now `no-cache`, like
`releases.json`.

`check.py` cannot test the JavaScript paths — those need a DOM. For those:

```sh
npm install jsdom          # not a repo dependency; install where convenient
```

Load `index.html` in jsdom, stub `window.fetch` to return `releases.json` and
`/api/latest`, eval `releases.js`, dispatch `DOMContentLoaded`, then assert
that the eight `[data-lg-pkg]` cards still have eight distinct `href`s. Test
both passes *and* the feed-only path with `/api/latest` failing, since the two
mask each other: the GitHub pass sets every href by format and will paper over
a broken rebuild in the feed pass.

The lightbox is worth testing the same way, and the useful assertions are the
ones about what must *not* happen: clicking the image does not close it, the
overlay is reused rather than rebuilt on the second open, the scroll lock is
released, and focus returns to the screenshot that was clicked.

Anything about **layout** needs a real browser instead — jsdom has none.
Headless Firefox works, with one trap: `--screenshot` fires at the load event,
so a probe on a timer renders nothing. Measure synchronously in an iframe's
`onload` and write the numbers into the page, one page load per viewport
width. Scroll-driven `lgRise` animations also sit at their `from` state
(`opacity: 0`) in a screenshot, so probe pages want
`*{animation:none!important;opacity:1!important}`, and `loading="lazy"`
images never arrive at all — strip it before measuring anything below the
fold.

## GitHub only

The site links to GitHub and names no other host. The project was on a
self-hosted GitLab when the artifact was written, so `unbundle.py` rewrites
every link, button and sentence that referred to it (correction 1), and fails
the build if any survive. `check.py` repeats the check against what is on disk.

If the repository ever moves again, change it in `unbundle.py` — editing
`public/index.html` alone means the next rebuild reinstates the old wording.

## No terminal for Windows or macOS

Linux users get shell commands, because that is how software is installed
there. Windows and macOS users get none: they are GUI users, and a command
prompt is a wall, not an instruction.

This took three fixes. The `.msi` card said `msiexec /i ...` — now
"double-click" (keeping the filename, so `/api/latest` can still rewrite it).
The macOS block is click-by-click. And `sha256sum -c SHA256SUMS` was sitting
in the **Windows** column, which is the one place it cannot run; it moved to
the Linux column, where it is native. What replaced it in the Windows column
says plainly that Windows cannot check a checksum without a command prompt, so
the protection is downloading from the release page and nowhere else — and the
SmartScreen box no longer tells people to "check the checksum" it cannot help
them check.

## macOS

There is no macOS release. The download section carries a "Coming soon" block
with the full Gatekeeper walkthrough for an unsigned app, written as static
copy in `unbundle.py` (correction 6): no package card, no entry in
`releases.json`, so neither `releases.js` nor `/api/latest` touches it.

The walkthrough is the **Open Anyway** route: try to open it and let macOS
refuse, then System Settings → Privacy & Security → Security → *Open Anyway*,
then confirm once. Step 1 is not filler — the button only appears after macOS
has blocked the app at least once. Control-click → Open is mentioned only as
the macOS 14-and-earlier shortcut, since macOS 15 removed it.

When there is a build, it becomes ordinary packages with `"os": "macos"` in
`releases.json` — which also needs a third column in the download grid, since
`packages()` in `releases.js` only rebuilds the `linux` and `windows` lists.

The block promises the app will be unsigned and tells people how to get past
Gatekeeper. That is a real security instruction, so it leads with where to get
the file: someone clicking *Open Anyway* is vouching for the download
themselves.

## The brand

The page pitched "Everything other Matrix clients fake." before it had said
what it was. The name appeared once, at 18 px in the nav; the mark existed as
a 26 px nav icon and a 14 px chip. The hero now opens on a lockup — mark,
wordmark, and the one-line description that was already in `<title>` but
nowhere on the page — and the `<h1>` keeps its job as the pitch, under a name
that now means something.

## Screenshots

The four screenshots are the only photographs on an 8,800 px page, and they
had two problems.

They carried **no `width`/`height`** and are `loading="lazy"`, so until each
file arrived its box was zero pixels tall: the caption sat under nothing and
the grid jumped as the images landed. Correction 12 reads the real dimensions
out of each PNG's IHDR at build time and writes them onto the tag, so the
browser reserves the right shape before a byte is fetched. They are read from
the files rather than typed in because a re-exported screenshot would
otherwise reserve the *wrong* shape, which is worse than reserving none —
`check.py` compares the two.

They also render about 540 px wide from a 3,839 px original, so each is now
wrapped in a `<button data-lg-zoom>` and `releases.js` opens it full screen.

A **button** rather than a click handler on the `<img>`: that way it is in the
tab order, activates on Enter and Space, and is announced as something you can
press. All three are free with a button and all three have to be rebuilt by
hand without one.

Three things about the overlay are load-bearing:

- **The image is the one thing that does not close it.** Everything else does
  — backdrop, caption, close button, Escape. On a phone that is what lets you
  pinch and pan a screenshot without the first touch dismissing it.
- **`cursor: zoom-out` on the backdrop is not decoration.** iOS only
  dispatches `click` for a plain `<div>` when it looks interactive, and a
  cursor is what makes it look interactive. Without it the backdrop swallows
  the tap and nothing closes.
- **`max-height: calc(100dvh - 150px)`, not `100vh`.** On a phone the browser
  chrome counts towards `vh`, so `vh` sizes the image to a viewport taller
  than the one you can see and crops the bottom of it behind the address bar.

The overlay is built once on first use and reused; closing it drops the `src`
so a 3,839 px image is not held decoded for a page you have gone back to
scrolling. Focus moves to the close button on open and returns to the
screenshot on close.

## The theme strip

The page claimed "Eleven themes" in a feature card and "eleven WCAG-AA themes"
in its meta description, and then showed none of them — 8,800 px of one slate
palette and a single blue accent. Correction 13 puts eleven swatches under the
screenshots, each a miniature of the client: rail, two received bubbles, one
sent bubble in the accent.

**The colours are not decorative.** Every value in the `_THEMES` table in
`unbundle.py` is copied from `qml/AppTheme.qml` in the client repo — the
`_light`, `_dark`, `_graphite` … palette objects, resolved through their
colour literals, in `SettingsManager::Theme` enum order. This repository
cannot see that one at build time, so **if a palette changes there it has to
be changed here too.** `check.py` cannot prove they are current; it only
proves nobody quietly dropped one, which is the failure that would leave the
page saying "Eleven themes" above ten swatches.

Eleven is prime, so the grid is set explicitly rather than left to `auto-fit`:
eleven across on desktop, `6 + 5` below 1080 px, `4 + 4 + 3` on a phone.
`auto-fit` gave nine in a row and a stranded pair underneath. The 1080 px rule
needs `!important` for the usual reason — the grid is an inline style on the
element.

## Search engines

Google had already picked **`https://github.com/Mizerd/lightning`** as the
canonical page for this content. That is not a mistake on its part: the domain
used to redirect there, and a redirect is the strongest duplicate signal there
is. The fix is to say the opposite, in every way a crawler reads:

- a self-referencing `<link rel="canonical">` — this URL is the original
- `SoftwareApplication` JSON-LD with **`sameAs`** pointing at the repository —
  the same project, not a competing copy of this page
- `og:url`, `og:site_name`, `twitter:card`, and a real 1200x630 `og:image`

The JSON-LD is a `<script type="application/ld+json">` **data block**, which
is never executed, so `script-src 'self'` does not have to be loosened to
carry it. `releases.js` keeps its `softwareVersion` in step with the rest of
the page, because `data-lg-bind` reaches DOM and this is JSON.

`og:image` was `screenshot-rooms-and-gifs.png`: 3839x2043 and 545 KB, which is
7.8 megapixels for a card rendered about 500 px wide, and past the size some
scrapers will fetch at all. It is now `assets/og-card.png`, 1200x630 and
154 KB. Its source is `tools/og-card.html` — screenshotted in Firefox rather
than drawn in ImageMagick, so the type is the site's own webfonts laid out by
the same engine as the site. That file is a **build input and must not be left
in `public/`**.

Note that `og:image` is referenced by `content=`, not `src=`/`href=`, so the
generic "local references resolve" check never sees it. It has its own check —
a social card that 404s is invisible until someone shares a link and gets a
blank box.

**Two things outside this repository still point the wrong way**, and neither
can be fixed from here:

- the GitHub repository has **no homepage URL set**, so the page Google
  currently treats as canonical does not link back to the site
- its description still reads "Mirror of the canonical source at
  gitlab.smetonis.net…", which tells a crawler in as many words that the
  canonical source is somewhere else

## Motion

The artifact arrived with a motion vocabulary already — `lgRise` reveals,
drifting hero glows, a marquee, a light strike across the header — so what is
here extends it rather than introducing a second style of movement.

**Almost all of it is CSS.** `motion.js` supplies only the things a stylesheet
cannot work out for itself: whether the page has left the top, which section
is on screen, and where the pointer is inside a panel. That split is the point
— the artifact's own reset already carries

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
```

so a reader who has asked for less movement gets none of the new work either,
without a second switch that could be forgotten. Verified with Firefox's
`ui.prefersReducedMotion` pref: nothing animating, nothing transitioning,
`scroll-behavior: auto`, no content stuck invisible, the overlay still opening
and closing.

If `motion.js` never loads, the page is what it was: the header keeps its
resting colour, no nav link is marked, and panels do not light up.

### Firefox has no scroll timelines, and that matters here

Sixteen elements in the artifact animate with

```css
animation: lgRise ... both;
animation-timeline: view();
animation-range: entry 0% cover 20%;
```

Chrome and Safari tie those to the element's passage through the viewport.
**Firefox does not support scroll-driven animations at all** — it drops
`animation-timeline` as unrecognised and the animation falls back to the
document timeline, so it runs to completion during page load. Every reveal on
the page had therefore already happened before you scrolled to it, and Firefox
users saw a page with no reveals. Nothing looked broken, because `both` leaves
each element at its finished state, which is exactly why it went unnoticed.

`motion.js` now drives them where the browser has no scroll timelines: each
one is paused (`both` holds it at `from`, opacity 0) and released by an
IntersectionObserver. Two details keep that safe:

- an element is **paused and observed in the same breath**, so it can never be
  left at opacity 0 with nothing to start it
- it is the **last thing the file does**, so a throw earlier on cannot leave
  the page half-hidden

The scroll progress bar has the same cause. `animation-timeline: scroll(root
block)` is the right answer and runs off the main thread — and does nothing in
Firefox, which is not a rounding error for a Linux Matrix client. It is a
passive scroll listener coalesced onto a frame instead: the listener sets a
flag and nothing else, so all reading and writing happens once per frame
inside the rAF callback rather than turning a scroll into a layout thrash.

### Traps in this pass

- **A style attribute is re-serialised from its parsed form.** Setting any
  property through `el.style` rewrites the whole attribute — and Firefox has
  already dropped the `animation-timeline` it could not parse. So
  `[style*="animation-timeline"]` finds those elements before `motion.js`
  touches them and finds nothing afterwards. Measure them by
  `animationPlayState`, not by the attribute.
- **`requestAnimationFrame` is throttled for content the browser is not
  painting.** The overlay's fade-in was a nested pair of rAF calls, the usual
  way to get a "before" frame for a transition. In a background tab or an
  offscreen frame the callback never runs, and the overlay sits open at
  opacity 0 swallowing every click. Reading `offsetWidth` forces the same
  style-and-layout flush with no such condition.
- **`IntersectionObserver` with a null root uses the *top-level* viewport.**
  An offscreen iframe therefore intersects nothing, which makes a working page
  measure as broken. Probe frames have to be on screen.
- **Closing the overlay is two-phase.** The scroll lock and focus come back at
  once — making a reader wait out a fade before the page scrolls again is
  worse than the fade is worth — and `hidden` follows on a timer. A timer, not
  `transitionend`: under reduced motion every transition is `none`, so
  `transitionend` would never fire and the overlay would stay on top of the
  page forever.

### Scrollbars

The install boxes scroll horizontally (`white-space: pre`) and the AppImage
command is long enough to always show a bar. `:root { color-scheme: dark }`
does most of the work — it darkens the page's own scrollbar and any form
control too — and the code boxes additionally get `scrollbar-width: thin` with
explicit colours, plus the `::-webkit-scrollbar` equivalents, so the bar
inside a `#070a0e` box is quieter than the page's.

## Mobile

The artifact was laid out for desktop only: at a 390 px viewport the document
measured **719 px wide**, so the page sat squeezed against the left edge behind
a horizontal scroll. The generator now emits a `@media (max-width: 760px)`
block. The measured causes were, worst first:

1. the nav's seven links in a nowrap flex row — the widest element on the page,
   and the reason the viewport blew out at all. Below the breakpoint the five
   in-page links are hidden; the brand and Download button stay.
2. `repeat(auto-fit, minmax(420px, 1fr))` grids — a 420 px column inside a
   326 px container. Collapsed to one column.
3. the "why" rows' `88px 1fr 1.15fr` grid, which kept all three columns and
   wrapped the prose to about one word per line. Stacked.
4. the install-command boxes' `white-space: pre`, whose ~624 px max-content
   width propagated up through every ancestor, because grid and flex children
   default to `min-width: auto`. They wrap on mobile instead.
5. desktop type sizes (68 px hero, 42 px section heads) at phone width.

The sticky alpha bar was a sixth item, fixed later: it ran to four lines and,
being sticky, cost that on every scroll. Two things were wrong. The `ALPHA`
pill is a `<span>`, and `_mark()` can only tag `nav|section|div|figure|a|h1-h3`
— so a predicate written for it silently matched an unrelated amber label in
the status section instead, and the pill is now tagged by hand in correction 3.
And the bar is a flex container, which **blockifies its children**: `display:
inline` on the warning computed to `block`, so the 126 px "what's missing" link
was pushed onto a row of its own. On mobile the bar becomes a plain block of
running text, and a shorter second wording (`.lg-alpha-brief`) replaces the
full sentence — both are in the markup, so the warning is right with JavaScript
off. Measured 94 px → 52 px at 390 px.

Because every style in the page is inline, these overrides need `!important` —
an inline style beats any stylesheet rule without it. The elements are tagged
with `lg-*` classes during the build rather than targeted by attribute
selectors, so the CSS stays greppable.

`html, body { overflow-x: clip }` is a deliberate backstop, not the fix: all
five causes above are fixed at source. It is there so a future edit degrades
into one clipped element instead of shoving the whole layout sideways again.

To check a change, measure rather than eyeball — `document.documentElement.scrollWidth`
must equal `clientWidth` at 320 px, and the only elements wider than the
viewport should be the hero glow and the marquee, both clipped by design.

## Local preview

```sh
cd public && python3 -m http.server 8899
```

Then open http://localhost:8899. Serve from `public/`, not the repository
root — every path in the page is absolute (`/assets/...`).

`_headers` and `_redirects` are Cloudflare features and do nothing locally.
Workers static assets supports both natively, the same as Pages did.

`python3 -m http.server` does not run the Worker, so `/api/latest` 404s and the
page falls back to `releases.json` — which is exactly the no-JS path, worth
seeing. To exercise the real route:

```sh
npx wrangler dev
```

If that reports a TLS error on the upstream fetch, the sandbox is missing a CA
bundle rather than the Worker being broken:
`SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt npx wrangler dev`.

## Deploying

Cloudflare **Workers** (static assets), connected to this GitHub repository.
Every push to `main` deploys.

`wrangler.jsonc` is the whole configuration: it points Cloudflare at `public/`
and asks for `404.html` on unknown paths. There is no `main` script and no
assets binding, because the site is static — Cloudflare serves the directory
directly.

**One-time setup** — Cloudflare dashboard → Workers & Pages → Create →
Import a repository → `lightning-website`:

| Field | Value |
| --- | --- |
| Build command | *(leave empty)* |
| Deploy command | `npx wrangler deploy` |
| Version-preview command | *(leave empty)* |
| Root directory | `/` |

There is no build step: the repository already contains the finished site.
`wrangler deploy` reads `wrangler.jsonc` and uploads `public/`.

Then under the Worker's **Domains** tab, add **both**:

- `www.lightning-matrix.org` — the canonical hostname
- `lightning-matrix.org` — the apex

`www` is canonical: it is what `<link rel="canonical">`, the Open Graph tags
and `sitemap.xml` all point at.

If DNS for `lightning-matrix.org` is already on Cloudflare, adding the domains
creates the records for you. Otherwise point the nameservers at Cloudflare
first. A custom domain will not attach while the hostname already has A /
AAAA / CNAME records — delete those first (but never the MX or TXT records,
which carry email).

### The apex → www redirect

This is **not** in `_redirects`: Workers rejects cross-hostname redirects
there ("Only relative URLs are allowed", code 100324), and the rejection
fails the entire deploy.

It is a zone Redirect Rule instead — dashboard → `lightning-matrix.org` →
**Rules → Redirect Rules**:

| | |
| --- | --- |
| Match | URI Full, wildcard `http*://lightning-matrix.org/*` |
| Target | `https://www.lightning-matrix.org/${2}` |
| Status | 301, preserve query string |

Redirect Rules run *before* Workers, so anything matching here never reaches
the site. Watch for leftover parking rules pointing at GitHub — they will
silently swallow the whole domain.

Deploying by hand, if you ever need to:

```sh
npx wrangler deploy          # or: npx wrangler versions upload
```

### Response headers

`public/_headers` sets a strict Content-Security-Policy — the page loads
nothing from any third party, so everything is `'self'`. The one loosening is
`style-src 'unsafe-inline'`, which the inline `style="..."` attributes require.

`connect-src` stays `'self'` even though the page needs GitHub's release data:
`src/worker.js` fetches it server-side and the browser only ever talks to this
origin. That is the reason the lookup is proxied rather than called from the
page — no visitor's IP is handed to GitHub just for loading the site, and one
cached edge response serves everyone instead of each visitor spending their own
GitHub rate limit.

Caching is deliberately split: fonts are immutable (family + unicode subset
fully identify the file), screenshots get a day because their filenames are
not content-hashed, and **`releases.json` is `no-cache`** so a release is
visible immediately.

Fonts sit at `/fonts/`, not `/assets/fonts/`, because Cloudflare applies
*every* matching rule in `_headers` and merges the results — a nested rule
emitted two `Cache-Control` values in one header and the browser honoured the
first, capping fonts at a day. Keep header prefixes disjoint.

If you add a third-party embed later, the CSP will block it until you add the
origin to the matching directive.

## Licence

GPL-3.0-or-later, matching the client. See [LICENSE](LICENSE).

Screenshots come from Lightning's demo mode, which uses invented `*.example`
accounts and local test media — no real conversations.
