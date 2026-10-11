// food-lens PWA. No build step, no framework: hash routes render into #app.
//
//   #/            home: scan button, search, recent scans
//   #/scan        live camera scanner
//   #/search/<q>  keyword search results
//   #/p/<barcode> result: score, risky ingredients, why, alternatives

import { startScanner, validGtin } from "./scanner.js";

const app = document.getElementById("app");
const HISTORY_KEY = "fl.history.v1";
const INSTALL_DISMISSED_KEY = "fl.install.dismissed";
let cleanup = null; // teardown for the current view (e.g. stop the camera)

// ---------------------------------------------------------------- helpers

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (typeof u === "string" && u.startsWith("https://") ? u : "");
// in-app navigation depth lives in history.state, so Back buttons know whether
// there's an app page to go back to (deep links / home-screen shortcuts start at 0)
let pendingNav = null;
const go = (hash, replace = false) => {
  pendingNav = replace ? "replace" : "push";
  if (replace) location.replace(hash); else location.hash = hash;
};
const goBack = () => {
  if ((history.state?.depth ?? 0) > 0) history.back();
  else go("#/", true);
};

const icons = {
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  scan: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 8v8M10 8v8M13 8v8M16 8v8" stroke-width="1.6"/></svg>',
  torch: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L4 14h7l-1 8 9-12h-7z"/></svg>',
  scanSmall: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M8 8v8M12 8v8M16 8v8"/></svg>',
};

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(path) {
  let res;
  try {
    res = await fetch(path, { headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError(navigator.onLine ? "Couldn't reach the server." : "You're offline.", 0);
  }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${res.status}).`;
    throw new ApiError(detail, res.status);
  }
  return body;
}

// ---------------------------------------------------------------- history

function getHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; } catch { return []; }
}
function addHistory(entry) {
  try {
    const list = getHistory().filter((h) => h.barcode !== entry.barcode);
    list.unshift({ ...entry, ts: Date.now() });
    localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, 30)));
  } catch { /* storage full/blocked: history is a nicety */ }
}
function clearHistory() {
  try { localStorage.removeItem(HISTORY_KEY); } catch { /* ignore */ }
}

// ---------------------------------------------------------------- shared bits

function thumb(url, cls = "thumb") {
  const src = safeUrl(url);
  return src
    ? `<img class="${cls}" src="${esc(src)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : `<div class="${cls}">🛒</div>`;
}

function scorePill(score, color) {
  return score == null
    ? '<div class="pill na">?<small>no data</small></div>'
    : `<div class="pill" style="background:${esc(color)}">${score}<small>/100</small></div>`;
}

function productRow(p, extra = "") {
  const meta = [p.brands?.join(", "), p.quantity].filter(Boolean).join(" · ");
  return `<a class="row" href="#/p/${encodeURIComponent(p.barcode)}">
    ${thumb(p.image_url)}
    <div class="info"><div class="name">${esc(p.name)}</div>
      <div class="meta">${esc(meta) || "&nbsp;"}</div>${extra}</div>
    ${scorePill(p.score, p.color)}
  </a>`;
}

function topbar(title, { back = true, right = "" } = {}) {
  return `<div class="topbar">
    ${back ? `<button class="icon-btn" data-back aria-label="Back">${icons.back}</button>` : ""}
    <h1>${title}</h1>${right}
  </div>`;
}

function wireBack() {
  app.querySelectorAll("[data-back]").forEach((b) => b.addEventListener("click", goBack));
}

function searchForm(value = "") {
  return `<form class="searchbar" data-search role="search">
    <input type="search" name="q" value="${esc(value)}" placeholder="Search a product or type a barcode"
           autocomplete="off" enterkeyhint="search" aria-label="Search products">
    <button type="submit">Search</button>
  </form>`;
}

function wireSearch() {
  const form = app.querySelector("[data-search]");
  form?.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = form.q.value.trim();
    if (!q) return;
    const digits = q.replace(/[\s-]/g, "");
    if (/^\d{8,14}$/.test(digits)) go(`#/p/${digits}`);
    else if (q.length >= 2) go(`#/search/${encodeURIComponent(q)}`);
    form.q.blur();
  });
}

function errorBox(emoji, title, message, actions = "") {
  return `<div class="card error-box"><div class="big">${emoji}</div>
    <h2 style="justify-content:center">${esc(title)}</h2><p>${esc(message)}</p>
    <div class="actions">${actions}</div></div>`;
}

