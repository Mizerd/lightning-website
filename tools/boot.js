(function () {
  // Inlined into <head> by build-site.py, before the first paint, and allowed
  // by its sha256 in _headers. Everything it decides is keyed in the CSS, so
  // the page is drawn once, in the right theme and order; releases.js later
  // only takes over what is already on screen.
  var C = /*@CONFIG@*/null;
  var d = document.documentElement;
  var t = null;
  try { t = localStorage.getItem("lg-theme"); } catch (e) { /* storage blocked */ }
  if (C.themes.indexOf(t) < 0) {
    t = null;
    try {
      if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) t = C.light;
    } catch (e) { /* no media queries */ }
  }
  if (t) d.setAttribute("data-theme", t);
  d.className += (d.className ? " " : "") + "lg-js lg-boot";

  // The faces are font-display: optional, so whatever is used ~100ms in stays
  // for the visit. Holding the paint until then (no longer) means the page is
  // laid out once, in its final font, instead of re-wrapping when it lands.
  if (document.fonts && document.fonts.load && window.Promise) {
    d.className += " lg-fontwait";
    var shown = function () { d.className = d.className.replace(/\s*\blg-fontwait\b/g, ""); };
    setTimeout(shown, 100);
    // In the frame before the first paint the stylesheet below is parsed and
    // its faces exist; asked from here, load() would find none and resolve.
    requestAnimationFrame(function () {
      Promise.all(C.faces.map(function (f) { return document.fonts.load(f); })).then(shown, shown);
    });
  }

  function detect() {
    var nav = window.navigator || {};
    var ua = nav.userAgent || "";
    var plat = (nav.userAgentData && nav.userAgentData.platform) || nav.platform || "";
    if (/Android|iPhone|iPad|iPod/i.test(ua)) return null;
    if (/Win/i.test(plat) || /Windows/.test(ua)) return "windows";
    if (/Mac/i.test(plat) || /Macintosh/.test(ua)) return nav.maxTouchPoints > 1 ? null : "macos";
    if (/Linux|X11|CrOS/i.test(plat + " " + ua)) {
      if (/Ubuntu/i.test(ua)) return "ubuntu";
      if (/Fedora|SUSE/i.test(ua)) return "fedora";
      if (/Debian/i.test(ua)) return "debian";
      return "linux";
    }
    return null;
  }
  var os = detect();
  if (C.families.indexOf(os) < 0) os = null;
  if (os) d.setAttribute("data-lg-os", os);
  var m = /^#download-([a-z0-9-]+)$/.exec(location.hash || "");
  var open = m ? (C.families.indexOf(m[1]) >= 0 ? m[1] : C.groups[m[1]] || null) : null;
  if (open || os) d.setAttribute("data-lg-open", open || os);

  // The screenshots are baked in the default theme; point each at the chosen
  // one as the parser creates it, before it can paint.
  if (t && t !== C.def && window.MutationObserver) {
    var fix = function (img) {
      img.src = "/assets/shots/" + img.getAttribute("data-lg-shot") + "--" + t + ".png";
    };
    var mo = new MutationObserver(function (recs) {
      for (var i = 0; i < recs.length; i++) {
        var added = recs[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          var n = added[j];
          if (n.nodeType !== 1) continue;
          if (n.hasAttribute("data-lg-shot")) fix(n);
          var inner = n.querySelectorAll ? n.querySelectorAll("img[data-lg-shot]") : [];
          for (var k = 0; k < inner.length; k++) fix(inner[k]);
        }
      }
    });
    mo.observe(d, { childList: true, subtree: true });
    document.addEventListener("DOMContentLoaded", function () { mo.disconnect(); });
  }
})();
