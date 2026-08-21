/* Exercises the full-screen screenshot overlay against the real index.html
 * and the real releases.js, on both /api/latest code paths.
 *
 *   npm install jsdom          # not a repo dependency
 *   node tools/lightbox-test.js
 *
 * jsdom, because this is about DOM and event order. Anything about LAYOUT
 * needs a real browser -- see "Checking a change" in the README.
 *
 * The assertions that matter most are the negative ones: clicking the image
 * must NOT close the overlay (that is what lets you pinch and pan a
 * screenshot on a phone), and the second open must reuse the overlay rather
 * than build another one.
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
const feed = fs.readFileSync(ROOT + "/public/releases.json", "utf8");

let fails = 0;
function ok(label, cond, detail) {
  if (!cond) fails++;
  console.log("  " + (cond ? "ok  " : "FAIL") + " " + label +
              (cond ? "" : "  -- " + detail));
}

async function run(apiUp) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  const doc = window.document;

  window.fetch = (url) => {
    if (url === "/releases.json")
      return Promise.resolve({ ok: true, json: () => Promise.resolve(JSON.parse(feed)) });
    if (url === "/api/latest" && apiUp)
      return Promise.resolve({ ok: true, json: () => Promise.resolve({
        version: "9.9.9", released: "2026-08-21",
        release_url: "https://github.com/Mizerd/lightning/releases/tag/v9.9.9",
        assets: [] }) });
    return Promise.reject(new Error("down"));
  };
  window.eval(js);
  await new Promise((r) => window.setTimeout(r, 60));

  const tag = apiUp ? "/api/latest UP  " : "/api/latest DOWN";
  console.log("\n" + tag);

  // --- the triggers ---------------------------------------------------
  const btns = doc.querySelectorAll("[data-lg-zoom]");
  ok(tag + " four zoom triggers", btns.length === 4, btns.length + " found");
  const hints = [...doc.querySelectorAll("[data-lg-zoomhint]")];
  ok(tag + " every Expand badge revealed",
     hints.length === 4 && hints.every((h) => !h.hidden),
     hints.filter((h) => h.hidden).length + " still hidden");

  // Every screenshot must carry its own dimensions, or the box is 0px tall
  // until the image lands.
  const imgs = [...doc.querySelectorAll('img[src^="/assets/screenshot-"]')];
  ok(tag + " every screenshot has width and height",
     imgs.length === 4 && imgs.every((i) => +i.getAttribute("width") > 0 &&
                                            +i.getAttribute("height") > 0),
     imgs.map((i) => i.getAttribute("width") + "x" + i.getAttribute("height")).join(" "));

  // --- opening ---------------------------------------------------------
  ok(tag + " no overlay before a click",
     !doc.querySelector(".lg-lightbox"), "one exists already");

  const click = (el) => el.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  click(btns[0].querySelector("img"));   // click the picture, as a reader would
  const lb = doc.querySelector(".lg-lightbox");
  ok(tag + " a click opens the overlay", lb && !lb.hidden, "no overlay");
  const lbImg = lb && lb.querySelector("img");
  ok(tag + " it shows the image that was clicked",
     lbImg && lbImg.getAttribute("src") === btns[0].querySelector("img").getAttribute("src"),
     lbImg ? lbImg.getAttribute("src") : "no img");
  ok(tag + " it carries the figure's caption",
     lb.querySelector("figcaption").textContent.indexOf("GIF picker") !== -1,
     lb.querySelector("figcaption").textContent);
  ok(tag + " the page behind it is locked",
     doc.documentElement.classList.contains("lg-lbopen") &&
     doc.body.classList.contains("lg-lbopen"), "scroll not locked");
  ok(tag + " it is announced as a dialog",
     lb.getAttribute("role") === "dialog" && lb.getAttribute("aria-modal") === "true",
     lb.getAttribute("role"));

  // --- clicking the image must NOT close it (pinch and pan on a phone) --
  click(lbImg);
  ok(tag + " clicking the image keeps it open", !lb.hidden, "closed on the image");

  // --- clicking anywhere else closes -----------------------------------
  click(lb);
  ok(tag + " clicking the backdrop closes", lb.hidden, "still open");
  ok(tag + " the scroll lock is released",
     !doc.documentElement.classList.contains("lg-lbopen") &&
     !doc.body.classList.contains("lg-lbopen"), "lock stuck on");
  ok(tag + " the image is dropped when closed",
     !lbImg.getAttribute("src"), "src still set");

  // --- the close button -------------------------------------------------
  click(btns[1]);
  ok(tag + " a second screenshot opens", !lb.hidden, "did not reopen");
  ok(tag + " the overlay is reused, not rebuilt",
     doc.querySelectorAll(".lg-lightbox").length === 1,
     doc.querySelectorAll(".lg-lightbox").length + " overlays");
  click(lb.querySelector(".lg-lbclose"));
  ok(tag + " the close button closes", lb.hidden, "still open");

  // --- Escape ------------------------------------------------------------
  click(btns[2]);
  doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  ok(tag + " Escape closes", lb.hidden, "still open");

  // --- focus returns to the trigger --------------------------------------
  click(btns[3]);
  const closeBtn = lb.querySelector(".lg-lbclose");
  ok(tag + " focus moves into the overlay", doc.activeElement === closeBtn,
     doc.activeElement && doc.activeElement.className);
  doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  ok(tag + " focus returns to the screenshot", doc.activeElement === btns[3],
     doc.activeElement && doc.activeElement.tagName);

  // --- the structured data keeps up with the version ---------------------
  const ld = JSON.parse(doc.querySelector('script[type="application/ld+json"]').textContent);
  const shown = doc.querySelector('[data-lg-bind="version"]').textContent;
  ok(tag + " JSON-LD version matches the page", ld.softwareVersion === shown,
     ld.softwareVersion + " vs " + shown);
  ok(tag + " JSON-LD points back at GitHub",
     Array.isArray(ld.sameAs) && ld.sameAs[0].indexOf("github.com") !== -1,
     JSON.stringify(ld.sameAs));

  // --- nothing regressed in the copy buttons -----------------------------
  const copy = [...doc.querySelectorAll("[data-lg-copybtn]")];
  ok(tag + " copy buttons still revealed",
     copy.length === 6 && copy.every((b) => !b.hidden),
     copy.length + " buttons, " + copy.filter((b) => b.hidden).length + " hidden");
}

(async () => {
  await run(true);
  await run(false);
  console.log(fails ? "\nFAILED: " + fails : "\nall lightbox checks passed");
  process.exit(fails ? 1 : 0);
})();