// ---------------------------------------------------------------- install prompt

let deferredInstall = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredInstall = e;
  if (currentRoute().name === "home") render();
});
window.addEventListener("appinstalled", () => { deferredInstall = null; });

const isStandalone = () =>
  matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent)
  || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

function installBanner() {
  if (isStandalone()) return "";
  try { if (localStorage.getItem(INSTALL_DISMISSED_KEY)) return ""; } catch { /* ignore */ }
  if (deferredInstall) {
    return `<div class="install"><span>📲 Install food-lens on your home screen</span>
      <button data-install>Install</button><button class="x" data-install-x aria-label="Dismiss">✕</button></div>`;
  }
  if (isIOS()) {
    return `<div class="install"><span>📲 To install: tap <b>Share</b> <span aria-hidden="true">⎙</span> then <b>Add to Home Screen</b></span>
      <button class="x" data-install-x aria-label="Dismiss">✕</button></div>`;
  }
  return "";
}

function wireInstall() {
  app.querySelector("[data-install]")?.addEventListener("click", async () => {
    if (!deferredInstall) return;
    deferredInstall.prompt();
    await deferredInstall.userChoice.catch(() => null);
    deferredInstall = null;
    render();
  });
  app.querySelector("[data-install-x]")?.addEventListener("click", () => {
    try { localStorage.setItem(INSTALL_DISMISSED_KEY, "1"); } catch { /* ignore */ }
    render();
  });
}

// ---------------------------------------------------------------- views

function viewHome() {
  const recent = getHistory();
  app.innerHTML = `
    <section class="hero">
      <div class="brand"><img src="/icons/icon-192.png" alt=""><h1>food-lens</h1></div>
      <p class="tagline">Barcode in, health score out — with the receipts.</p>
      <button class="scan-cta" data-scan>
        ${icons.scan}<div><strong>Scan a barcode</strong><span>Point your camera at any packaged food</span></div>
      </button>
      ${searchForm()}
      <div class="chips" aria-label="Try an example">
        <button class="chip" data-q="3017620422003">🍫 Nutella</button>
        <button class="chip" data-q="5449000000996">🥤 Coca-Cola</button>
        <button class="chip" data-s="greek yogurt">Greek yogurt</button>
        <button class="chip" data-s="oat milk">Oat milk</button>
        <button class="chip" data-s="peanut butter">Peanut butter</button>
      </div>
      ${installBanner()}
    </section>
    ${recent.length ? `
      <div class="section-title">Recent <button data-clear>Clear</button></div>
      <div class="list">${recent.map((p) => productRow(p)).join("")}</div>` : ""}
    <p class="foot">Data: Open Food Facts · Scoring: fixed rules, no LLM near the math</p>`;

  app.querySelector("[data-scan]").addEventListener("click", () => go("#/scan"));
  app.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => go(`#/p/${b.dataset.q}`)));
  app.querySelectorAll("[data-s]").forEach((b) => b.addEventListener("click", () =>
    go(`#/search/${encodeURIComponent(b.dataset.s)}`)));
  app.querySelector("[data-clear]")?.addEventListener("click", () => { clearHistory(); render(); });
  wireSearch();
  wireInstall();
}

function viewScan() {
  app.innerHTML = `
    <div class="scanner">
      <video autoplay playsinline muted></video>
      <div class="shade"><div class="reticle"></div></div>
      <div class="scan-top">
        <button class="icon-btn" data-close aria-label="Close scanner">${icons.close}</button>
        <button class="icon-btn" data-torch aria-label="Toggle flashlight" hidden>${icons.torch}</button>
      </div>
      <div class="scan-status">Opening camera…</div>
      <div class="scan-bottom">
        <form data-manual>
          <input name="code" inputmode="numeric" pattern="[0-9 ]*" placeholder="…or type the digits"
                 autocomplete="off" enterkeyhint="go" aria-label="Barcode digits">
          <button type="submit">Go</button>
        </form>
      </div>
    </div>`;

  const video = app.querySelector("video");
  const status = app.querySelector(".scan-status");
  const torchBtn = app.querySelector("[data-torch]");
  let scanner = null;
  let alive = true;

  app.querySelector("[data-close]").addEventListener("click", goBack);
  app.querySelector("[data-manual]").addEventListener("submit", (e) => {
    e.preventDefault();
    const code = e.target.code.value.replace(/\D/g, "");
    if (code.length < 8) { status.textContent = "Barcodes have 8–14 digits."; return; }
    go(`#/p/${code}`, true);
  });

  startScanner(video, {
    onStatus: (msg) => { if (alive) status.textContent = msg; },
    onCode: (code) => {
      app.querySelector(".reticle")?.classList.add("hit");
      status.textContent = `Found ${code}`;
      // replace, so Back from the result returns home instead of reopening the camera
      setTimeout(() => go(`#/p/${code}`, true), 150);
    },
  }).then((s) => {
    scanner = s;
    if (!alive) { s.stop(); return; }
    if (s.torch) {
      torchBtn.hidden = false;
      torchBtn.addEventListener("click", async () => {
        try { torchBtn.classList.toggle("on", await s.torch()); } catch { torchBtn.hidden = true; }
      });
    }
  }).catch((err) => {
    if (!alive) return;
    app.querySelector(".shade").innerHTML =
      `<div class="scan-msg"><div><div style="font-size:2.4rem">📷</div><p>${esc(err.message)}</p></div></div>`;
    status.textContent = "";
  });

  cleanup = () => { alive = false; scanner?.stop(); };
}

