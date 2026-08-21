/* State for the page's motion. Not the motion itself.
 *
 * Almost everything that moves is CSS -- see the block that unbundle.py
 * writes into <head>. This file only supplies what the stylesheet cannot work
 * out on its own:
 *
 *   1.  whether the page has scrolled away from the top  (header.lg-stuck)
 *   1b. how far down it is                               (the progress bar)
 *   2.  which section is on screen                       (.lg-navlink.lg-here)
 *   3.  where the pointer is inside a panel              (--lg-mx / --lg-my)
 *   4.  the scroll reveals, where the browser has no scroll timelines
 *
 * Keeping it that way matters. The artifact's reset already carries
 *
 *   @media (prefers-reduced-motion: reduce) {
 *     *, *::before, *::after { animation: none !important;
 *                              transition: none !important; }
 *   }
 *
 * so a reader who has asked for less movement gets none of this for free --
 * there is no second switch here that could be forgotten. The one thing that
 * is checked below is the pointer tracking, and only because writing a custom
 * property forty times a second to drive an effect that has been turned off
 * is wasted work, not because it would be visible.
 *
 * If this file never loads, the page is exactly what it was: the header keeps
 * its resting colour, no nav link is marked, and panels do not light up.
 */
(function () {
  "use strict";

  var reduced = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- 1. has the page left the top? ------------------------------------
   *
   * An IntersectionObserver on a one-pixel sentinel at the top of the
   * document, rather than a scroll listener. This fires twice in the life of
   * a visit -- once on the way down, once on the way back -- where a scroll
   * listener runs on every frame of every scroll to answer the same question.
   */
  var top = document.querySelector("[data-lg-top]");
  var header = document.querySelector("header");
  if (top && header && window.IntersectionObserver) {
    new IntersectionObserver(function (entries) {
      header.classList.toggle("lg-stuck", !entries[0].isIntersecting);
    }).observe(top);
  }

  /* ---- 1b. how far down is it? -------------------------------------------
   *
   * `animation-timeline: scroll(root block)` would do this in CSS, off the
   * main thread, and is the right answer everywhere it works. It is not used
   * because Firefox does not support scroll-driven animations, and Firefox is
   * not a rounding error for a Linux Matrix client.
   *
   * So: a passive listener, coalesced onto a frame. The listener itself does
   * nothing but set a flag -- all the reading and writing happens once per
   * frame, inside the rAF callback, which is what keeps a scroll from turning
   * into a layout thrash.
   */
  var bar = document.querySelector(".lg-progress");
  if (bar && window.requestAnimationFrame) {
    var queued = false;

    var paint = function () {
      queued = false;
      var de = document.documentElement;
      var span = de.scrollHeight - de.clientHeight;
      var at = span > 0 ? (window.pageYOffset || de.scrollTop) / span : 0;
      bar.style.transform = "scaleX(" + Math.min(1, Math.max(0, at)) + ")";
    };

    var queue = function () {
      if (queued) return;
      queued = true;
      window.requestAnimationFrame(paint);
    };

    window.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", queue, { passive: true });
    paint();
  }

  /* ---- 2. which section is on screen? ------------------------------------
   *
   * Only sections that a nav link actually points at, so the observer is not
   * watching things nothing can highlight.
   *
   * rootMargin pulls the top of the viewport down past the sticky header and
   * leaves only a band across the upper middle of the screen. Without it the
   * section being scrolled *out* of view stays "current" until its last pixel
   * leaves, so the marker lags a whole section behind the reader.
   */
  var links = {};
  [].forEach.call(document.querySelectorAll(".lg-navlink[href^='#']"),
    function (a) { links[a.getAttribute("href").slice(1)] = a; });

  var watched = Object.keys(links)
    .map(function (id) { return document.getElementById(id); })
    .filter(Boolean);

  if (watched.length && window.IntersectionObserver) {
    var visible = Object.create(null);

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) visible[e.target.id] = e.boundingClientRect.top;
        else delete visible[e.target.id];
      });

      // More than one section can be inside the band at once. The one nearest
      // the top of it is the one being read. If none is -- between two long
      // sections, or at the very bottom -- the last mark stands rather than
      // clearing, so the nav never flickers back to nothing mid-scroll.
      var ids = Object.keys(visible);
      if (!ids.length) return;
      ids.sort(function (a, b) { return visible[a] - visible[b]; });

      for (var key in links) {
        links[key].classList.toggle("lg-here", key === ids[0]);
      }
    }, { rootMargin: "-45% 0px -45% 0px" });

    watched.forEach(function (el) { io.observe(el); });
  }

  /* ---- 3. where is the pointer? ------------------------------------------
   *
   * One listener on the document rather than two per panel: there are
   * seventeen panels, and delegation also survives releases.js rebuilding the
   * package cards with cloneNode, which does not copy listeners.
   *
   * Coordinates are written as percentages so the gradient does not have to
   * be recomputed against the element's pixel size, and are only written when
   * they have actually changed by a whole percent -- a mousemove fires far
   * more often than a gradient needs to move.
   */
  if (!reduced && window.matchMedia &&
      window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    var lastEl = null, lastX = -1, lastY = -1;

    document.addEventListener("mousemove", function (ev) {
      var card = ev.target && ev.target.closest
        ? ev.target.closest(".lg-card") : null;
      if (!card) { lastEl = null; return; }

      var r = card.getBoundingClientRect();
      if (!r.width || !r.height) return;
      var x = Math.round(((ev.clientX - r.left) / r.width) * 100);
      var y = Math.round(((ev.clientY - r.top) / r.height) * 100);
      if (card === lastEl && x === lastX && y === lastY) return;

      lastEl = card; lastX = x; lastY = y;
      card.style.setProperty("--lg-mx", x + "%");
      card.style.setProperty("--lg-my", y + "%");
    }, { passive: true });
  }

  /* ---- 4. the scroll reveals, where there are no scroll timelines --------
   *
   * Sixteen elements in the artifact animate with
   *
   *     animation: lgRise ... both;
   *     animation-timeline: view();
   *     animation-range: entry 0% cover 20%;
   *
   * which ties the animation's progress to the element's own passage through
   * the viewport. Chrome and Safari do this. **Firefox does not** -- it drops
   * `animation-timeline` as unrecognised and the animation falls back to the
   * document timeline, meaning it runs to completion during page load. Every
   * reveal on the page has therefore already happened by the time you scroll
   * to it, and Firefox users see a page with no reveals at all. Nothing is
   * broken or hidden, which is why this survived: `both` leaves each element
   * at its finished state.
   *
   * So where the browser has no scroll timelines, they are driven from here
   * instead. The animation is paused (with `both` fill that holds it at the
   * `from` state -- opacity 0) and released when the element reaches the
   * viewport.
   *
   * This is deliberately the LAST thing the file does. If any of it throws,
   * or the file never loads, nothing is left paused: no element is touched
   * until the moment it is also given an observer that will start it again.
   */
  var noTimelines = !(window.CSS && CSS.supports &&
                      CSS.supports("animation-timeline: view()"));

  if (noTimelines && !reduced && window.IntersectionObserver) {
    var reveals = document.querySelectorAll('[style*="animation-timeline"]');

    var revealer = new IntersectionObserver(function (entries, obs) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.style.animationPlayState = "running";
        obs.unobserve(e.target);
      });
    }, { rootMargin: "0px 0px -12% 0px" });

    [].forEach.call(reveals, function (el) {
      // Paused and observed together, so an element can never end up held at
      // opacity 0 with nothing left to start it.
      el.style.animationPlayState = "paused";
      revealer.observe(el);
    });
  }
})();
