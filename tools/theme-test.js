/* Exercises the theme wave in releases.js against the real page.
 *
 *   npm install jsdom          # not a repo dependency
 *   node tools/theme-test.js
 *
 * WHY THIS EXISTS. Picking a theme now runs about a second of machinery: a
 * per-block colour delay written from the click's position, a ring element
 * that has to be taken away again, and seven screenshots cross-faded through
 * overlay <img>s that have to be taken away again too. Every one of those
 * fails QUIETLY -- the page still ends up in the right theme, so a glance
 * says it worked:
 *
 *   * an overlay that is never removed leaves the OLD screenshot sitting at
 *     full opacity over the new one, and a second switch stacks another;
 *   * a `--wave-d` left behind puts a permanent delay on every later colour
 *     change of that block;
 *   * `.lg-wave` left on <html> puts a 720ms transition on every hover on the
 *     page, for the rest of the visit;
 *   * an animated RESTORE (the theme a previous visit chose) would run the
 *     whole wave against a page the reader has not looked at yet.
 *
 * The first of those shipped in the hour this file was written: cleanup hung
 * off requestAnimationFrame alone, and a hidden tab runs no animation frames
 * at all, so the overlays stayed for as long as the reader was away.
 *
 * jsdom lays nothing out, so every rect is zeros and every block would take
 * the same delay. The stub below is what gives the page a geometry to spread
 * the wave across.
 */
const fs = require("fs");
const path = require("path");

let JSDOM;
try {
  ({ JSDOM } = require("jsdom"));
} catch (err) {
  console.error("needs jsdom:  npm install jsdom");
  process.exit(2);
}

const ROOT = path.dirname(__dirname);
const html = fs.readFileSync(ROOT + "/public/index.html", "utf8")
  .replace(/<script src="\/releases\.js" defer><\/script>/, "");
const js = fs.readFileSync(ROOT + "/public/releases.js", "utf8");

let failures = 0;
function check(label, ok, detail) {
  console.log("  %s %s%s", ok ? "ok  " : "FAIL", label,
              ok ? "" : "  -- " + (detail || ""));
  if (!ok) failures++;
}

function page(opts) {
  opts = opts || {};
  // pretendToBeVisual is load-bearing twice: without it jsdom reports
  // visibilityState "prerender", and the page correctly refuses to animate a
  // transition nobody can see -- and it has no requestAnimationFrame at all.
  const dom = new JSDOM(html, { runScripts: "outside-only",
                                pretendToBeVisual: true,
                                url: "https://www.lightning-matrix.org/" });
  const win = dom.window;
  win.fetch = function () { return Promise.reject(new Error("offline")); };
  if (opts.reduceMotion) {
    win.matchMedia = function () { return { matches: true }; };
  }
  if (opts.viewTransitions) {
    // jsdom has neither view transitions nor Element.animate, which is exactly
    // why the primary path would otherwise never be exercised at all: every
    // assertion in this file would silently be about the fallback.
    win.__vt = { starts: 0, animations: [], insideCallback: null };
    win.document.startViewTransition = function (cb) {
      win.__vt.starts++;
      cb();
      win.__vt.insideCallback = win.document.documentElement.getAttribute("data-theme");
      return { ready: Promise.resolve(), finished: Promise.resolve(),
               updateCallbackDone: Promise.resolve() };
    };
    win.Element.prototype.animate = function (frames, options) {
      win.__vt.animations.push({ frames: frames, options: options });
      return { finished: Promise.resolve(), cancel: function () {} };
    };
  }
  if (opts.remembered) {
    try { win.localStorage.setItem("lg-theme", opts.remembered); } catch (e) {}
  }
  // A geometry. Positions come from document order, so blocks land at
  // different distances from the click and the delays have to spread.
  const order = new Map();
  Array.prototype.slice.call(win.document.querySelectorAll("*"))
    .forEach(function (el, i) { order.set(el, i); });
  win.Element.prototype.getBoundingClientRect = function () {
    const i = order.get(this) || 0;
    const top = (i * 31) % 3600, left = (i * 71) % 1300;
    return { x: left, y: top, top: top, left: left,
             right: left + 380, bottom: top + 140, width: 380, height: 140 };
  };
  win.eval(js);
  return win;
}

function click(win, slug) {
  const btn = win.document.querySelector('[data-lg-theme="' + slug + '"]');
  const ev = new win.MouseEvent("click", { bubbles: true });
  // jsdom's MouseEvent honours clientX/clientY only through the init dict on
  // some versions; set them outright so the origin is never 0,0 by accident.
  Object.defineProperty(ev, "clientX", { value: 640 });
  Object.defineProperty(ev, "clientY", { value: 300 });
  btn.dispatchEvent(ev);
  return btn;
}

function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

function shotSuffixes(win) {
  return Array.prototype.slice.call(win.document.querySelectorAll("[data-lg-shot]"))
    .map(function (i) { return String(i.getAttribute("src")).split("--").pop(); });
}

