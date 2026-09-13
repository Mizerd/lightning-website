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

  /* The wave's shape, in two sizes, because there are two ways to draw it.
   *
   * WAVE_SWEEP_MS is the snapshot wipe: ONE movement, an expanding circle, so
   * it can afford to be slow without feeling slow. WAVE_MS and
   * WAVE_SPREAD_MS are the fallback's -- a hundred overlapping colour
   * transitions, each 720ms, released over 300ms of stagger from the click.
   *
   * Both replaced a 260ms fade on six selectors, which was too fast to read as
   * a change and too narrow to be one: the grounds eased while every paragraph
   * on top of them snapped.
   */
  var WAVE_SWEEP_MS = 840;
  var WAVE_MS = 720;
  var WAVE_SPREAD_MS = 300;
  // The ink crosses on its own fixed lag (see the CSS), and the wave may not
  // be disarmed before the LAST thing lands -- removing `.lg-wave` removes the
  // transition, and a running transition whose property stops being
  // transitionable is CANCELLED, so a colour would jump the rest of the way.
  var WAVE_INK_MS = 200 + 260;

  /* The blocks that turn as a unit. `--wave-d` INHERITS, so a heading moves
   * with the section that holds it and nothing below this line has to be
   * enumerated -- which is the whole reason the delay is a custom property
   * rather than a per-element transition written by script.
   */
  var WAVE_BLOCKS = ".lg-top, main > section, .lg-row, .lg-pkg, .lg-card," +
                    " .lg-shot, .lg-plat, .lg-list > li, .lg-swatches, footer";

  var waveGen = 0;
  var waveMarked = [];
  var waveFront = null;
  var waveTimer = 0;

  function shotSrc(name, slug) {
    return "/assets/shots/" + name + "--" + slug + ".png";
  }

  function endWave() {
    clearTimeout(waveTimer);
    document.documentElement.classList.remove("lg-wave");
    waveMarked.forEach(function (el) { el.style.removeProperty("--wave-d"); });
    waveMarked = [];
    if (waveFront && waveFront.parentNode) waveFront.parentNode.removeChild(waveFront);
    waveFront = null;
  }

  // Delay every block by its distance from the click, normalised against the
  // FURTHEST block rather than against a guessed radius: the same gesture then
  // takes the same time on a phone and on a 4K panel. The square root is what
  // makes it read as a ripple -- a front that slows as it spreads -- instead
  // of a ruler sliding down the page.
  function markWave(ox, oy) {
    var els = Array.prototype.slice.call(document.querySelectorAll(WAVE_BLOCKS));
    var far = 1, dist = [];
    els.forEach(function (el) {
      var r = el.getBoundingClientRect();
      var dx = r.left + r.width / 2 - ox;
      var dy = r.top + r.height / 2 - oy;
      var d = Math.sqrt(dx * dx + dy * dy);
      dist.push(d);
      if (d > far) far = d;
    });
    els.forEach(function (el, i) {
      el.style.setProperty("--wave-d",
        Math.round(WAVE_SPREAD_MS * Math.sqrt(dist[i] / far)) + "ms");
      waveMarked.push(el);
    });
  }

  // The visible front: one soft ring in the NEW theme's accent. The element is
  // a fixed 360px (see the CSS) and JS supplies only the SCALE that carries it
  // to the furthest corner of the viewport from wherever the reader clicked --
  // so the gradient is rasterized once, small, and the rest is the compositor
  // enlarging a texture.
  function rideWave(ox, oy) {
    var ink = getComputedStyle(document.documentElement)
                .getPropertyValue("--accent").trim();
    if (!ink) return;
    var w = window.innerWidth, h = window.innerHeight;
    var reach = Math.max(
      Math.hypot(ox, oy), Math.hypot(w - ox, oy),
      Math.hypot(ox, h - oy), Math.hypot(w - ox, h - oy));
    var el = document.createElement("div");
    el.className = "lg-wavefront";
    el.style.setProperty("--wave-ink", ink);
    el.style.setProperty("--wave-ride",
      (document.startViewTransition ? WAVE_SWEEP_MS : WAVE_MS + WAVE_SPREAD_MS) + "ms");
    el.style.setProperty("--wave-scale", (reach * 2 / 360).toFixed(3));
    el.style.left = ox + "px";
    el.style.top = oy + "px";
    document.body.appendChild(el);
    waveFront = el;
  }

  /* The pictures dissolve rather than blink.
   *
   * Every scenario was captured in every theme from the client's own demo
   * mode, so a switch replaces seven <img> sources at once. Assigning src
   * shows the OLD picture until the new one has decoded and then cuts -- seven
   * separate flashes in the middle of a smooth colour wave. The incoming
   * picture is laid over the outgoing one, decoded BEFORE anything is shown,
   * and faded in on the same delay the block around it is using.
   */
  function crossfadeShots(slug, gen) {
    document.querySelectorAll("[data-lg-shot]").forEach(function (img) {
      var next = shotSrc(img.getAttribute("data-lg-shot"), slug);
      var host = img.parentNode;
      if (!host || img.getAttribute("src") === next) return;
      var delay = parseFloat(
        getComputedStyle(img).getPropertyValue("--wave-d")) || 0;
      var started = Date.now();
      var over = document.createElement("img");
      over.className = "lg-shot-x";
      over.alt = "";
      over.setAttribute("aria-hidden", "true");
      over.src = next;

      var fired = false, dropped = false;
      function drop() {
        if (dropped) return;
        dropped = true;
        if (over.parentNode) over.parentNode.removeChild(over);
      }
      function reveal() {
        if (fired) return;
        fired = true;
        if (gen !== waveGen) return;
        // A tab hidden between the click and the decode runs no animation
        // frames and advances no transition, so a fade there would leave the
        // OLD picture sitting at full opacity over the new one until the
        // reader came back. Swap outright instead.
        if (document.hidden) { img.src = next; return; }
        // Spend the decode out of the block's own delay rather than after it,
        // so a picture that took 200ms to decode still lands with its section
        // instead of trailing the wave by that much.
        var left = Math.max(0, delay - (Date.now() - started));
        host.appendChild(over);
        void over.offsetWidth;                     // start from opacity 0
        over.style.transition = "opacity " + WAVE_MS +
          "ms cubic-bezier(0.32, 0, 0.2, 1) " + left + "ms";
        over.style.opacity = "1";
        setTimeout(function () {
          if (gen !== waveGen) { drop(); return; }
          img.src = next;
          // Two frames: the base image must be PAINTED before the overlay
          // goes, or the swap shows one frame of the old picture. The timer is
          // not belt-and-braces and it is deliberately scheduled FIRST -- a tab
          // hidden at this instant never runs another animation frame, and an
          // environment without rAF at all would throw here and never reach a
          // fallback written below the call that threw.
          setTimeout(drop, 400);
          if (window.requestAnimationFrame) {
            requestAnimationFrame(function () { requestAnimationFrame(drop); });
          }
        }, WAVE_MS + left + 60);
      }

      // Decode off-document, so nothing is on screen until it is ready to be.
      // The timeout is the floor: a slow or failed decode must not hold a
      // picture back for longer than the wave it belongs to.
      var pre = new Image();
      pre.src = next;
      var late = setTimeout(reveal, 900);
      var decoded = pre.decode ? pre.decode() : Promise.reject();
      decoded.then(function () { clearTimeout(late); reveal(); },
                   function () { clearTimeout(late); reveal(); });
    });
  }

  // Everything a theme change actually IS, with no animation anywhere in it.
  // Both wave paths call this; one of them calls it inside a snapshot.
  //
  // `keepShots` is for the fallback path ONLY, and it is load-bearing: that
  // path cross-fades the pictures itself and assigns each new src at the end
  // of its own fade. Swapping them here as well would leave the overlay
  // dissolving one copy of the new picture into an identical one -- no visible
  // fade at all, and nothing to say so.
  function setTheme(slug, keepShots) {
    document.documentElement.setAttribute("data-theme", slug);
    if (!keepShots) {
      document.querySelectorAll("[data-lg-shot]").forEach(function (img) {
        img.src = shotSrc(img.getAttribute("data-lg-shot"), slug);
      });
    }
    document.querySelectorAll("[data-lg-theme]").forEach(function (b) {
      b.setAttribute("aria-pressed",
                     b.getAttribute("data-lg-theme") === slug ? "true" : "false");
    });
  }

  // Decode every incoming screenshot BEFORE the change is made, so the frame
  // the browser snapshots already has them. An undecoded image would be
  // snapshotted blank and the wave would wipe in seven empty boxes.
  function decodeShots(slug) {
    var waits = [];
    document.querySelectorAll("[data-lg-shot]").forEach(function (img) {
      var next = shotSrc(img.getAttribute("data-lg-shot"), slug);
      if (img.getAttribute("src") === next) return;
      var pre = new Image();
      pre.src = next;
      waits.push(pre.decode ? pre.decode().catch(function () {}) : Promise.resolve());
    });
    // Never wait longer than the wave itself would have taken. A cold cache on
    // a slow link must not leave the reader pressing a button that does
    // nothing; a picture that misses the snapshot simply appears with it.
    return Promise.race([
      Promise.all(waits),
      new Promise(function (done) { setTimeout(done, 600); })
    ]);
  }

  /* THE WAVE, when the browser can snapshot a page.
   *
   * A light palette and a dark one are opposite at both ends: the ground has
   * to travel from pale to near-black while the text travels the other way,
   * and any CONTINUOUS interpolation of both has an instant where a half-dark
   * letter sits on a half-light ground. Measured on this page, three ways of
   * timing it -- one curve for both, ink slower than ground, ink crossing on
   * its own late lag -- bottomed out at 1.13:1, 1.5:1 and 1.02:1. That is not
   * dim; it is unreadable, and there is no pair of curves that avoids it,
   * because the crossing is the problem and not the speed.
   *
   * A view transition removes the crossing entirely. The browser holds a
   * picture of the old page, the new one is built underneath it complete, and
   * an expanding circle from the reader's own click wipes one to the other.
   * Every pixel is either fully the old theme or fully the new one; the only
   * thing that moves is the edge, and the edge IS the wave. It carries the
   * screenshots along with it for free, because they are in the same picture.
   */
  function waveSnapshot(slug, origin, gen) {
    return decodeShots(slug).then(function () {
      if (gen !== waveGen) return;
      var vt = document.startViewTransition(function () { setTheme(slug); });
      vt.ready.then(function () {
        var w = window.innerWidth, h = window.innerHeight;
        var reach = Math.max(
          Math.hypot(origin.x, origin.y), Math.hypot(w - origin.x, origin.y),
          Math.hypot(origin.x, h - origin.y), Math.hypot(w - origin.x, h - origin.y));
        var at = " at " + origin.x + "px " + origin.y + "px)";
        document.documentElement.animate(
          { clipPath: ["circle(0px" + at, "circle(" + Math.ceil(reach) + "px" + at] },
          { duration: WAVE_SWEEP_MS, easing: "cubic-bezier(0.24, 0.62, 0.28, 1)",
            pseudoElement: "::view-transition-new(root)" });
        rideWave(origin.x, origin.y);              // reads the NEW accent
        waveTimer = setTimeout(function () {
          if (gen === waveGen) endWave();
        }, WAVE_SWEEP_MS + 160);
      }, function () { /* the transition was skipped; the theme still landed */ });
    });
  }

  /* THE WAVE, when it cannot.
   *
   * Firefox before 144 and Safari before 18 have no view transitions, so this
   * is the same idea built out of what every browser has: one colour
   * transition over everything, delayed per block by its distance from the
   * click, with the pictures cross-faded through overlay <img>s on the same
   * delays. It has the crossing problem described above and cannot not have
   * it; the ink is given a fast 260ms cross so the bad instant is an instant.
   */
  function waveTransitions(slug, origin, gen) {
    endWave();
    markWave(origin.x, origin.y);
    document.documentElement.classList.add("lg-wave");
    // One forced reflow, so the browser has a before-change style that already
    // carries the transition rather than deciding both in one go.
    void document.body.offsetWidth;
    setTheme(slug, true);                          // the pictures are this path's own
    rideWave(origin.x, origin.y);                  // reads the NEW accent
    crossfadeShots(slug, gen);
    waveTimer = setTimeout(function () {
      if (gen === waveGen) endWave();
    }, WAVE_INK_MS + WAVE_SPREAD_MS + 140);
  }

  function applyTheme(slug, remember, origin) {
    if (!slug) return;
    // A hidden tab runs no animation frames: every transition on it is frozen
    // at its start value, so "animating" there means showing the OLD colours
    // until the reader comes back. Switch outright instead.
    var animate = !!origin && !prefersReducedMotion() && !document.hidden;
    var gen = ++waveGen;

    if (remember) {
      // A browser with storage disabled must still switch themes; only the
      // remembering is optional. Written first: it is the reader's choice and
      // it must survive whatever the animation does.
      try { localStorage.setItem(THEME_KEY, slug); } catch (e) { /* fine */ }
    }

    if (!animate) {
      endWave();
      setTheme(slug);
    } else if (document.startViewTransition) {
      waveSnapshot(slug, origin, gen);
    } else {
      waveTransitions(slug, origin, gen);
    }
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target && ev.target.closest
      ? ev.target.closest("[data-lg-theme]") : null;
    if (!btn) return;
    // The wave starts where the reader actually pressed. A keyboard activation
    // reports 0,0 for both, so fall back to the button's own centre.
    var r = btn.getBoundingClientRect();
    var x = ev.clientX || 0, y = ev.clientY || 0;
    if (!x && !y) { x = r.left + r.width / 2; y = r.top + r.height / 2; }
    applyTheme(btn.getAttribute("data-lg-theme"), true, { x: x, y: y });
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

  /* ---- the sky --------------------------------------------------------------
   * A fresh constellation field on every load, built from the SET SHAPES in
   * public/sky-shapes.json (inlined into the page as #lg-sky-shapes).
   *
   * index.html ships a baked field so a reader without JavaScript still gets a
   * sky, and this replaces it for two reasons. The first is that it is a
   * different sky every time, which is the point. The second is less obvious
   * and matters more: the baked one is a fixed viewBox scaled to fit, so on a
   * phone it is a handful of enormous stars and on a 4K panel a fine mist.
   * Rolled here, the field is generated in the layer's REAL pixel size, so the
   * density and the star sizes are the same everywhere.
   */
  function skyShapes() {
    var el = document.getElementById("lg-sky-shapes");
    if (!el) return null;
    try {
      var data = JSON.parse(el.textContent);
      return data && data.shapes && data.shapes.length ? data.shapes : null;
    } catch (err) {
      return null;
    }
  }

  function r1(v) { return Math.round(v * 10) / 10; }
  function r2(v) { return Math.round(v * 100) / 100; }

  // The same algorithm build-site.py bakes with, in the same coordinate space.
  // They are not required to agree star for star -- each rolls its own -- only
  // to build from the same shapes.
  function skyField(W, H, shapes) {
    // Keep the centre column clear: the page's text sits in a 1080px column
    // and this layer is behind it. The band narrows on a narrow window rather
    // than swallowing the whole width.
    var keep = Math.min(1080, W * 0.72);
    keep = Math.min(keep, Math.max(0, W - 240));
    var lo = (W - keep) / 2, hi = (W + keep) / 2;

    var lines = [], circles = [], stars = [], placed = [];
    var nConst = Math.max(5, Math.min(16, Math.round(W * H / 1000000)));
    for (var i = 0; i < nConst; i++) {
      var shape = shapes[(Math.random() * shapes.length) | 0];
      var size = 90 + Math.random() * 120;
      var rot = Math.random() * Math.PI * 2;
      var squash = 0.78 + Math.random() * 0.47;
      var cos = Math.cos(rot), sin = Math.sin(rot);

      // Centres go in the margins; a figure may spill towards the column,
      // which reads as sky continuing behind the page rather than stopping at
      // a line. Rejection-sampled so two figures do not land on each other.
      var cx = 0, cy = 0;
      for (var t = 0; t < 40; t++) {
        cx = lo <= 60 ? Math.random() * W
           : (Math.random() < 0.5 ? Math.random() * lo
                                  : hi + Math.random() * (W - hi));
        cy = size * 0.6 + Math.random() * Math.max(1, H - size * 1.2);
        var clear = true;
        for (var q = 0; q < placed.length; q++) {
          var qx = cx - placed[q][0], qy = cy - placed[q][1];
          var lim = (size + placed[q][2]) * 0.6;
          if (qx * qx + qy * qy <= lim * lim) { clear = false; break; }
        }
        if (clear) break;
      }
      placed.push([cx, cy, size]);

      var pts = [];
      for (var k = 0; k < shape.pts.length; k++) {
        var dx = (shape.pts[k][0] - 0.5) * size;
        var dy = (shape.pts[k][1] - 0.5) * size * squash;
        pts.push([r1(cx + dx * cos - dy * sin), r1(cy + dx * sin + dy * cos)]);
      }
      for (var e = 0; e < shape.edges.length; e++) {
        var a = pts[shape.edges[e][0]], b = pts[shape.edges[e][1]];
        if (!a || !b) continue;
        lines.push('<line x1="' + a[0] + '" y1="' + a[1] +
                   '" x2="' + b[0] + '" y2="' + b[1] + '"/>');
      }
      for (var v = 0; v < pts.length; v++) {
        stars.push([pts[v][0], pts[v][1], r2(1.2 + Math.random() * 0.9)]);
      }
    }

    // The accent star is one of a constellation's own vertices, so the detail
    // sits inside a figure rather than floating in the dust.
    var accent = stars.length ? (Math.random() * stars.length) | 0 : -1;

    // Dust: unconnected stars, kept out of the column, at a density that
    // follows the area rather than a number somebody typed once.
    var vertices = stars.length;
    var nDust = Math.round(W * H / 34000);
    for (var tries = 0; stars.length - vertices < nDust && tries < nDust * 12; tries++) {
      var x = Math.random() * W, y = Math.random() * H;
      if (x > lo && x < hi) continue;
      stars.push([r1(x), r1(y), r2(0.6 + Math.random())]);
    }

    for (var s = 0; s < stars.length; s++) {
      circles.push('<circle' + (s === accent ? ' class="lg-sky-mark"' : '') +
                   ' cx="' + stars[s][0] + '" cy="' + stars[s][1] +
                   '" r="' + (s === accent ? 2.6 : stars[s][2]) + '"/>');
    }
    return lines.join("") + circles.join("");
  }

  var skyW = 0, skyH = 0, skyTimer = 0;

  function paintSky() {
    var svg = document.querySelector("svg.lg-sky");
    var shapes = skyShapes();
    if (!svg || !shapes) return;
    // The layer's own box, not the window and not scrollHeight: it is sized by
    // CSS to cover the document, and measuring what we are actually filling is
    // the one measurement that cannot disagree with it.
    var box = svg.getBoundingClientRect();
    var W = Math.round(box.width), H = Math.round(box.height);
    if (W < 240 || H < 240) return;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.innerHTML = skyField(W, H, shapes);
    skyW = W;
    skyH = H;
  }

  // Repaint only when the document has actually changed shape. Fonts landing,
  // images decoding and a window resize all move it; a few pixels do not
  // deserve a whole new sky, and rerolling on every observer callback would
  // make the stars flicker while the reader drags a window edge.
  function skyResized() {
    var svg = document.querySelector("svg.lg-sky");
    if (!svg) return;
    var box = svg.getBoundingClientRect();
    if (Math.abs(box.width - skyW) < 48 && Math.abs(box.height - skyH) < 240) return;
    paintSky();
  }

  function skyWatch() {
    var svg = document.querySelector("svg.lg-sky");
    if (!svg) return;
    function later() {
      clearTimeout(skyTimer);
      skyTimer = setTimeout(skyResized, 220);
    }
    if (window.ResizeObserver) {
      new ResizeObserver(later).observe(svg);
    } else {
      window.addEventListener("resize", later);
    }
    window.addEventListener("load", later);
  }

  paintSky();
  skyWatch();

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
