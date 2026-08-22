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
      d.packages.forEach(function (p) {
        p.download_url = fromTemplate(d.asset_url, d.version, p.file);
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
        var name = String(d.assets[i].name || "").toLowerCase();
        if (name.slice(-f.length) === f) return d.assets[i];
      }
      return null;
    }

    document.querySelectorAll("[data-lg-format]").forEach(function (card) {
      // data-lg-match wins where it exists: the format badge is what a reader
      // sees (".zip"), which is not always enough to pick one asset out of a
      // release that publishes two of them.
      var asset = assetFor(card.getAttribute("data-lg-match")
                           || card.getAttribute("data-lg-format"));
      if (!asset || !asset.url) return;

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
    lb.addEventListener("click", function (ev) {
      if (ev.target !== lbImg) closeLightbox();
    });
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

    // The caption belongs to the <figure> two levels up. Without one the
    // element would still take its margin, so it is emptied and hidden.
    var fig = btn.closest ? btn.closest("figure") : null;
    var cap = fig ? fig.querySelector("figcaption") : null;
    lbCap.textContent = cap ? cap.textContent : "";
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

    var closeBtn = lb.querySelector(".lg-lbclose");
    if (closeBtn) closeBtn.focus();
  }

  function closeLightbox() {
    if (!lb || lb.hidden) return;
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