async function viewSearch(query) {
  app.innerHTML = `
    ${topbar("Search")}
    ${searchForm(query)}
    <div class="section-title" data-summary>Searching “${esc(query)}”…</div>
    <div class="list" data-results>${skeletonRows(5)}</div>
    <div data-more></div>`;
  wireBack();
  wireSearch();

  const list = app.querySelector("[data-results]");
  const summary = app.querySelector("[data-summary]");
  const moreBox = app.querySelector("[data-more]");
  let page = 1;
  let token = {};
  cleanup = () => { token = null; };

  const load = async (first) => {
    const mine = token;
    try {
      const data = await api(`/api/search?q=${encodeURIComponent(query)}&page=${page}`);
      if (mine !== token) return;
      if (first) list.innerHTML = "";
      if (first && !data.results.length) {
        summary.textContent = "No matches";
        list.innerHTML = errorBox("🔎", "Nothing found",
          "Try a simpler term (brand or product type), or scan the barcode instead.",
          `<a class="btn" href="#/scan">Scan barcode</a>`);
        return;
      }
      summary.textContent = `Results for “${query}”`;
      list.insertAdjacentHTML("beforeend", data.results.map((p) => productRow(p)).join(""));
      moreBox.innerHTML = data.page < data.page_count ? '<button class="more">Load more</button>' : "";
      moreBox.querySelector(".more")?.addEventListener("click", (e) => {
        e.target.disabled = true;
        e.target.textContent = "Loading…";
        page += 1;
        load(false);
      });
    } catch (err) {
      if (mine !== token) return;
      summary.textContent = "";
      if (first) list.innerHTML = errorBox("⚠️", "Search failed", err.message,
        `<button class="btn" data-retry>Try again</button>`);
      else moreBox.innerHTML = `<p class="foot">${esc(err.message)}</p>`;
      list.querySelector("[data-retry]")?.addEventListener("click", () => render());
    }
  };
  load(true);
}

function skeletonRows(n) {
  return Array.from({ length: n }, () =>
    `<div class="row"><div class="thumb skel"></div><div class="info">
      <div class="skel" style="height:14px;width:70%"></div>
      <div class="skel" style="height:12px;width:40%;margin-top:8px"></div></div>
      <div class="pill skel" style="height:44px"></div></div>`).join("");
}

function ring(score, color) {
  const r = 50, c = 2 * Math.PI * r;
  const pct = score == null ? 0 : score / 100;
  return `<div class="ring" role="img" aria-label="Health score ${score ?? "unknown"} out of 100">
    <svg viewBox="0 0 116 116">
      <circle cx="58" cy="58" r="${r}" fill="none" stroke="var(--surface-2)" stroke-width="12"/>
      <circle cx="58" cy="58" r="${r}" fill="none" stroke="${esc(color)}" stroke-width="12"
        stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c}" data-offset="${c * (1 - pct)}"/>
    </svg>
    <div class="num"><div><b style="color:${esc(color)}">${score ?? "?"}</b><span>${score == null ? "no data" : "/ 100"}</span></div></div>
  </div>`;
}

function risksCard(risks) {
  const body = risks.length
    ? risks.map((r) => `<div class="risk">
        <div class="risk-head">${esc(r.name)}${r.code ? ` <span class="code">${esc(r.code)}</span>` : ""}
          <span class="lvl lvl-${esc(r.level)}">${esc(r.level)}</span></div>
        <p>${esc(r.reason)}</p></div>`).join("")
    : '<p class="clean">✓ No risky additives or ingredients flagged.</p>';
  return `<section class="card"><h2>Risky ingredients ${risks.length ? `<span class="count">${risks.length}</span>` : ""}</h2>${body}</section>`;
}

