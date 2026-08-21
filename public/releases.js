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
    }

    var sha = document.querySelector("[data-lg-dl-sha]");
    if (sha) {
      var shaUrl = fromTemplate(d.asset_url, d.version, "SHA256SUMS");
      if (shaUrl) sha.href = shaUrl;
    }
  }

  // ---- pass 2: whatever GitHub actually published --------------------------
  // This is what makes a new release appear without touching this repo. Each
  // card knows its format (".deb", "AppImage", ...) and every release publishes
  // exactly one asset per format, so the card's format is enough to find its
  // asset -- no version or filename is assumed anywhere.
  function applyLatest(d) {
    if (!d || !d.version || !Array.isArray(d.assets) || !d.assets.length) return;

    text("version", d.version);
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
      var asset = assetFor(card.getAttribute("data-lg-format"));
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

  function flash(btn, word) {
    if (btn.dataset.busy) return;
    btn.dataset.busy = "1";
    var was = btn.textContent;
    btn.textContent = word;
    setTimeout(function () {
      btn.textContent = was;
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
      function () { flash(btn, "Copied"); },
      function () { flash(btn, "Press Ctrl+C"); }
    );
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
