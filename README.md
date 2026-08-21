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
  404.html
  robots.txt
  sitemap.xml
  _headers           <- Cloudflare: CSP, security headers, cache policy
  _redirects         <- Cloudflare: same-site path redirects (relative URLs only)
  assets/
    lightning-mark.svg
    screenshot-*.png
  fonts/*.woff2      <- Manrope, JetBrains Mono, Space Grotesk (self-hosted)

wrangler.jsonc       <- Cloudflare config: serve public/, 404.html on miss
src/
  worker.js          <- one route, GET /api/latest (newest release from GitHub)
artifact/
  Lightning.html     <- the original Claude artifact this site was built from
tools/
  unbundle.py        <- converts that artifact into public/
  check.py           <- invariant checks; run after editing public/
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
version agrees with `releases.json`, nothing served mentions GitLab, and
`releases.js` is not cacheable for longer than the HTML it rewrites. Exits
non-zero, so it works in a pre-push hook.

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
