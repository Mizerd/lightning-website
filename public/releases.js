/* Keeps a deployed page in step with releases.json.
 *
 * index.html is already rendered from releases.json at build time, so this
 * script is not what makes the page work -- it is what lets you cut a release
 * by editing releases.json alone, with no HTML change and no rebuild. If it
 * never runs, the page still shows the version it was built with.
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

  fetch("/releases.json", { cache: "no-cache" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d || !d.version) return;

      text("version", d.version);
      if (d.released) text("released", d.released);
      if (d.releases_url) link("releasesUrl", d.releases_url);
      if (d.mirror_url) link("mirrorUrl", d.mirror_url);
      link("donateUrl", d.donate_url);

      if (Array.isArray(d.packages) && d.packages.length) {
        packages("linux", d.packages.filter(function (p) { return p.os === "linux"; }));
        packages("windows", d.packages.filter(function (p) { return p.os === "windows"; }));
      }
    })
    .catch(function () { /* keep the built-in content */ });
})();
