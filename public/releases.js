/* Keeps a deployed page in step with releases.json.
 *
 * index.html is already rendered from releases.json at build time, so this
 * script is not what makes the page work -- it is what keeps a deployed page
 * current. If it never runs, the page still shows the version it was built
 * with, and every download button still points at a real release asset.
 *
 * Two sources, applied in order:
 *   1. /releases.json  -- this repo's feed. Editing it is how you change the
 *      wording, the package list, or the donate link.
 *   2. /api/latest     -- the Worker's view of the newest GitHub release.
 *      This is what makes a new release appear here on its own: it overrides
 *      the version, the date and every download URL with whatever GitHub
 *      actually published, and rewrites the filenames inside the install
 *      commands to match.
 *
 * Every step fails soft: a bad fetch, bad JSON or a missing field leaves the
 * built-in content exactly as it is.
 */
(function () {
  "use strict";

  function text(key, value) {
    document.querySelectorAll('[data-lg-bind="' + key + '"]').forEach(function (el) {
      el.textContent = value;
    });
  }

  // The version also appears in the SoftwareApplication data block in <head>,
  // which is JSON rather than DOM, so data-lg-bind cannot reach it. Kept in
  // step here for the same reason as everything else on the page: the site
  // must never quote a version GitHub has moved past.
  function ldVersion(value) {
    var el = document.querySelector('script[type="application/ld+json"]');
    if (!el || !value) return;
    try {
      var d = JSON.parse(el.textContent);
      if (d.softwareVersion === value) return;
      d.softwareVersion = value;
      el.textContent = JSON.stringify(d);
    } catch (err) { /* leave the built-in block alone */ }
  }

  function link(key, url) {
    document.querySelectorAll('[data-lg-href="' + key + '"]').forEach(function (el) {
      if (url) {
        el.href = url;
        el.hidden = false;
      } else {
        // No destination configured -- keep the markup, keep it unclickable.
        el.hidden = true;
        el.removeAttribute("href");
      }
    });
  }

  // Point one card's download button at a URL, or hide it if there is none.
  function setDownload(scope, url, fileName) {
    var a = scope.querySelector("[data-lg-dl]");
    if (!a) return;
    if (url) {
      a.href = url;
      a.hidden = false;
      if (fileName) a.setAttribute("aria-label", "Download " + fileName);
    } else {
      a.hidden = true;
      a.removeAttribute("href");
    }
  }

  function packages(osName, list) {
    var cards = document.querySelectorAll('[data-lg-pkg="' + osName + '"]');
    if (!cards.length || !list.length) return;

    var parent = cards[0].parentNode;
    var proto = cards[0].cloneNode(true);

    var built = list.map(function (pkg) {
      var card = proto.cloneNode(true);
      card.querySelectorAll("[data-lg-bind]").forEach(function (slot) {
        var field = slot.getAttribute("data-lg-bind").split(".")[1];
        if (pkg[field] != null) slot.textContent = pkg[field];
      });
      // Everything below is per-card state inherited from the prototype, which
      // is card zero. Each one must be overwritten or the clone silently keeps
      // card zero's value -- the bug that made every Linux button serve the
      // .deb and every Windows button the .msi. setDownload is called
      // unconditionally so a missing URL hides the button rather than leaving
      // it pointing at the wrong file.
      setDownload(card, pkg.download_url, pkg.file);
      card.setAttribute("data-lg-format", pkg.format || "");
      // The suffix pass 2 matches on, when the displayed format is ambiguous.
      // Two cards ship a ".zip" -- the Windows portable and the macOS bundle --
      // and matching on the badge text alone would hand both of them whichever
      // .zip GitHub happened to list first.
      if (pkg.match) card.setAttribute("data-lg-match", pkg.match);
      else card.removeAttribute("data-lg-match");
      card.setAttribute("data-lg-file", pkg.file || "");
      return card;
    });

    // Swap in place: replace the first card, drop the rest. Doing it in this
    // order keeps the new cards at the original position among their siblings
    // rather than appending them to the end of the column.
    parent.replaceChild(built[0], cards[0]);
    for (var i = 1; i < cards.length; i++) parent.removeChild(cards[i]);
    for (var j = built.length - 1; j >= 1; j--) {
      built[0].parentNode.insertBefore(built[j], built[0].nextSibling);
    }
  }

  // "https://.../download/v${version}/${file}" -> a real URL.
  function fromTemplate(tpl, version, file) {
    if (!tpl || !file) return "";
    return tpl.replace("${version}", version).replace("${file}", file);
  }

  // ---- pass 1: this repo's feed -------------------------------------------
  function applyFeed(d) {
    if (!d || !d.version) return;

    text("version", d.version);
    ldVersion(d.version);
    if (d.released) text("released", d.released);
    if (d.releases_url) link("releasesUrl", d.releases_url);
    link("donateUrl", d.donate_url);

    if (Array.isArray(d.packages) && d.packages.length) {
      // Give each package its download URL before the cards are rebuilt.
      // A PINNED package carries its own absolute url, because it belongs to
      // an older release than this feed describes -- templating this feed's
      // version onto its filename would produce a URL that 404s.
      d.packages.forEach(function (p) {
        p.download_url = p.url || fromTemplate(d.asset_url, d.version, p.file);
      });
      packages("linux", d.packages.filter(function (p) { return p.os === "linux"; }));
      packages("windows", d.packages.filter(function (p) { return p.os === "windows"; }));
      packages("macos", d.packages.filter(function (p) { return p.os === "macos"; }));
    }

    var sha = document.querySelector("[data-lg-dl-sha]");
    if (sha) {
      var shaUrl = fromTemplate(d.asset_url, d.version, "SHA256SUMS");
      if (shaUrl) sha.href = shaUrl;
    }
  }

  // ---- pass 2: whatever GitHub actually published --------------------------
  // This is what makes a new release appear without touching this repo. Each
  // card knows the suffix its asset ends with -- data-lg-match where the
  // displayed format is ambiguous, the format itself otherwise -- so no
  // version or filename is assumed anywhere. Since 0.7.5 two cards publish a
  // ".zip" (Windows portable, macOS), which is exactly why the match attribute
  // exists: without it whichever .zip GitHub listed first would win both.
  function applyLatest(d) {
    if (!d || !d.version || !Array.isArray(d.assets) || !d.assets.length) return;

    text("version", d.version);
    ldVersion(d.version);
    if (d.released) text("released", d.released);

    function assetFor(format) {
      var f = String(format).toLowerCase();
      for (var i = 0; i < d.assets.length; i++) {
        if (taken[d.assets[i].name]) continue;
        var name = String(d.assets[i].name || "").toLowerCase();
        if (name.slice(-f.length) === f) return d.assets[i];
      }
      return null;
    }

    // Assets a more specific card has already claimed.
    var taken = {};

    // MOST SPECIFIC FIRST, AND AN ASSET IS TAKEN ONCE.
    //
    // Suffix matching alone cannot separate `lightning_X_amd64.deb` from
    // `lightning_X_ubuntu2604_amd64.deb` -- every suffix of the first is also
    // a suffix of the second -- so whichever card ran first took whichever
    // asset GitHub happened to list first. 0.9.5 is the release that made
    // that real: it is the first to publish two .deb files.
    //
    // Resolving the LONGEST token first and removing the asset it claims
    // fixes it without embedding a version in any token: the Ubuntu card's
    // `_ubuntu2604_amd64.deb` is longer, it resolves first, and the Debian
    // card's `_amd64.deb` then has only one .deb left to find. A card with no
    // token at all sorts last, which is what you want -- the vaguest card
    // should never take an asset a specific one named.
    var ordered = Array.prototype.slice.call(
      document.querySelectorAll("[data-lg-format]"));
    ordered.sort(function (a, b) {
      return (b.getAttribute("data-lg-match") || "").length
           - (a.getAttribute("data-lg-match") || "").length;
    });
    ordered.forEach(function (card) {
      // A PINNED card names a file from an OLDER release on purpose -- macOS
      // is pinned at 0.9.4 because 0.9.5 has no macOS build. Resolving it
      // against the newest release would find nothing and hide its button,
      // removing the only macOS download the page offers.
      if (card.hasAttribute("data-lg-pinned")) return;
      // data-lg-match wins where it exists: the format badge is what a reader
      // sees (".zip"), which is not always enough to pick one asset out of a
      // release that publishes two of them.
      var asset = assetFor(card.getAttribute("data-lg-match")
                           || card.getAttribute("data-lg-format"));
      if (!asset || !asset.url) return;
      taken[asset.name] = true;

      setDownload(card, asset.url, asset.name);

      // The install command names the file, so a stale name would contradict
      // the button right next to it.
      var was = card.getAttribute("data-lg-file");
      if (was && was !== asset.name) {
        var cmd = card.querySelector('[data-lg-bind="pkg.install"]');
        if (cmd && cmd.textContent.indexOf(was) >= 0) {
          cmd.textContent = cmd.textContent.split(was).join(asset.name);
        }
        card.setAttribute("data-lg-file", asset.name);
      }
    });

    var sha = document.querySelector("[data-lg-dl-sha]");
    var shaAsset = null;
    for (var i = 0; i < d.assets.length; i++) {
      if (d.assets[i].name === "SHA256SUMS") { shaAsset = d.assets[i]; break; }
    }
    if (sha && shaAsset && shaAsset.url) sha.href = shaAsset.url;

    var rel = document.querySelector('[data-lg-href="releasesUrl"]');
    if (rel && d.release_url) rel.href = d.release_url;
  }

  // ---- copy buttons on the install commands -------------------------------
  // The buttons ship `hidden` so a reader without JavaScript never sees one
  // that cannot work. Clicks are handled by delegation because packages()
  // rebuilds these cards with cloneNode, which does not copy event listeners
  // -- a listener bound per button would die on every clone.

  function copyText(value) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(value);
    }
    // Older browsers, and any context where the async API is unavailable.
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = value;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      document.body.removeChild(ta);
      ok ? resolve() : reject();
    });
  }

  function flash(btn, word, good) {
    if (btn.dataset.busy) return;
    btn.dataset.busy = "1";
    var was = btn.textContent;
    btn.textContent = word;
    // Green only on success. The fallback path's "Press Ctrl+C" is an
    // instruction, not a result, and colouring it as one would be a lie.
    if (good) btn.classList.add("lg-copied");
    setTimeout(function () {
      btn.textContent = was;
      btn.classList.remove("lg-copied");
      delete btn.dataset.busy;
    }, 1400);
  }

  function showCopyButtons() {
    document.querySelectorAll("[data-lg-copybtn]").forEach(function (b) {
      b.hidden = false;
    });
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target && ev.target.closest
      ? ev.target.closest("[data-lg-copybtn]") : null;
    if (!btn) return;
    // The command is the button's sibling, so its textContent is the command
    // and nothing else -- no button label mixed into what gets copied.
    var box = btn.parentNode.querySelector("[data-lg-copy]");
    if (!box) return;
    copyText(box.textContent).then(
      function () { flash(btn, "✓ Copied", true); },
      function () { flash(btn, "Press Ctrl+C"); }
    );
  });

  /* ---- the theme strip --------------------------------------------------
   *
   * Every palette on this page is the CLIENT's, extracted from its own
   * AppTheme.qml, so picking one shows what the application actually looks
   * like rather than a web designer's impression of it. The whole switch is
   * one attribute on <html>: the CSS carries a [data-theme] block per theme
   * and everything else reads tokens.
   *
   * The choice is remembered. Someone who picks a theme has told you which
   * one they want to look at; making them pick again every visit is a worse
   * page. localStorage only -- nothing leaves the browser.
   */
  var THEME_KEY = "lg-theme";

  function applyTheme(slug, remember) {
    if (!slug) return;
    document.documentElement.setAttribute("data-theme", slug);
    document.querySelectorAll("[data-lg-theme]").forEach(function (b) {
      b.setAttribute("aria-pressed",
                     b.getAttribute("data-lg-theme") === slug ? "true" : "false");
    });
    if (remember) {
      // A browser with storage disabled must still switch themes; only the
      // remembering is optional.
      try { localStorage.setItem(THEME_KEY, slug); } catch (e) { /* fine */ }
    }
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target && ev.target.closest
      ? ev.target.closest("[data-lg-theme]") : null;
    if (!btn) return;
    applyTheme(btn.getAttribute("data-lg-theme"), true);
  });

  // Restore on load. The default is already correct in the CSS, so this only
  // ever has to act when a previous visit chose something else.
  try {
    var saved = localStorage.getItem(THEME_KEY);
    if (saved && document.querySelector('[data-lg-theme="' + saved + '"]')) {
      applyTheme(saved, false);
    }
  } catch (e) { /* no storage, no restore, still a working page */ }

  /* ---- full-screen screenshots ------------------------------------------
   *
   * Each screenshot is wrapped in a <button data-lg-zoom> by the generator
   * (correction 12 in tools/unbundle.py). Pressing one opens the same image
   * over the page; clicking anywhere that is not the image closes it again,
   * as does Escape and the close button.
   *
   * Set up immediately rather than in the release-feed chain below, because
   * this has nothing to do with releases: if GitHub is unreachable and every
   * fetch fails, the screenshots must still open.
   */
  var lb = null;        // the overlay, built once on first use
  var lbImg = null;
  var lbCap = null;
  var lbReturn = null;  // what to hand focus back to when we close
  var hideTimer = null; // defers display:none until the fade has run

  function buildLightbox() {
    lb = document.createElement("div");
    lb.className = "lg-lightbox";
    lb.hidden = true;
    // A dialog rather than a bare div, so a screen reader announces the
    // image as having taken over rather than reading it in place.
    lb.setAttribute("role", "dialog");
    lb.setAttribute("aria-modal", "true");
    lb.setAttribute("aria-label", "Screenshot");

    var close = document.createElement("button");
    close.type = "button";
    close.className = "lg-lbclose";
    close.setAttribute("aria-label", "Close");
    close.textContent = "✕";

    lbImg = document.createElement("img");
    lbImg.alt = "";

    lbCap = document.createElement("figcaption");

    lb.appendChild(close);
    lb.appendChild(lbImg);
    lb.appendChild(lbCap);
    document.body.appendChild(lb);

    // One listener on the overlay covers the backdrop, the caption and the
    // close button. The image is the only thing that does NOT close, so it
    // can be pinched and panned without the first tap dismissing it.
    // Clicking ANYWHERE closes, the picture included. This used to exempt the
    // image so a phone could pinch and pan it; the maintainer asked for
    // click-anywhere on 2026-09-13 and that is the trade -- easier to dismiss
    // everywhere, no panning a zoomed screenshot on a touch screen.
    lb.addEventListener("click", function () { closeLightbox(); });
  }

  function openLightbox(btn) {
    var img = btn.querySelector("img");
    if (!img) return;
    if (!lb) buildLightbox();

    // Reopened while the last one was still fading out: cancel the pending
    // hide, or it would fire a moment later and blank the new image.
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }

    lbReturn = btn;
    // Same src, so the browser serves it from cache and the full-size image
    // appears immediately rather than downloading a second time.
    lbImg.src = img.currentSrc || img.src;
    lbImg.alt = img.alt || "";

    // The caption belongs to the <figure> two levels up. The 2026-09-13
    // redesign dropped figcaptions -- each screenshot now sits beside the
    // paragraph that describes it, so a caption under it repeated the copy
    // a few pixels away. Full screen there is no such paragraph, so the
    // alt text stands in: it is the same short description, and it is
    // required to exist anyway. Without either, the element would still take
    // its margin, so it is emptied and hidden.
    var fig = btn.closest ? btn.closest("figure") : null;
    var cap = fig ? fig.querySelector("figcaption") : null;
    lbCap.textContent = cap ? cap.textContent : (img.alt || "");
    lbCap.hidden = !lbCap.textContent;

    lb.hidden = false;
    document.documentElement.classList.add("lg-lbopen");
    document.body.classList.add("lg-lbopen");

    // `hidden` is display:none, which has no intermediate state, so putting
    // the class on in the same breath as the unhide gives the transition
    // nothing to run from and the overlay simply appears.
    //
    // Reading offsetWidth flushes pending style and layout synchronously,
    // which is what gives the browser a "before" value. This was a pair of
    // nested requestAnimationFrame calls first, and that is the more commonly
    // written version, but rAF is throttled for content the browser is not
    // painting -- a background tab, an offscreen frame -- and the callback
    // then never runs at all, leaving the overlay open at opacity 0 and
    // swallowing every click. A forced reflow has no such condition.
    void lb.offsetWidth;
    lb.classList.add("lg-lbon");

    // THE FLIGHT. The overlay image is placed exactly over the thumbnail that
    // was clicked and then released to its natural size, so the picture grows
    // out of the card instead of appearing on top of it. Measured, not
    // guessed: the thumbnail's own rect against the image's final rect, which
    // is why this runs AFTER the class that lays the overlay out.
    //
    // transform only -- width/height would relayout the overlay on every
    // frame. A scale is one composited property and cannot reflow anything.
    flyFrom(img);

    var closeBtn = lb.querySelector(".lg-lbclose");
    if (closeBtn) closeBtn.focus();
  }

  function flyFrom(thumb) {
    if (!thumb || !lbImg || prefersReducedMotion()) return;
    var from = thumb.getBoundingClientRect();
    var to = lbImg.getBoundingClientRect();
    if (!from.width || !to.width) return;
    var sx = from.width / to.width;
    var sy = from.height / to.height;
    var dx = (from.left + from.width / 2) - (to.left + to.width / 2);
    var dy = (from.top + from.height / 2) - (to.top + to.height / 2);
    lbImg.style.transition = "none";
    lbImg.style.transformOrigin = "center center";
    lbImg.style.transform =
      "translate(" + dx + "px," + dy + "px) scale(" + sx + "," + sy + ")";
    void lbImg.offsetWidth;          // same forced reflow, same reason
    lbImg.style.transition = "transform 300ms cubic-bezier(0.2,0.75,0.25,1)";
    lbImg.style.transform = "none";
  }

  function prefersReducedMotion() {
    try {
      return window.matchMedia
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) { return false; }
  }

  function closeLightbox() {
    if (!lb || lb.hidden) return;

    // Fly back to the card it came from, so the picture returns to where the
    // reader's eye already is rather than dissolving in the middle of the
    // screen. `lbReturn` is the button that opened it and is still on screen.
    var thumb = lbReturn && lbReturn.querySelector
      ? lbReturn.querySelector("img") : null;
    if (thumb && lbImg && !prefersReducedMotion()) {
      var from = lbImg.getBoundingClientRect();
      var to = thumb.getBoundingClientRect();
      if (from.width && to.width) {
        lbImg.style.transition = "transform 260ms cubic-bezier(0.4,0,0.7,0.3)";
        lbImg.style.transform =
          "translate(" + ((to.left + to.width / 2) - (from.left + from.width / 2))
          + "px," + ((to.top + to.height / 2) - (from.top + from.height / 2))
          + "px) scale(" + (to.width / from.width) + ","
          + (to.height / from.height) + ")";
      }
    }
    lb.classList.remove("lg-lbon");

    // The page is released and focus goes back immediately -- only the
    // picture is still fading, and making the reader wait 280ms for the
    // scroll to work again would be worse than any transition is worth.
    document.documentElement.classList.remove("lg-lbopen");
    document.body.classList.remove("lg-lbopen");
    if (lbReturn && lbReturn.focus) lbReturn.focus();
    lbReturn = null;

    // A timer rather than transitionend. Under prefers-reduced-motion the
    // page's reset sets `transition: none !important` on everything, so no
    // transitionend would ever fire and the overlay would sit there forever,
    // invisible but on top of the page and swallowing every click.
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(function () {
      lb.hidden = true;
      // Drop the source so a 3,839px image is not held decoded for a page
      // the reader has gone back to scrolling.
      lbImg.removeAttribute("src");
      lbImg.style.transition = "";
      lbImg.style.transform = "";
    }, 280);
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target && ev.target.closest
      ? ev.target.closest("[data-lg-zoom]") : null;
    if (btn) openLightbox(btn);
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" || ev.key === "Esc") closeLightbox();
  });

  // The "Expand" badge ships hidden, so a reader without JavaScript is never
  // told an image opens when nothing is there to open it.
  document.querySelectorAll("[data-lg-zoomhint]").forEach(function (el) {
    el.hidden = false;
  });

  function load(url, apply, opts) {
    return fetch(url, opts)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(apply)
      .catch(function () { /* keep whatever is on the page */ });
  }

  // Sequential, not parallel: the GitHub pass must land last, because it is
  // the more authoritative of the two and rebuilt cards would otherwise
  // discard the URLs it just set.
  load("/releases.json", applyFeed, { cache: "no-cache" })
    .then(function () { return load("/api/latest", applyLatest); })
    // Last: the passes above replace the cards, and the buttons must be
    // revealed on whatever cards are actually in the document at the end.
    .then(showCopyButtons, showCopyButtons);
})();