async function main() {
  // ---- a click runs the wave ----------------------------------------------
  const win = page();
  const doc = win.document;
  click(win, "warm");

  check("the theme changes", doc.documentElement.getAttribute("data-theme") === "warm",
        doc.documentElement.getAttribute("data-theme"));
  check("the wave is armed", doc.documentElement.classList.contains("lg-wave"));
  check("one wavefront, not none and not two",
        doc.querySelectorAll(".lg-wavefront").length === 1,
        String(doc.querySelectorAll(".lg-wavefront").length));

  // The delays are the wave. All-equal means every block turns at once, which
  // is the behaviour this replaced.
  const delays = Array.prototype.slice.call(doc.querySelectorAll("[style*='--wave-d']"))
    .map(function (el) { return parseFloat(el.style.getPropertyValue("--wave-d")); });
  check("every block carries a delay", delays.length > 10, delays.length + " blocks");
  check("the delays spread", new Set(delays).size > 5,
        new Set(delays).size + " distinct of " + delays.length);
  check("no delay outruns the wave",
        delays.every(function (d) { return d >= 0 && d <= 400; }),
        "range " + Math.min.apply(null, delays) + ".." + Math.max.apply(null, delays));

  // ---- the pictures cross-fade rather than blink ---------------------------
  await wait(60);
  const shots = doc.querySelectorAll("[data-lg-shot]").length;
  check("an overlay per screenshot",
        doc.querySelectorAll(".lg-shot-x").length === shots,
        doc.querySelectorAll(".lg-shot-x").length + " of " + shots);

  // ---- and NOTHING is left behind -----------------------------------------
  await wait(1600);
  check("every overlay is taken away",
        doc.querySelectorAll(".lg-shot-x").length === 0,
        doc.querySelectorAll(".lg-shot-x").length + " left on the page");
  check("the pictures ended up in the new theme",
        shotSuffixes(win).every(function (s) { return s === "warm.png"; }),
        shotSuffixes(win).join(","));
  check("the wavefront is taken away",
        doc.querySelectorAll(".lg-wavefront").length === 0,
        String(doc.querySelectorAll(".lg-wavefront").length));
  check("the wave is disarmed",
        !doc.documentElement.classList.contains("lg-wave"));
  check("no block keeps a delay",
        doc.querySelectorAll("[style*='--wave-d']").length === 0,
        doc.querySelectorAll("[style*='--wave-d']").length + " left");

  // ---- a restore is not an animation --------------------------------------
  // The theme a previous visit chose is already on screen as far as the reader
  // is concerned; washing it in would be a second of movement nobody asked
  // for, before they have looked at anything.
  const restored = page({ remembered: "storm" });
  check("a remembered theme is applied",
        restored.document.documentElement.getAttribute("data-theme") === "storm",
        restored.document.documentElement.getAttribute("data-theme"));
  check("a remembered theme does not wave",
        !restored.document.documentElement.classList.contains("lg-wave") &&
        restored.document.querySelectorAll(".lg-wavefront").length === 0 &&
        restored.document.querySelectorAll(".lg-shot-x").length === 0);
  check("a remembered theme still moves the pictures",
        shotSuffixes(restored).every(function (s) { return s === "storm.png"; }),
        shotSuffixes(restored).join(","));

  // ---- reduced motion switches, it does not wave --------------------------
  const still = page({ reduceMotion: true });
  click(still, "nordic");
  check("reduced motion switches the theme",
        still.document.documentElement.getAttribute("data-theme") === "nordic",
        still.document.documentElement.getAttribute("data-theme"));
  check("reduced motion runs no wave",
        !still.document.documentElement.classList.contains("lg-wave") &&
        still.document.querySelectorAll(".lg-wavefront").length === 0 &&
        still.document.querySelectorAll(".lg-shot-x").length === 0);
  check("reduced motion still moves the pictures",
        shotSuffixes(still).every(function (s) { return s === "nordic.png"; }),
        shotSuffixes(still).join(","));

  // ---- the snapshot path, where the browser has one ------------------------
  // This is what nearly every reader gets, and it shares none of the fallback's
  // machinery: no per-block delays, no overlay images, no `.lg-wave`. Without
  // the stubs in page() jsdom would take the fallback and every assertion above
  // would be about a path most people never reach.
  const vt = page({ viewTransitions: true });
  click(vt, "deep-teal");
  await wait(80);
  check("the snapshot path is preferred", vt.__vt.starts === 1,
        vt.__vt.starts + " view transitions started");
  check("the theme is changed INSIDE the snapshot callback",
        vt.__vt.insideCallback === "deep-teal",
        String(vt.__vt.insideCallback));
  check("the pictures change inside it too",
        shotSuffixes(vt).every(function (s) { return s === "deep-teal.png"; }),
        shotSuffixes(vt).join(","));

  const clip = vt.__vt.animations.filter(function (a) {
    return a.options && a.options.pseudoElement === "::view-transition-new(root)";
  });
  check("the new page is clipped in, not cross-faded", clip.length === 1,
        vt.__vt.animations.length + " animations, " + clip.length + " on the snapshot");
  if (clip.length === 1) {
    const from = String(clip[0].frames.clipPath[0]);
    const to = String(clip[0].frames.clipPath[1]);
    check("the circle grows from the click", /^circle\(0px at 640px 300px\)$/.test(from), from);
    const r = parseFloat((/circle\((\d+)px/.exec(to) || [])[1]);
    check("the circle reaches past the far corner", r > 300, to);
    check("the sweep is slow enough to read",
          clip[0].options.duration >= 600 && clip[0].options.duration <= 1200,
          String(clip[0].options.duration));
  }
  check("the fallback's machinery is not used as well",
        !vt.document.documentElement.classList.contains("lg-wave") &&
        vt.document.querySelectorAll(".lg-shot-x").length === 0 &&
        vt.document.querySelectorAll("[style*='--wave-d']").length === 0);
  await wait(1200);
  check("the snapshot path cleans up after itself",
        vt.document.querySelectorAll(".lg-wavefront").length === 0,
        String(vt.document.querySelectorAll(".lg-wavefront").length));

  console.log();
  if (failures) { console.log("FAILED: " + failures + " check(s)"); process.exit(1); }
  console.log("all theme checks passed");
}

main().catch(function (e) { console.error(e); process.exit(1); });
