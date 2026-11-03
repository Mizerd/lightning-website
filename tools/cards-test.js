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
// "soon" packages render as muted placeholder rows with no data-lg-pkg.
const live = feed.packages.filter(p => !p.soon);
const installOf = p => String(p.install || "").split("${file}").join(p.file || "");

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
  // Pinned packages are NOT in the release being published -- that is why they
  // are pinned -- so the stub must not offer one, or the "left alone" path
  // would never be exercised.
  const seen = {};
  const assets = live.filter(p => !p.pinned && !p.store && !seen[p.file] && (seen[p.file] = 1)).map(function (p) {
    let name = p.file
      .replace(feed.version, LATEST_VERSION)
      .replace(/-[0-9a-f]{7}-/, "-" + LATEST_SHA + "-");
    return { name: name, url: "https://example.invalid/dl/" + name };
  });
  // Decoys whose names end in a store card's format badge: were pass 2 to
  // match a store card by suffix, it would take one of these.
  assets.push({ name: "decoy-Flathub", url: "https://example.invalid/dl/decoy-Flathub" });
  assets.push({ name: "decoy-COPR", url: "https://example.invalid/dl/decoy-COPR" });
  assets.push({ name: "SHA256SUMS", url: "https://example.invalid/dl/SHA256SUMS" });
  return { version: LATEST_VERSION, released: "2099-01-01", assets: assets,
           release_url: "https://example.invalid/rel" };
}

