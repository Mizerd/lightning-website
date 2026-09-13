/* Exercises the package-card rebuild against the real index.html and the real
 * releases.js, on both /api/latest code paths.
 *
 *   npm install jsdom          # not a repo dependency
 *   node tools/cards-test.js
 *
 * WHY THIS EXISTS. releases.js rebuilds every card at runtime by CLONING CARD
 * ZERO and writing each package's own values into the [data-lg-bind] slots it
 * finds. A card that is missing a slot silently keeps CARD ZERO'S value -- and
 * the baked HTML looks perfect while it happens, because the miss only shows
 * once the script runs. check.py cannot see it: it has no DOM.
 *
 * Twice now that has shipped. First the download buttons, where every Linux
 * button served the .deb and every Windows button the .msi. Then, in the
 * 2026-09-13 redesign, the install COMMAND: the new generator put the text
 * straight into the <code> without data-lg-bind="pkg.install", so every Linux
 * card told the reader to chmod the AppImage -- including the .deb, .rpm and
 * .snap cards.
 *
 * Both passes are tested, and separately, BECAUSE THEY MASK EACH OTHER: pass 2
 * sets every href by asset suffix, so it papers over a broken rebuild in pass
 * 1. The pass-2 stub therefore reports a DIFFERENT version and build sha from
 * releases.json, which is that pass's whole job -- a stub echoing the feed back
 * would prove nothing about it.
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
const feed = JSON.parse(fs.readFileSync(ROOT + "/public/releases.json", "utf8"));

let failures = 0;
function check(label, ok, detail) {
  console.log("  %s %s%s", ok ? "ok  " : "FAIL", label,
              ok ? "" : "  -- " + (detail || ""));
  if (!ok) failures++;
}

// The pass-2 stub. A real release renames the Windows and macOS assets (they
// carry the release commit's short sha), so the names here deliberately differ
// from the feed's -- that difference is what proves the filename rewrite runs.
const LATEST_VERSION = "9.9.9";
const LATEST_SHA = "deadbee";
function latestPayload() {
  const assets = feed.packages.map(function (p) {
    let name = p.file
      .replace(feed.version, LATEST_VERSION)
      .replace(/-[0-9a-f]{7}-/, "-" + LATEST_SHA + "-");
    return { name: name, url: "https://example.invalid/dl/" + name };
  });
  assets.push({ name: "SHA256SUMS", url: "https://example.invalid/dl/SHA256SUMS" });
  return { version: LATEST_VERSION, released: "2099-01-01", assets: assets,
           release_url: "https://example.invalid/rel" };
}

function run(withLatest) {
  const dom = new JSDOM(html, { runScripts: "outside-only", url: "https://www.lightning-matrix.org/" });
  const win = dom.window;
  win.fetch = function (url) {
    if (String(url).indexOf("/releases.json") >= 0) {
      return Promise.resolve({ ok: true, json: function () { return Promise.resolve(feed); } });
    }
    if (String(url).indexOf("/api/latest") >= 0) {
      if (!withLatest) return Promise.resolve({ ok: false, json: function () { return Promise.resolve(null); } });
      return Promise.resolve({ ok: true, json: function () { return Promise.resolve(latestPayload()); } });
    }
    return Promise.reject(new Error("unexpected fetch " + url));
  };
  win.eval(js);
  // Both passes are promise chains off fetch; three macrotask turns is ample
  // and does not depend on how many links the chain has.
  return new Promise(function (resolve) {
    setTimeout(function () { setTimeout(function () { setTimeout(function () {
      resolve(win.document);
    }, 0); }, 0); }, 0);
  });
}

function cards(doc) {
  return Array.prototype.slice.call(doc.querySelectorAll("[data-lg-pkg]"));
}

async function main() {
  for (const withLatest of [false, true]) {
    const label = withLatest ? "feed + /api/latest" : "feed only (/api/latest fails)";
    console.log("\n" + label);
    const doc = await run(withLatest);
    const els = cards(doc);

    // Count off the page, never write the number down: the package set changes
    // whenever the release does.
    check("a card per package", els.length === feed.packages.length,
          els.length + " cards, " + feed.packages.length + " packages");
    if (els.length !== feed.packages.length) continue;

    // ---- the defect this file exists for -----------------------------------
    // Every card's install text must be ITS OWN. Compared against the feed,
    // not merely against its neighbours: five cards all showing the AppImage
    // command are five DISTINCT-from-nothing failures that a uniqueness test
    // would catch, but a card silently showing the WRONG one of two real
    // commands would not.
    const wrong = [];
    els.forEach(function (card, i) {
      const pkg = feed.packages[i];
      const slot = card.querySelector('[data-lg-bind="pkg.install"]');
      if (!slot) { wrong.push(pkg.format + ": no pkg.install slot"); return; }
      // Pass 2 rewrites the filename inside the command, so compare against
      // the feed's command with the same substitution applied.
      let want = pkg.install;
      if (withLatest) {
        const asset = card.getAttribute("data-lg-file");
        if (asset && asset !== pkg.file) want = want.split(pkg.file).join(asset);
      }
      if (slot.textContent !== want) {
        wrong.push(pkg.format + ": " + JSON.stringify(slot.textContent)
                   + " want " + JSON.stringify(want));
      }
    });
    check("every card shows its own install command", !wrong.length, wrong.join("; "));

    const fmts = [], labels = [];
    els.forEach(function (card, i) {
      const f = card.querySelector('[data-lg-bind="pkg.format"]');
      const l = card.querySelector('[data-lg-bind="pkg.label"]');
      fmts.push(f ? f.textContent : "(missing)");
      labels.push(l ? l.textContent : "(missing)");
    });
    check("every card shows its own format",
          JSON.stringify(fmts) === JSON.stringify(feed.packages.map(p => p.format)),
          JSON.stringify(fmts));
    check("every card shows its own label",
          JSON.stringify(labels) === JSON.stringify(feed.packages.map(p => p.label)),
          JSON.stringify(labels));

    // ---- the older bug of the same shape -----------------------------------
    const hrefs = els.map(function (c) {
      const a = c.querySelector("[data-lg-dl]");
      return a && !a.hidden ? a.getAttribute("href") : null;
    });
    const present = hrefs.filter(Boolean);
    check("every card has a download button", present.length === els.length,
          present.length + " of " + els.length);
    check("every download URL is distinct",
          new Set(present).size === present.length,
          present.length + " buttons, " + new Set(present).size + " distinct");

    const mismatched = [];
    els.forEach(function (card, i) {
      const a = card.querySelector("[data-lg-dl]");
      const file = card.getAttribute("data-lg-file");
      if (a && file && !String(a.getAttribute("href")).endsWith(file)) {
        mismatched.push(file + " -> " + a.getAttribute("href"));
      }
    });
    check("each button points at its own card's file", !mismatched.length,
          mismatched.join("; "));

    // The copy buttons are revealed only at the end of the chain, on whatever
    // cards are in the document by then -- a rebuild that ran after the reveal
    // would put hidden buttons back on the page.
    const btns = Array.prototype.slice.call(doc.querySelectorAll("[data-lg-copybtn]"));
    check("every copy button was revealed", btns.length > 0 && btns.every(b => !b.hidden),
          btns.filter(b => b.hidden).length + " of " + btns.length + " still hidden");

    // ---- pass 2 actually ran ----------------------------------------------
    // Without this the whole "feed + /api/latest" run could be a second copy
    // of the feed-only run and every assertion above would still pass.
    if (withLatest) {
      const shown = Array.prototype.slice.call(doc.querySelectorAll('[data-lg-bind="version"]'))
        .map(function (e) { return e.textContent; });
      check("the page follows the published version",
            shown.length > 0 && shown.every(v => v === LATEST_VERSION),
            JSON.stringify(shown));
      const renamed = els.filter(function (c) {
        return String(c.getAttribute("data-lg-file")).indexOf(LATEST_VERSION) >= 0;
      });
      check("card filenames follow the published assets",
            renamed.length === els.length,
            renamed.length + " of " + els.length + " renamed");
    }
  }

  console.log();
  if (failures) { console.log("FAILED: " + failures + " check(s)"); process.exit(1); }
  console.log("all checks passed");
}

main().catch(function (e) { console.error(e); process.exit(1); });