function whyCard(data) {
  const factors = data.score.factors.map((f) => {
    const cls = f.points < 0 ? "neg" : f.points > 0 ? "pos" : "zero";
    const pts = f.points === 0 ? "—" : (f.points > 0 ? "+" : "") + f.points;
    return `<li><span>${esc(f.label)}<span class="detail">${esc(f.detail)}</span></span>
      <span class="pts ${cls}">${pts}</span></li>`;
  }).join("");
  return `<section class="card why"><h2>Why this score</h2>
    <p>${esc(data.explanation)}</p>
    <div class="src">${data.explainer === "llm" ? "Written by an LLM from the breakdown below" : "Generated from the breakdown below"}</div>
    ${data.score.score != null ? `<ul class="factors"><li><span><b>Starting score</b></span><span class="pts">100</span></li>${factors}</ul>` : ""}
  </section>`;
}

function nutrientsCard(rows, isDrink) {
  if (!rows.length) return "";
  const levelText = { low: "low", moderate: "moderate", high: "high", good: "good" };
  return `<section class="card"><h2>Nutrition <span class="count">per 100${isDrink ? "ml" : "g"}</span></h2>
    <table class="nutr">${rows.map((n) => `<tr>
      <td><span class="dot ${n.level ? `dot-${esc(n.level)}` : ""}" title="${esc(levelText[n.level] || "")}"></span>${esc(n.label)}</td>
      <td>${esc(n.value)} ${esc(n.unit)}${n.level ? ` <span class="code" style="color:var(--muted);font-size:.8rem">· ${esc(levelText[n.level])}</span>` : ""}</td>
    </tr>`).join("")}</table></section>`;
}

async function viewProduct(barcode) {
  app.innerHTML = `${topbar("Result")}
    <div class="card"><div class="prod-head"><div class="thumb skel"></div><div style="flex:1">
      <div class="skel" style="height:18px;width:80%"></div>
      <div class="skel" style="height:13px;width:50%;margin-top:10px"></div></div></div>
      <div class="score-wrap"><div class="ring skel" style="border-radius:50%"></div>
      <div style="flex:1"><div class="skel" style="height:20px;width:70%"></div></div></div></div>
    <div class="card"><div class="skel" style="height:80px"></div></div>`;
  wireBack();

  let alive = true;
  cleanup = () => { alive = false; };

  let data;
  try {
    data = await api(`/api/product/${encodeURIComponent(barcode)}`);
  } catch (err) {
    if (!alive) return;
    const notFound = err.status === 404;
    app.innerHTML = `${topbar("Result")}` + errorBox(
      notFound ? "🤷" : "⚠️",
      notFound ? "Product not found" : "Something went wrong",
      err.message,
      `<a class="btn" href="#/scan">Scan again</a><a class="btn ghost" href="#/">Search by name</a>
       ${notFound ? "" : '<button class="btn ghost" data-retry>Retry</button>'}`);
    wireBack();
    app.querySelector("[data-retry]")?.addEventListener("click", () => render());
    return;
  }
  if (!alive) return;

  const { product: p, score: s } = data;
  addHistory({ barcode: p.barcode, name: p.name, brands: p.brands, quantity: p.quantity,
               image_url: p.image_small_url, score: s.score, color: s.color });

  const meta = [p.brands.join(", "), p.quantity].filter(Boolean).join(" · ");
  const isDrink = (p.categories || []).includes("en:beverages");
  const badges = [
    p.nutriscore_grade ? `<span class="badge ns ns-${esc(p.nutriscore_grade)}">Nutri-Score ${esc(p.nutriscore_grade)}</span>` : "",
    p.nova_group ? `<span class="badge">NOVA ${esc(p.nova_group)}</span>` : "",
    data.risks.length ? `<span class="badge">${data.risks.length} flagged</span>` : "",
  ].join("");
  const notice = s.confidence === "low"
    ? `<div class="notice">⚠️ Some nutrition data is missing, so this score may be optimistic.</div>`
    : s.confidence === "none"
      ? `<div class="notice">⚠️ Open Food Facts has no sugar, fat or salt data for this product, so it can't be scored.</div>`
      : "";

  app.innerHTML = `
    ${topbar("Result", { right: `<button class="icon-btn" data-rescan aria-label="Scan another">${icons.scanSmall}</button>` })}
    <section class="card">
      <div class="prod-head">${thumb(p.image_url)}
        <div><div class="name">${esc(p.name)}</div>
          <div class="meta">${esc(meta)}</div>
          <div class="meta">Barcode ${esc(p.barcode)}</div></div>
      </div>
      <div class="score-wrap">${ring(s.score, s.color)}
        <div class="verdict"><div class="band" style="color:${esc(s.color)}">${esc(s.band)}</div>
          <div class="badges">${badges}</div></div>
      </div>
      ${notice}
    </section>
    ${risksCard(data.risks)}
    ${whyCard(data)}
    <section class="card" data-alts><h2>Healthier alternatives</h2>${skeletonRows(3)}</section>
    ${nutrientsCard(data.nutrients, isDrink)}
    ${p.ingredients_text ? `<details class="card"><summary>Ingredients</summary><p>${esc(p.ingredients_text)}</p>
      ${p.allergens?.length ? `<p><b>Allergens:</b> ${esc(p.allergens.join(", "))}</p>` : ""}</details>` : ""}
    <p class="foot"><a href="https://world.openfoodfacts.org/product/${encodeURIComponent(p.barcode)}" target="_blank" rel="noopener">View on Open Food Facts ↗</a></p>`;

  wireBack();
  app.querySelector("[data-rescan]").addEventListener("click", () => go("#/scan"));
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const arc = app.querySelector(".ring circle[data-offset]");
    if (arc) arc.style.strokeDashoffset = arc.dataset.offset;
  }));

  loadAlternatives(p.barcode, s.score, () => alive);
}

