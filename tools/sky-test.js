/* Exercises the constellation generator in releases.js against the real page.
 *
 *   npm install jsdom          # not a repo dependency
 *   node tools/sky-test.js
 *
 * WHY THIS EXISTS. check.py can see the BAKED field -- it is text in
 * index.html -- and can see nothing at all about the one a reader actually
 * gets, which releases.js rolls at load time in the layer's real pixel size.
 * Three things about that field are silently wrong rather than loudly wrong:
 *
 *   * a placement bug that puts stars outside the viewBox clips away without a
 *     word, so the sky simply gets emptier as the arithmetic drifts;
 *   * a density that does not follow the area gives a phone a handful of
 *     boulders and a 4K panel a fine mist, and both look deliberate;
 *   * a generator that stops rolling -- a cached seed, a memoised field --
 *     leaves a page that still has a sky, just always the same one, which is
 *     the whole feature quietly gone.
 *
 * jsdom lays nothing out, so every getBoundingClientRect is zeros and the
 * generator correctly refuses to draw. The stub below is what gives it a box.
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

// One page with the sky laid out at a given size. Everything else measures
// zero, which is what the rest of the script already copes with. The returned
// handle can be RESIZED, which is the only way to reach the repaint path:
// jsdom has no ResizeObserver, so releases.js takes its window-resize
// fallback, and both call the same debounced check.
function page(w, h) {
  const dom = new JSDOM(html, { runScripts: "outside-only",
                                url: "https://www.lightning-matrix.org/" });
  const win = dom.window;
  win.fetch = function () { return Promise.reject(new Error("offline")); };
  const box = { w: w, h: h };
  const zero = { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0,
                 width: 0, height: 0 };
  win.Element.prototype.getBoundingClientRect = function () {
    if (this.getAttribute && this.getAttribute("class") === "lg-sky") {
      return { x: 0, y: 0, top: 0, left: 0, right: box.w, bottom: box.h,
               width: box.w, height: box.h };
    }
    return zero;
  };
  win.eval(js);                       // paintSky() runs as the script is read
  return {
    svg: win.document.querySelector("svg.lg-sky"),
    resize: function (nw, nh) {
      box.w = nw;
      box.h = nh;
      win.dispatchEvent(new win.Event("resize"));
      // Longer than the 220ms debounce, and measured from here rather than
      // assumed: a test that reads before the timer fires passes on a
      // generator that never repaints at all.
      return new Promise(function (done) { setTimeout(done, 400); });
    }
  };
}

function skyAt(w, h) { return page(w, h).svg; }

function numbers(svg, sel, attrs) {
  const out = [];
  svg.querySelectorAll(sel).forEach(function (el) {
    attrs.forEach(function (a) { out.push(parseFloat(el.getAttribute(a))); });
  });
  return out;
}

const svg = skyAt(1400, 6800);

check("the field is rolled at the layer's own size",
      svg.getAttribute("viewBox") === "0 0 1400 6800",
      svg.getAttribute("viewBox"));

const lines = svg.querySelectorAll("line").length;
const stars = svg.querySelectorAll("circle").length;
check("there are figures, not just dust", lines >= 20 && stars >= 100,
      lines + " lines, " + stars + " stars");
check("exactly one accent star",
      svg.querySelectorAll(".lg-sky-mark").length === 1,
      String(svg.querySelectorAll(".lg-sky-mark").length));

// Everything drawn has to be INSIDE the box, or it is clipped away in silence.
// A small overhang is deliberate -- a constellation may sit half off the edge,
// which is what a sky does -- so the tolerance is one figure's width.
const xs = numbers(svg, "circle", ["cx"]).concat(numbers(svg, "line", ["x1", "x2"]));
const ys = numbers(svg, "circle", ["cy"]).concat(numbers(svg, "line", ["y1", "y2"]));
check("nothing is drawn off the edge",
      Math.min.apply(null, xs) > -220 && Math.max.apply(null, xs) < 1400 + 220 &&
      Math.min.apply(null, ys) > -220 && Math.max.apply(null, ys) < 6800 + 220,
      "x " + Math.min.apply(null, xs).toFixed(0) + ".." + Math.max.apply(null, xs).toFixed(0) +
      "  y " + Math.min.apply(null, ys).toFixed(0) + ".." + Math.max.apply(null, ys).toFixed(0));

// Stars now fill the WHOLE field, centre included -- the layer sits behind
// the text at a low opacity, so the middle must not be an empty lane. The
// centre column is 72% of the width, so a roughly uniform field puts most
// stars there; assert it is populated rather than carved out.
let inColumn = 0;
svg.querySelectorAll("circle").forEach(function (c) {
  const x = parseFloat(c.getAttribute("cx"));
  if (x > (1400 - 1008) / 2 && x < (1400 + 1008) / 2) inColumn++;
});
check("the centre is filled, not carved out", inColumn > stars * 0.4,
      inColumn + " of " + stars + " stars are in the centre column");

// Density follows the area. A quarter of the page must not carry the same
// number of stars as the whole of it.
const small = skyAt(700, 3400);
const smallStars = small.querySelectorAll("circle").length;
check("the density follows the area",
      smallStars > stars * 0.12 && smallStars < stars * 0.45,
      smallStars + " stars at a quarter of the area, " + stars + " at full");

// And it is a different sky every time, which is the point of it.
const again = skyAt(1400, 6800);
check("a fresh field on every load",
      again.innerHTML !== svg.innerHTML,
      "two loads produced byte-identical skies");

// The document changes shape after the first paint -- fonts land, images
// decode, somebody drags a window edge -- and a field generated for the old
// shape is either clipped or short.
async function repaint() {
  const p = page(1400, 6800);
  const before = p.svg.getAttribute("viewBox");
  await p.resize(1400, 6805);
  check("a few pixels do not reroll the sky",
        p.svg.getAttribute("viewBox") === before,
        "rerolled for a 5px change: " + p.svg.getAttribute("viewBox"));
  await p.resize(700, 9200);
  check("a real change repaints at the new size",
        p.svg.getAttribute("viewBox") === "0 0 700 9200",
        p.svg.getAttribute("viewBox"));

  console.log();
  if (failures) { console.log("FAILED: " + failures + " check(s)"); process.exit(1); }
  console.log("all sky checks passed");
}

repaint().catch(function (e) { console.error(e); process.exit(1); });
