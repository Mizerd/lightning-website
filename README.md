# lightning-website

The official website for [Lightning](https://gitlab.smetonis.net/Mizerd/lightning),
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
    fonts/*.woff2    <- Manrope, JetBrains Mono, Space Grotesk (self-hosted)

wrangler.jsonc       <- Cloudflare config: serve public/, 404.html on miss
artifact/
  Lightning.html     <- the original Claude artifact this site was built from
tools/
  unbundle.py        <- converts that artifact into public/
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
  "mirror_url":   "https://gitlab.smetonis.net/Mizerd/lightning/-/releases",
  "donate_url":   "",                // empty hides the Donate button
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

`index.html` also ships the current values baked in, so the page is correct
before `releases.js` runs and stays correct if it never does. Those baked-in
values only refresh when the page is rebuilt (below) — for a normal release,
editing `releases.json` alone is enough and the live page follows.

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

## Local preview

```sh
cd public && python3 -m http.server 8899
```

Then open http://localhost:8899. Serve from `public/`, not the repository
root — every path in the page is absolute (`/assets/...`).

`_headers` and `_redirects` are Cloudflare features and do nothing locally.
Workers static assets supports both natively, the same as Pages did.

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
`style-src 'unsafe-inline'`, which the 347 inline `style="..."` attributes
require.

Caching is deliberately split: fonts are immutable (family + unicode subset
fully identify the file), screenshots get a day because their filenames are
not content-hashed, and **`releases.json` is `no-cache`** so a release is
visible immediately.

If you add a third-party embed later, the CSP will block it until you add the
origin to the matching directive.

## Licence

GPL-3.0-or-later, matching the client. See [LICENSE](LICENSE).

Screenshots come from Lightning's demo mode, which uses invented `*.example`
accounts and local test media — no real conversations.