function run(withLatest, opts) {
  opts = opts || {};
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true,
                                url: "https://www.lightning-matrix.org/" + (opts.hash || "") });
  const feedData = opts.feed || feed;
  if (opts.ua) Object.defineProperty(dom.window.navigator, "userAgent", { value: opts.ua });
  if (opts.platform != null) Object.defineProperty(dom.window.navigator, "platform", { value: opts.platform });
  if (opts.uad) Object.defineProperty(dom.window.navigator, "userAgentData", { value: opts.uad });
  const win = dom.window;
  win.fetch = function (url) {
    if (String(url).indexOf("/releases.json") >= 0) {
      return Promise.resolve({ ok: true, json: function () { return Promise.resolve(JSON.parse(JSON.stringify(feedData))); } });
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
    check("a card per package", els.length === live.length,
          els.length + " cards, " + live.length + " packages");
    if (els.length !== live.length) continue;

    // ---- the defect this file exists for -----------------------------------
    // Every card's install text must be ITS OWN. Compared against the feed,
    // not merely against its neighbours: five cards all showing the AppImage
    // command are five DISTINCT-from-nothing failures that a uniqueness test
    // would catch, but a card silently showing the WRONG one of two real
    // commands would not.
    const wrong = [];
    els.forEach(function (card, i) {
      const pkg = live[i];
      // A pinned card is deliberately left alone by pass 2 (it names an older
      // release's file), so under "feed + /api/latest" its filename must NOT
      // have been rewritten and its button must still point at its own url.
      if (pkg.store) {
        // A store card must keep its own link, label, and no file, under both
        // passes -- pass 2 offers no asset it could be (wrongly) matched to,
        // and must not hide or rewrite the button either.
        const a = card.querySelector("[data-lg-dl]");
        if (!card.hasAttribute("data-lg-store"))
          wrong.push(pkg.format + ": store card lost data-lg-store");
        if (!a || a.hidden || a.getAttribute("href") !== pkg.url)
          wrong.push(pkg.format + ": store card lost its own url");
        if (!a || a.textContent !== pkg.action)
          wrong.push(pkg.format + ": store button says " + (a && a.textContent));
        if (card.getAttribute("data-lg-file") !== "")
          wrong.push(pkg.format + ": store card gained a file");
      }
      if (pkg.note) {
        const n = card.querySelector('[data-lg-bind="pkg.note"]');
        if (!n || n.hidden || n.textContent !== pkg.note)
          wrong.push(pkg.format + ": note missing or wrong");
      } else {
        const n = card.querySelector('[data-lg-bind="pkg.note"]');
        if (n && !n.hidden) wrong.push(pkg.format + ": stray note shown");
      }
      if (pkg.pinned) {
        const a = card.querySelector("[data-lg-dl]");
        if (card.getAttribute("data-lg-file") !== pkg.file)
          wrong.push(pkg.format + ": pinned card was rewritten to "
                     + card.getAttribute("data-lg-file"));
        if (!a || a.hidden || a.getAttribute("href") !== pkg.url)
          wrong.push(pkg.format + ": pinned card lost its own download URL");
      }
      const slot = card.querySelector('[data-lg-bind="pkg.install"]');
      if (!slot) { wrong.push(pkg.format + ": no pkg.install slot"); return; }
      // Pass 2 rewrites the filename inside the command, so compare against
      // the feed's command with the same substitution applied.
      let want = installOf(pkg);
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
          JSON.stringify(fmts) === JSON.stringify(live.map(p => p.format)),
          JSON.stringify(fmts));
    check("every card shows its own label",
          JSON.stringify(labels) === JSON.stringify(live.map(p => p.label)),
          JSON.stringify(labels));

    // ---- the older bug of the same shape -----------------------------------
    const hrefs = els.map(function (c) {
      const a = c.querySelector("[data-lg-dl]");
      return a && !a.hidden ? a.getAttribute("href") : null;
    });
    const present = hrefs.filter(Boolean);
    check("every card has a download button", present.length === els.length,
          present.length + " of " + els.length);
    // Cards sharing a match token share one asset on purpose (openSUSE offers
    // Fedora's .rpm); any other repeat is the cloned-href bug.
    const tokens = els.map(c => (c.getAttribute("data-lg-match") || c.getAttribute("data-lg-format")).toLowerCase());
    const byTok = {};
    let crossed = [];
    els.forEach(function (c, i) {
      const h = hrefs[i];
      if (!h) return;
      if (byTok[tokens[i]] && byTok[tokens[i]] !== h) crossed.push(tokens[i] + " has two URLs");
      byTok[tokens[i]] = h;
    });
    check("every download URL is distinct",
          new Set(present).size === new Set(tokens).size && !crossed.length,
          present.length + " buttons, " + new Set(present).size + " distinct, "
          + new Set(tokens).size + " tokens " + crossed.join("; "));

    const mismatched = [];
    els.forEach(function (card, i) {
      const a = card.querySelector("[data-lg-dl]");
      const file = card.getAttribute("data-lg-file");
      if (card.hasAttribute("data-lg-pinned")) return;
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
      const unpinned = els.filter(c => !c.hasAttribute("data-lg-pinned") && !c.hasAttribute("data-lg-store"));
      const renamed = unpinned.filter(function (c) {
        return String(c.getAttribute("data-lg-file")).indexOf(LATEST_VERSION) >= 0;
      });
      check("card filenames follow the published assets",
            renamed.length === unpinned.length,
            renamed.length + " of " + unpinned.length + " renamed");
    }
  }

  await gridChecks();

  console.log();
  if (failures) { console.log("FAILED: " + failures + " check(s)"); process.exit(1); }
  console.log("all checks passed");
}

// ---- the OS grid: one panel open at a time, deep links, placeholders -------
async function gridChecks() {
  const LINUX_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0";
  const WIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0 Safari/537.36";
  const panels = doc => Array.prototype.slice.call(doc.querySelectorAll("[data-lg-family]"));
  const openIds = doc => panels(doc).filter(p => !p.hidden).map(p => p.getAttribute("data-lg-family"));
  const tile = (doc, id) => doc.querySelector('[data-lg-tile="' + id + '"]');

  console.log("\nOS grid");
  let doc = await run(true, { ua: WIN_UA });
  check("the visitor's OS opens on its own", JSON.stringify(openIds(doc)) === '["windows"]',
        JSON.stringify(openIds(doc)));
  check("and is marked as theirs", !tile(doc, "windows").querySelector("[data-lg-mine]").hidden);
  check("tiles are disclosure buttons",
        panels(doc).every(p => { const t = tile(doc, p.getAttribute("data-lg-family"));
          return t.getAttribute("role") === "button"
            && t.getAttribute("aria-expanded") === String(!p.hidden)
            && t.getAttribute("aria-controls") === p.id; }));

  tile(doc, "linux").click();
  check("a click opens that family and closes the other",
        JSON.stringify(openIds(doc)) === '["linux"]', JSON.stringify(openIds(doc)));
  check("the URL names the open family", doc.location.hash === "#download-linux", doc.location.hash);
  tile(doc, "linux").click();
  check("a second click closes it", openIds(doc).length === 0, JSON.stringify(openIds(doc)));

  tile(doc, "macos").click();
  const inside = doc.querySelector("#download-macos [data-lg-dl]");
  inside.focus();
  inside.dispatchEvent(new doc.defaultView.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  check("Escape inside a panel closes it", openIds(doc).length === 0, JSON.stringify(openIds(doc)));
  check("and returns focus to its tile", doc.activeElement === tile(doc, "macos"));
  tile(doc, "fedora").dispatchEvent(new doc.defaultView.KeyboardEvent("keydown", { key: " ", bubbles: true }));
  check("Space on a tile opens it", JSON.stringify(openIds(doc)) === '["fedora"]', JSON.stringify(openIds(doc)));

  const soon = Array.prototype.slice.call(doc.querySelectorAll("[data-lg-soon]"));
  check("a placeholder row per soon package", soon.length === feed.packages.length - live.length,
        soon.length + " rows");
  check("placeholders carry no link and no command",
        soon.every(r => !r.querySelector("a, [data-lg-copy], [data-lg-copybtn]")));

  doc = await run(true, { ua: WIN_UA, hash: "#download-debian" });
  check("a #download-<family> link opens that family over the detected one",
        JSON.stringify(openIds(doc)) === '["debian"]', JSON.stringify(openIds(doc)));

  // The data model: flipping a placeholder live is a feed change, not markup.
  const flipped = JSON.parse(JSON.stringify(feed));
  const arm = flipped.packages.find(p => p.soon && p.family === "debian");
  delete arm.soon;
  arm.file = "lightning_" + feed.version + "_arm64.deb";
  delete flipped.families.find(f => f.id === "ubuntu").note;
  flipped.packages = flipped.packages.filter(p => p.family !== "macos");
  doc = await run(false, { ua: LINUX_UA, feed: flipped });
  const deb = doc.querySelector('#download-debian [data-lg-file="' + arm.file + '"]');
  check("a live ARM row appears from the feed alone", !!deb);
  check("with its own download and command",
        !!deb && deb.querySelector("[data-lg-dl]").getAttribute("href").endsWith(arm.file)
        && deb.querySelector('[data-lg-bind="pkg.install"]').textContent === "sudo apt install ./" + arm.file);
  check("and the tile's ARM chip goes live",
        tile(doc, "debian").querySelector("[data-lg-tile-arch]").textContent === "x86_64ARM64",
        tile(doc, "debian").querySelector("[data-lg-tile-arch]").textContent);
  check("a family the feed empties is hidden, tile and panel",
        tile(doc, "macos").hidden && doc.getElementById("download-macos").hidden);
  check("a family note the feed drops is hidden",
        doc.querySelector("#download-ubuntu [data-lg-family-note]").hidden);
  check("Linux visitors get the any-distribution card", JSON.stringify(openIds(doc)) === '["linux"]',
        JSON.stringify(openIds(doc)));

  await detectionChecks();
  await placeholderChecks();
  await opensuseChecks();
}

// ---- "Your system": detected, marked, opened and moved to the front --------
async function detectionChecks() {
  console.log("\nYour system");
  const FF = "Gecko/20100101 Firefox/140.0";
  const CASES = [
    ["generic Linux (Chrome)", { ua: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
                                 platform: "Linux x86_64", uad: { platform: "Linux" } }, "linux"],
    ["generic Linux (Firefox)", { ua: "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) " + FF, platform: "Linux x86_64" }, "linux"],
    ["Ubuntu Firefox", { ua: "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:140.0) " + FF, platform: "Linux x86_64" }, "ubuntu"],
    ["Fedora Firefox", { ua: "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:140.0) " + FF, platform: "Linux x86_64" }, "fedora"],
    ["openSUSE Firefox", { ua: "Mozilla/5.0 (X11; openSUSE; Linux x86_64; rv:140.0) " + FF, platform: "Linux x86_64" }, "fedora"],
    ["Debian Firefox", { ua: "Mozilla/5.0 (X11; Debian; Linux x86_64; rv:140.0) " + FF, platform: "Linux x86_64" }, "debian"],
    ["Windows Chrome + Client Hints", { ua: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
                                        platform: "Win32", uad: { platform: "Windows" } }, "windows"],
    ["Windows Firefox", { ua: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) " + FF, platform: "Win32" }, "windows"],
    ["macOS Safari", { ua: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15",
                       platform: "MacIntel" }, "macos"],
    ["macOS Chrome + Client Hints", { ua: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
                                      platform: "MacIntel", uad: { platform: "macOS" } }, "macos"],
    ["Client Hints alone (reduced UA string)", { ua: "Mozilla/5.0 AppleWebKit/537.36 Chrome/140.0", platform: "", uad: { platform: "Windows" } }, "windows"],
    ["Android phone", { ua: "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/140.0 Mobile Safari/537.36",
                        platform: "Linux armv8l", uad: { platform: "Android" } }, null],
  ];
  const baked = Array.from(new JSDOM(html).window.document.querySelectorAll("[data-lg-tile]"))
    .map(t => t.getAttribute("data-lg-tile"));
  for (const [name, opts, want] of CASES) {
    const doc = await run(false, opts);
    const order = Array.from(doc.querySelectorAll("[data-lg-tile]")).map(t => t.getAttribute("data-lg-tile"));
    const mine = Array.from(doc.querySelectorAll("[data-lg-tile]"))
      .filter(t => !t.querySelector("[data-lg-mine]").hidden).map(t => t.getAttribute("data-lg-tile"));
    const open = Array.from(doc.querySelectorAll("[data-lg-family]")).filter(p => !p.hidden)
      .map(p => p.getAttribute("data-lg-family"));
    if (want) {
      const rest = baked.filter(id => id !== want);
      const ok = order[0] === want && JSON.stringify(order.slice(1)) === JSON.stringify(rest)
        && JSON.stringify(mine) === JSON.stringify([want]) && JSON.stringify(open) === JSON.stringify([want]);
      check(name + " -> " + want + ": first, marked, open", ok,
            "order " + order.join(",") + " mine " + mine + " open " + open);
    } else {
      check(name + " -> nothing detected, baked order kept",
            JSON.stringify(order) === JSON.stringify(baked) && !mine.length && !open.length,
            "order " + order.join(",") + " mine " + mine + " open " + open);
    }
  }
  // Tab follows the DOM, so the moved tile must be the grid's first focusable child.
  const doc = await run(false, CASES[6][1]);
  const grid = doc.querySelector(".lg-os-grid");
  check("the moved tile is first in the DOM, so first in Tab order",
        grid.firstElementChild.getAttribute("data-lg-tile") === "windows"
        && grid.querySelectorAll("[data-lg-tile]")[0] === grid.firstElementChild);
}

// ---- every ARM build the new lane makes has a placeholder in its card ------
async function placeholderChecks() {
  console.log("\nARM placeholders");
  const doc = await run(true, {});
  const WANT = [["linux", "AppImage", "-aarch64.AppImage"], ["linux", ".snap", "_arm64.snap"],
                ["debian", ".deb", "_arm64.deb"], ["ubuntu", ".deb", "_ubuntu2604_arm64.deb"],
                ["fedora", ".rpm", ".aarch64.rpm"]];
  WANT.forEach(function ([fam, fmt, match]) {
    const inFeed = feed.packages.filter(p => p.soon && p.family === fam && p.format === fmt && p.match === match);
    const rows = Array.from(doc.querySelectorAll("#download-" + fam + " [data-lg-soon]"))
      .filter(r => r.querySelector(".lg-pkg-fmt").textContent === fmt);
    check(fam + " " + fmt + " ARM64 placeholder (" + match + ")",
          inFeed.length >= 1 && rows.length === inFeed.length
          && rows.every(r => r.querySelector(".lg-arch").textContent === "ARM64"
                             && /Coming soon/.test(r.textContent)
                             && !r.querySelector("a, code, button")),
          inFeed.length + " in feed, " + rows.length + " rows");
    const chips = doc.querySelector('[data-lg-tile="' + fam + '"] [data-lg-tile-arch]').textContent;
    // Linux already has a live ARM64 build (Flathub), so its chip stays solid.
    const liveArm = feed.packages.some(p => p.family === fam && !p.soon
      && [].concat(p.arch || "x86_64").indexOf("aarch64") >= 0);
    check(fam + " tile shows ARM64 " + (liveArm ? "live" : "soon"),
          liveArm ? /ARM64/.test(chips) && !/ARM64 soon/.test(chips) : /ARM64 soon/.test(chips), chips);
  });
  const ids = WANT.map(w => w[2]);
  check("no placeholder match token is a live card's",
        !Array.from(doc.querySelectorAll("[data-lg-match]")).some(c => ids.indexOf(c.getAttribute("data-lg-match")) >= 0));
}

// ---- openSUSE: its own block, logo and zypper row inside the Fedora card --
async function opensuseChecks() {
  console.log("\nopenSUSE");
  const rpm = live.find(p => p.group === "opensuse" && p.format === ".rpm");
  for (const withLatest of [false, true]) {
    const doc = await run(withLatest, {});
    const tag = withLatest ? " (after /api/latest)" : " (feed)";
    const tile = doc.querySelector('[data-lg-tile="fedora"]');
    check("the Fedora tile shows both marks" + tag,
          !!tile.querySelector('use[href="#lg-logo-fedora"]') && !!tile.querySelector('use[href="#lg-logo-opensuse"]'));
    check("the sprite carries the openSUSE mark" + tag, !!doc.getElementById("lg-logo-opensuse"));
    const block = doc.querySelector('#download-fedora [data-lg-group="opensuse"]');
    check("the panel has an openSUSE block" + tag, !!block);
    if (!block) continue;
    check("headed by its own logo and name" + tag,
          !!block.querySelector('.lg-group-head use[href="#lg-logo-opensuse"]')
          && block.querySelector(".lg-group-head h4").textContent === "openSUSE");
    const card = block.querySelector("[data-lg-pkg]");
    const cmd = card && card.querySelector('[data-lg-bind="pkg.install"]').textContent;
    const href = card && card.querySelector("[data-lg-dl]").getAttribute("href");
    const fed = Array.from(doc.querySelectorAll('#download-fedora [data-lg-group="fedora"] [data-lg-pkg][data-lg-format=".rpm"]'))[0];
    const fedHref = fed && fed.querySelector("[data-lg-dl]").getAttribute("href");
    check("with a zypper command for the .rpm" + tag,
          !!cmd && cmd.indexOf("sudo zypper install --allow-unsigned-rpm ./") === 0
          && cmd.slice(-card.getAttribute("data-lg-file").length) === card.getAttribute("data-lg-file"), cmd);
    check("downloading the same file as Fedora's .rpm row" + tag,
          !!href && href === fedHref && href.endsWith(card.getAttribute("data-lg-file"))
          && (!withLatest || card.getAttribute("data-lg-file").indexOf(LATEST_VERSION) >= 0),
          href + " vs " + fedHref);
    check("no dnf in the openSUSE block, no zypper in Fedora's" + tag,
          !/\bdnf\b/.test(block.textContent)
          && !/zypper/.test(doc.querySelector('#download-fedora [data-lg-group="fedora"]').textContent));
  }
  const doc = await run(false, { hash: "#download-opensuse" });
  const open = Array.from(doc.querySelectorAll("[data-lg-family]")).filter(p => !p.hidden).map(p => p.getAttribute("data-lg-family"));
  check("#download-opensuse opens the Fedora / openSUSE card", JSON.stringify(open) === '["fedora"]', JSON.stringify(open));
}

main().catch(function (e) { console.error(e); process.exit(1); });