async function loadAlternatives(barcode, baseScore, isAlive) {
  const box = app.querySelector("[data-alts]");
  try {
    const data = await api(`/api/alternatives/${encodeURIComponent(barcode)}`);
    if (!isAlive()) return;
    if (!data.alternatives.length) {
      box.innerHTML = `<h2>Healthier alternatives</h2><p class="clean" style="color:var(--muted);font-weight:400">
        ${baseScore != null && baseScore >= 80
          ? "This is already one of the better picks in its category. 👍"
          : "No clearly better option with complete data in this category yet."}</p>`;
      return;
    }
    box.innerHTML = `<h2>Healthier alternatives</h2>
      ${data.category ? `<p class="meta" style="color:var(--muted);font-size:.85rem;margin:-4px 0 10px">Same category: ${esc(data.category)}</p>` : ""}
      <div class="list">${data.alternatives.map((a) => productRow(a,
        baseScore != null ? `<div class="gain">+${a.score - baseScore} points better</div>` : "")).join("")}</div>`;
  } catch (err) {
    if (!isAlive()) return;
    box.innerHTML = `<h2>Healthier alternatives</h2><p class="foot" style="text-align:left">Couldn't load alternatives: ${esc(err.message)}</p>`;
  }
}

// ---------------------------------------------------------------- router

function currentRoute() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [name, ...rest] = hash.split("/");
  const arg = decodeURIComponent(rest.join("/") || "");
  if (name === "scan") return { name: "scan" };
  if (name === "search" && arg) return { name: "search", arg };
  if (name === "p" && arg) return { name: "product", arg: arg.replace(/\D/g, "") };
  return { name: "home" };
}

function render() {
  cleanup?.();
  cleanup = null;
  const route = currentRoute();
  document.body.classList.toggle("scanning", route.name === "scan");
  window.scrollTo(0, 0);
  if (route.name === "scan") viewScan();
  else if (route.name === "search") viewSearch(route.arg);
  else if (route.name === "product") viewProduct(route.arg);
  else viewHome();
}

let depth = history.state?.depth ?? 0;
if (history.state?.depth == null) history.replaceState({ depth }, "");
window.addEventListener("hashchange", () => {
  if (typeof history.state?.depth === "number") {
    depth = history.state.depth; // back/forward onto an entry we've seen
  } else {
    // new entry: a push (go() or a plain <a href="#/...">) goes one deeper,
    // a replace keeps the depth of the entry it replaced
    if (pendingNav !== "replace") depth += 1;
    history.replaceState({ depth }, "");
  }
  pendingNav = null;
  render();
});
render();

// ---------------------------------------------------------------- service worker

if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* offline support is optional */ });
  });
}

export { validGtin }; // handy from the console when debugging scans
