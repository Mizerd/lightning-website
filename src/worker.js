/* Cloudflare Worker for lightning-matrix.org.
 *
 * The site is static; this exists for exactly one route. GET /api/latest
 * reports the newest Lightning release -- version, date and the download URL
 * for each asset -- so the download buttons follow a new release without
 * anyone editing this repository.
 *
 * Why proxy it instead of calling api.github.com from the page:
 *   - the browser only ever talks to this origin, so the site's CSP stays
 *     locked to connect-src 'self'
 *   - no visitor's IP is handed to GitHub just for loading the page, which
 *     matters for a client whose whole pitch is not leaking anything
 *   - one cached edge response serves everyone, instead of every visitor
 *     spending their own 60-requests-per-hour GitHub rate limit
 *
 * Static assets are served by Cloudflare's asset layer BEFORE this code runs
 * (run_worker_first is not set), so a normal page load never enters the
 * Worker. Only unmatched paths arrive here -- hence the deferral back to
 * env.ASSETS at the bottom, which is what keeps 404.html working.
 */

const REPO = "Mizerd/lightning";
const UPSTREAM = `https://api.github.com/repos/${REPO}/releases/latest`;

// GitHub rejects API requests without a User-Agent.
const UA = "lightning-matrix.org (+https://www.lightning-matrix.org)";

// Long enough that a traffic spike costs GitHub one request; short enough that
// a new release shows up promptly.
const TTL = 300;

function json(body, status, cacheSeconds) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": cacheSeconds
        ? `public, max-age=${cacheSeconds}`
        : "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

async function latestRelease() {
  // cacheEverything + cacheTtl let one edge-cached upstream response serve
  // every visitor, regardless of what cache headers GitHub happens to send.
  const res = await fetch(UPSTREAM, {
    headers: {
      accept: "application/vnd.github+json",
      "user-agent": UA,
    },
    cf: { cacheEverything: true, cacheTtl: TTL },
  });

  if (!res.ok) {
    return { error: `github responded ${res.status}` };
  }

  const rel = await res.json();
  if (!rel || typeof rel.tag_name !== "string") {
    return { error: "unexpected github payload" };
  }

  return {
    // "v0.7.4" -> "0.7.4"; the site prints the bare number.
    version: rel.tag_name.replace(/^v/, ""),
    released: (rel.published_at || "").slice(0, 10),
    release_url: rel.html_url || "",
    assets: (rel.assets || []).map((a) => ({
      name: a.name,
      size: a.size,
      url: a.browser_download_url,
    })),
  };
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);

    if (pathname === "/api/latest") {
      if (request.method !== "GET" && request.method !== "HEAD") {
        return json({ error: "method not allowed" }, 405, 0);
      }
      try {
        const data = await latestRelease();
        // Upstream trouble is reported as 502 and deliberately not cached, so
        // a blip does not stick around. The page keeps its built-in values.
        if (data.error) return json(data, 502, 0);
        return json(data, 200, TTL);
      } catch (err) {
        return json({ error: String((err && err.message) || err) }, 502, 0);
      }
    }

    // Not an asset and not our one route: hand back to the asset layer so its
    // not_found_handling serves 404.html.
    return env.ASSETS.fetch(request);
  },
};
