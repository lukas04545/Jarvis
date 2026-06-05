/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S. terminal — client controller
   ═══════════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const REFRESH_MS = 90_000;
  let activeTopic = "";
  let lastNews = [];

  // ── helpers ──────────────────────────────────────────────────────────
  const esc = (s) =>
    String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  async function getJSON(url, opts) {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
    return r.json();
  }

  const simState = { news: false, surv: false };

  function setNet(ok) {
    if (!ok) {
      const el = $("net-indicator");
      el.textContent = "● DEGRADED";
      el.classList.add("stale");
    }
  }

  function updateNet() {
    const el = $("net-indicator");
    const simulated = simState.news || simState.surv;
    el.textContent = simulated ? "● SIMULATED FEED" : "● LIVE";
    el.classList.toggle("stale", simulated);
  }

  // ── clock ────────────────────────────────────────────────────────────
  function tickClock() {
    $("clock").textContent = new Date().toISOString().slice(11, 19);
  }
  setInterval(tickClock, 1000);
  tickClock();

  // ── status ───────────────────────────────────────────────────────────
  async function loadStatus() {
    try {
      const s = await getJSON("/api/status");
      const el = $("ai-status");
      el.textContent = s.ai_core;
      el.className = "pill " + (s.ai_core === "ONLINE" ? "online" : "offline");
      $("console-meta").textContent = s.model || "offline";
    } catch (e) {
      /* non-fatal */
    }
  }

  // ── news ─────────────────────────────────────────────────────────────
  function renderNews() {
    const list = $("news-list");
    const items = activeTopic
      ? lastNews.filter((i) => i.topic === activeTopic)
      : lastNews;
    if (!items.length) {
      list.innerHTML = `<div class="loading">NO ITEMS</div>`;
      return;
    }
    list.innerHTML = items
      .map(
        (it) => `
      <a class="news-item" href="${esc(it.link)}" target="_blank" rel="noopener">
        <div class="news-row">
          <span class="news-time">${esc(it.time)}</span>
          <span class="news-topic t-${esc(it.topic)}">${esc(it.topic)}</span>
          <span class="news-title">${esc(it.title)}</span>
        </div>
        <div class="news-src">${esc(it.source)} · ${esc(it.region)}</div>
      </a>`
      )
      .join("");
  }

  function renderTicker() {
    const top = lastNews.slice(0, 24);
    $("ticker-text").innerHTML =
      top.map((i) => `${esc(i.title)}`).join('<span class="sep">◆</span>') ||
      "No wire traffic.";
  }

  async function loadNews() {
    try {
      const n = await getJSON("/api/news");
      lastNews = n.items || [];
      const ageTxt = n.age != null ? `${Math.round(n.age)}s ago` : "live";
      const sim = n.simulated ? " · SIM" : "";
      $("news-meta").textContent = `${n.count} items · ${ageTxt}${sim}`;
      simState.news = !!n.simulated;
      updateNet();
      renderNews();
      renderTicker();
    } catch (e) {
      setNet(false);
    }
  }

  // ── surveillance ─────────────────────────────────────────────────────
  function renderSurv(s) {
    const seismic = s.seismic || {};
    const orbital = s.orbital || {};
    const solar = s.solar || {};

    const quakeRows = (seismic.events || [])
      .map(
        (q) => `
      <div class="quake">
        <span class="quake-mag m-${esc(q.level)}">M${esc(q.mag)}</span>
        <span class="quake-place">${esc(q.place)}</span>
        <span class="news-time">${esc(q.time)}</span>
      </div>`
      )
      .join("") || `<div class="kv"><span>no events &gt;M2.5 / 24h</span></div>`;

    const solarRows = (solar.alerts || [])
      .map((a) => `<div class="alert-line">${esc(a.summary)}</div>`)
      .join("") || `<div class="kv"><span>no active alerts</span></div>`;

    const statusTag = (o) =>
      `<span class="surv-status s-${esc(o.status || "DEGRADED")}">${esc(
        o.status || "DEGRADED"
      )}</span>`;

    $("surv-body").innerHTML = `
      <div class="surv-section">
        <div class="surv-title"><span>◢ SEISMIC // USGS</span>${statusTag(seismic)}</div>
        ${quakeRows}
      </div>
      <div class="surv-section">
        <div class="surv-title"><span>◢ ORBITAL // ISS</span>${statusTag(orbital)}</div>
        <div class="kv"><span>LAT / LON</span><b>${esc(orbital.lat ?? "--")}, ${esc(orbital.lon ?? "--")}</b></div>
        <div class="kv"><span>ALTITUDE</span><b>${esc(orbital.alt_km ?? "--")} km</b></div>
        <div class="kv"><span>VELOCITY</span><b>${esc(orbital.velocity_kmh ?? "--")} km/h</b></div>
        <div class="kv"><span>VISIBILITY</span><b>${esc(orbital.visibility ?? "--")}</b></div>
      </div>
      <div class="surv-section">
        <div class="surv-title"><span>◢ SPACE WX // NOAA</span>${statusTag(solar)}</div>
        ${solarRows}
      </div>`;
  }

  async function loadSurv() {
    try {
      const s = await getJSON("/api/surveillance");
      const p = $("posture");
      p.textContent = s.posture;
      p.className = "pill " + s.posture;
      $("sensors").textContent = `${s.sensors_online}/${s.sensors_total}`;
      const ageTxt = s.age != null ? `${Math.round(s.age)}s` : "live";
      const sim = s.simulated ? " · SIM" : "";
      $("surv-meta").textContent = `posture ${s.posture} · ${ageTxt}${sim}`;
      simState.surv = !!s.simulated;
      updateNet();
      renderSurv(s);
    } catch (e) {
      setNet(false);
    }
  }

  // ── console ──────────────────────────────────────────────────────────
  const log = $("console-log");

  function addLine(cls, text) {
    const div = document.createElement("div");
    div.className = "line " + cls;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function bootConsole() {
    addLine("sys", "J.A.R.V.I.S. core initialised. Global feeds linked.");
    addLine("jarvis", "Good day, Operator. I'm monitoring the wire and the sensor grid. Ask me anything, or type HELP.");
  }

  const HELP = [
    "COMMAND REFERENCE",
    "  HELP            this reference",
    "  NEWS            refresh the World Wire",
    "  SURV            refresh the surveillance grid",
    "  BRIEF           generate an AI situational briefing",
    "  REFRESH         reload all feeds",
    "  CLEAR           clear this console",
    "  <anything else> talk to J.A.R.V.I.S. (DeepSeek)",
  ].join("\n");

  async function doBrief() {
    const line = addLine("jarvis", "");
    line.innerHTML = '<span class="cursor">▌</span> synthesising briefing…';
    try {
      const b = await getJSON("/api/briefing");
      line.textContent = b.briefing;
      line.className = "line jarvis";
    } catch (e) {
      line.className = "line err";
      line.textContent = "Briefing failed: " + e.message;
    }
  }

  async function streamChat(message) {
    const line = addLine("jarvis", "");
    const cursor = '<span class="cursor">▌</span>';
    line.innerHTML = cursor;
    let buf = "";
    try {
      const r = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, with_context: true }),
      });
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let sse = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        sse += dec.decode(value, { stream: true });
        const parts = sse.split("\n\n");
        sse = parts.pop();
        for (const p of parts) {
          const m = p.match(/^data: (.*)$/m);
          if (!m) continue;
          if (m[1] === "[DONE]") continue;
          let payload;
          try { payload = JSON.parse(m[1]); } catch { continue; }
          if (payload.error) {
            line.className = "line err";
            line.textContent = "ERROR: " + payload.error;
            return;
          }
          if (payload.delta) {
            buf += payload.delta;
            line.innerHTML = esc(buf) + cursor;
            log.scrollTop = log.scrollHeight;
          }
        }
      }
      line.textContent = buf || "(no response)";
    } catch (e) {
      line.className = "line err";
      line.textContent = "Link error: " + e.message;
    }
  }

  async function handleInput(raw) {
    const text = raw.trim();
    if (!text) return;
    const cmd = text.toUpperCase();

    if (cmd === "CLEAR") { log.innerHTML = ""; return; }
    addLine("opr", text);

    switch (cmd) {
      case "HELP": addLine("sys", HELP); return;
      case "NEWS": addLine("sys", "Refreshing World Wire…"); return loadNews();
      case "SURV": addLine("sys", "Refreshing surveillance grid…"); return loadSurv();
      case "REFRESH": addLine("sys", "Reloading all feeds…"); refreshAll(); return;
      case "BRIEF": return doBrief();
      default: return streamChat(text);
    }
  }

  // ── wiring ───────────────────────────────────────────────────────────
  $("cmd").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const v = e.target.value;
      e.target.value = "";
      handleInput(v);
    }
  });

  $("news-filters").addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    document.querySelectorAll("#news-filters .chip").forEach((c) =>
      c.classList.remove("active"));
    btn.classList.add("active");
    activeTopic = btn.dataset.topic;
    renderNews();
  });

  $("fnbar").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (btn) handleInput(btn.dataset.cmd);
  });

  // Function keys F1–F6
  const FN = { F1: "HELP", F2: "NEWS", F3: "SURV", F4: "BRIEF", F5: "REFRESH", F6: "CLEAR" };
  document.addEventListener("keydown", (e) => {
    if (FN[e.key]) { e.preventDefault(); handleInput(FN[e.key]); }
  });

  // ── boot ─────────────────────────────────────────────────────────────
  function refreshAll() {
    loadStatus();
    loadNews();
    loadSurv();
  }

  bootConsole();
  refreshAll();
  setInterval(refreshAll, REFRESH_MS);

  // PWA home-screen shortcuts deep-link in via ?cmd=BRIEF|NEWS|SURV.
  const wanted = new URLSearchParams(location.search).get("cmd");
  if (wanted) setTimeout(() => handleInput(wanted), 600);

  // Android "Add to Home screen" — surface a one-tap install button when the
  // browser offers it, instead of burying it in the menu.
  let deferredPrompt = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    const btn = $("install-btn");
    if (!btn) return;
    btn.hidden = false;
    btn.addEventListener("click", async () => {
      btn.hidden = true;
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
    });
  });

  // Don't steal focus / pop the keyboard on touch devices.
  if (!window.matchMedia("(pointer: coarse)").matches) $("cmd").focus();
})();
