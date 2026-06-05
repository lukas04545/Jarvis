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
    "  FORECAST        run the ORACLE — predict future events",
    "  AGENTS <task>   deploy the multi-agent mesh on a tasking",
    "  DEVICE          local device sensors (memory/screen/voice input)",
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
      case "FORECAST": case "ORACLE": case "PREDICT":
        addLine("sys", "Engaging ORACLE — switching to forecast view…");
        showView("forecast");
        setTimeout(runForecast, 200); return;
      case "DEVICE": case "SENSORS":
        addLine("sys", "Opening local device sensors…");
        showView("device"); return;
      default:
        // AGENTS <task> / TASKFORCE <task> → deploy the multi-agent mesh.
        if (cmd === "AGENTS" || cmd === "TASKFORCE" ||
            cmd.startsWith("AGENTS ") || cmd.startsWith("TASKFORCE ")) {
          const task = text.replace(/^\s*\S+\s*/, "").trim();
          addLine("sys", task ? "Deploying agent mesh…" : "Opening agent mesh — enter a tasking.");
          showView("agents");
          if (task) { $("agent-query").value = task; setTimeout(() => runAgents(task), 200); }
          return;
        }
        return streamChat(text);
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

  // Function keys F1–F6 (ignore while typing in a field)
  const FN = { F1: "HELP", F2: "NEWS", F3: "SURV", F4: "BRIEF", F5: "REFRESH", F6: "CLEAR" };
  document.addEventListener("keydown", (e) => {
    if (FN[e.key] && e.target.tagName !== "INPUT") { e.preventDefault(); handleInput(FN[e.key]); }
  });

  // ── tabs (TERMINAL / GLOBE / FORECAST) ────────────────────────────────
  let globeReady = false;
  let forecastReady = false;
  function showView(name) {
    document.querySelectorAll(".view").forEach((v) =>
      v.classList.toggle("active", v.id === "view-" + name));
    document.querySelectorAll(".tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.view === name));
    if (name === "globe") {
      if (!globeReady) {
        JarvisGlobe.init("globe", onGlobeSelect);
        globeReady = true;
        loadSatellite();
        loadWebcams();
      }
      JarvisGlobe.show();
    } else {
      JarvisGlobe.hide();
    }
    if (name === "forecast" && !forecastReady) {
      forecastReady = true;
      loadSignals();
    }
    if (name === "agents" && !window.matchMedia("(pointer: coarse)").matches) {
      setTimeout(() => $("agent-query").focus(), 50);
    }
    if (name === "device" && window.JarvisDevice) JarvisDevice.init();
  }
  $("tabs").addEventListener("click", (e) => {
    const t = e.target.closest(".tab");
    if (t) showView(t.dataset.view);
  });

  $("globe-layers").addEventListener("change", (e) => {
    const cb = e.target.closest("input[data-layer]");
    if (cb) JarvisGlobe.setLayer(cb.dataset.layer, cb.checked);
  });

  // ── globe marker selection → intel detail / webcam viewer ─────────────
  function onGlobeSelect(marker, webcam) {
    const detail = $("globe-detail");
    const d = marker.data || {};
    if (marker.type === "webcam") {
      openWebcam(webcam || d);
      detail.innerHTML =
        `<b class="t-TECH">◉ WEBCAM</b><br>${esc(d.title || "")}<br>` +
        `<span class="news-src">${esc(d.city || "")} ${esc(d.country || "")}</span>`;
      return;
    }
    const rows = {
      seismic: `<b class="m-${esc(d.level)}">SEISMIC · M${esc(d.mag)}</b><br>${esc(d.place || "")}` +
               `<br><span class="news-src">${esc(d.time || "")} · depth ${esc(d.depth)}km · ${esc(d.level)}</span>`,
      orbital: `<b class="t-POLITICS">ORBITAL · ISS</b><br>alt ${esc(d.alt_km)}km · ${esc(d.velocity_kmh)} km/h` +
               `<br><span class="news-src">lat ${esc(d.lat)}, lon ${esc(d.lon)} · ${esc(d.visibility || "")}</span>`,
      satellite: `<b style="color:#ff5a1b">SAT EVENT · ${esc(d.tag)}</b><br>${esc(d.title || "")}` +
                 `<br><span class="news-src">${esc(d.category || "")} · NASA EONET</span>` +
                 (d.link ? `<br><a class="news-item" style="padding:0" href="${esc(d.link)}" target="_blank" rel="noopener">source ↗</a>` : ""),
      news: `<b class="t-DISASTER">NEWS CLUSTER</b><br>${esc(d.region)} — ${esc(d.count)} items` +
            `<br><span class="news-src">switch to TERMINAL for the wire</span>`,
    };
    detail.innerHTML = rows[marker.type] || esc(marker.label || "");
  }

  // ── live satellite rail ───────────────────────────────────────────────
  async function loadSatellite() {
    const box = $("sat-box");
    try {
      const s = await getJSON("/api/satellite");
      const ev = s.events || {};
      const img = s.earth_image || {};
      const cat = s.catalog || {};
      $("sat-meta").textContent =
        (s.simulated ? "SIM · " : "") + `${s.sources_online}/3 online`;
      const events = (ev.events || []).slice(0, 8).map((e) =>
        `<div class="sat-row"><span class="sat-tag">${esc(e.tag)}</span>` +
        `<span class="sat-title">${esc(e.title)}</span></div>`).join("");
      const earth = img.image
        ? `<img class="epic-img" src="${esc(img.image)}" alt="EPIC Earth" loading="lazy" />
           <div class="news-src">DSCOVR/EPIC · ${esc((img.date || "").slice(0, 16))}</div>`
        : `<div class="news-src">${esc(img.caption || "EPIC image unavailable")}</div>`;
      box.innerHTML =
        `<div class="kv"><span>ACTIVE SATELLITES</span><b>${esc(cat.active_satellites ?? "--")}</b></div>` +
        `<div class="kv"><span>EONET EVENTS</span><b>${esc(ev.count ?? 0)}</b></div>` +
        `<div class="sat-events">${events || '<div class="news-src">no open events</div>'}</div>` +
        `<div class="epic-wrap">${earth}</div>`;
    } catch (e) {
      box.innerHTML = `<div class="err">satellite link failed: ${esc(e.message)}</div>`;
    }
  }

  // ── public webcams (directory + viewer) ───────────────────────────────
  let webcamTimer = null;
  function closeWebcam() {
    if (webcamTimer) { clearInterval(webcamTimer); webcamTimer = null; }
    const v = $("webcam-viewer");
    v.hidden = true; v.innerHTML = "";
  }
  function openWebcam(cam) {
    const v = $("webcam-viewer");
    if (webcamTimer) { clearInterval(webcamTimer); webcamTimer = null; }
    v.hidden = false;
    const head = `<div class="wc-head">◉ ${esc(cam.title)} <button class="wc-close">✕</button></div>`;
    if (cam.image) {
      // Public refreshing JPEG (e.g. TfL traffic cam). Poll with a cache-buster.
      const bust = () => esc(cam.image) + (cam.image.includes("?") ? "&" : "?") + "_t=" + Date.now();
      v.innerHTML = head +
        `<img class="wc-frame" id="wc-img" src="${bust()}" alt="${esc(cam.title)}" />` +
        `<div class="news-src">${esc(cam.city || "")} ${esc(cam.country || "")} · live public feed, refreshing…` +
        (cam.video ? ` · <a href="${esc(cam.video)}" target="_blank" rel="noopener">video ↗</a>` : "") + `</div>`;
      webcamTimer = setInterval(() => {
        const img = document.getElementById("wc-img");
        if (img) img.src = bust(); else closeWebcam();
      }, 5000);
    } else {
      v.innerHTML = head +
        `<div class="wc-link">This is a publicly-published webcam. Open the live source:<br>` +
        `<a href="${esc(cam.link || "#")}" target="_blank" rel="noopener">${esc(cam.link || "source")} ↗</a></div>`;
    }
    v.querySelector(".wc-close").addEventListener("click", closeWebcam);
  }

  let webcamList = [];
  async function loadWebcams() {
    const list = $("webcam-list");
    try {
      const w = await getJSON("/api/webcams");
      webcamList = w.webcams || [];
      $("webcam-meta").textContent =
        (w.live ? "LIVE" : "SAMPLE") + ` · ${w.count}`;
      const note = w.note ? `<div class="wc-note">${esc(w.note)}</div>` : "";
      list.innerHTML = note + webcamList.map((c, i) =>
        `<div class="wc-item" data-i="${i}">` +
        `<span class="wc-dot">◉</span>` +
        `<span class="wc-name">${esc(c.title)}</span>` +
        `<span class="news-src">${esc(c.country || "")}</span></div>`).join("");
    } catch (e) {
      list.innerHTML = `<div class="err">webcam directory failed: ${esc(e.message)}</div>`;
    }
  }
  $("webcam-list").addEventListener("click", (e) => {
    const it = e.target.closest(".wc-item");
    if (!it) return;
    const cam = webcamList[+it.dataset.i];
    if (cam) { openWebcam(cam); JarvisGlobe.select("w-" + cam.id); }
  });

  // ── ORACLE: signals dashboard + forecast ──────────────────────────────
  const DOMAIN_COLORS = {
    CONFLICT: "var(--red)", MARKETS: "var(--green)", POLITICS: "var(--cyan)",
    DISASTER: "var(--amber)", CYBER: "#ff5db1", TECH: "var(--magenta)",
    SPACE: "#9d7bff", HEALTH: "#7ad6c0",
  };
  function momentumPct(z) { return Math.max(4, Math.min(100, 50 + z * 16)); }

  function renderSignals(sig) {
    $("signals-meta").textContent =
      (sig.simulated ? "SIM · " : "") + `${sig.samples_in_baseline} baseline samples`;

    // Domain momentum bars
    const dom = Object.entries(sig.domains || {})
      .sort((a, b) => (b[1].momentum - a[1].momentum) || (b[1].volume - a[1].volume));
    $("signal-domains").innerHTML = dom.map(([d, v]) => {
      const col = DOMAIN_COLORS[d] || "var(--text-dim)";
      return `<div class="sig-row">
        <span class="sig-name" style="color:${col}">${esc(d)}</span>
        <div class="sig-bar"><div class="sig-fill" style="width:${momentumPct(v.momentum)}%;background:${col}"></div></div>
        <span class="sig-val">${v.volume} · ${v.level}</span></div>`;
    }).join("") || '<div class="news-src">no signal</div>';

    // Anomalies
    $("signal-anomalies").innerHTML = (sig.anomalies || []).length
      ? sig.anomalies.map((a) => `<div class="anom">▲ ${esc(a)}</div>`).join("")
      : '<div class="news-src">no anomalies detected</div>';

    // Markets
    const mk = sig.markets || {};
    $("markets-meta").textContent = mk.sentiment || "--";
    $("signal-markets").innerHTML =
      `<div class="kv"><span>SENTIMENT</span><b class="${mk.sentiment === 'RISK-OFF' ? 'm-CRITICAL' : 'm-NOMINAL'}">${esc(mk.sentiment || '--')}</b></div>` +
      `<div class="kv"><span>RISK INDEX</span><b>${esc(mk.risk_index ?? '--')}</b></div>` +
      (mk.movers || []).map((m) => {
        const cls = m.chg >= 0 ? "up" : "down";
        return `<div class="mover"><span>${esc(m.symbol)}</span>` +
               `<span class="${cls}">${m.chg >= 0 ? "+" : ""}${esc(m.chg)}%</span></div>`;
      }).join("");

    // GDELT
    $("signal-gdelt").innerHTML = Object.entries(sig.gdelt || {}).map(([k, t]) => {
      if (t.error) return `<div class="news-src">${esc(k)}: offline</div>`;
      const toneCls = t.tone < -3 ? "down" : (t.tone > 1 ? "up" : "");
      return `<div class="mover"><span>${esc(k)}</span>` +
             `<span>vol ${t.trend_pct >= 0 ? "+" : ""}${esc(t.trend_pct)}% · ` +
             `<b class="${toneCls}">tone ${esc(t.tone)}</b></span></div>`;
    }).join("") || '<div class="news-src">no data</div>';
  }

  async function loadSignals() {
    try {
      const sig = await getJSON("/api/signals");
      renderSignals(sig);
    } catch (e) {
      $("signal-domains").innerHTML = `<div class="err">signals failed: ${esc(e.message)}</div>`;
    }
  }

  function probBucket(p) { return p >= 0.66 ? "high" : (p >= 0.4 ? "med" : "low"); }

  function renderPredictions(fc) {
    const banner = $("forecast-banner");
    const method = fc.method === "ai+heuristic"
      ? "AI (DeepSeek) + heuristic baseline"
      : "heuristic baseline (paste a DeepSeek key in SETTINGS for AI forecasts)";
    banner.innerHTML =
      `<span>${fc.simulated ? "⚠ SIMULATED SIGNALS · " : ""}method: ${esc(method)}</span>` +
      (fc.ai_error ? `<span class="err"> · AI: ${esc(fc.ai_error)}</span>` : "");

    $("forecast-meta").textContent =
      `${fc.predictions.length} predictions · ${new Date(fc.generated).toUTCString().slice(17, 25)}Z`;

    $("predictions").innerHTML = fc.predictions.map((p) => {
      const col = DOMAIN_COLORS[p.domain] || "var(--amber)";
      const pct = Math.round(p.probability * 100);
      const drivers = (p.drivers || []).map((d) => `<li>${esc(d)}</li>`).join("");
      return `<div class="pred ${probBucket(p.probability)}">
        <div class="pred-top">
          <span class="pred-prob">${pct}%</span>
          <div class="pred-meta">
            <span class="pred-domain" style="color:${col}">${esc(p.domain)}</span>
            <span class="pred-tag">${esc(p.region)}</span>
            <span class="pred-tag">⌛ ${esc(p.horizon)}</span>
            <span class="pred-tag">conf ${esc(p.confidence)}</span>
            <span class="pred-tag src-${esc(p.source)}">${esc(p.source)}</span>
          </div>
        </div>
        <div class="pred-bar"><div class="pred-fill" style="width:${pct}%;background:${col}"></div></div>
        <div class="pred-statement">${esc(p.statement)}</div>
        ${drivers ? `<div class="pred-drivers"><b>drivers</b><ul>${drivers}</ul></div>` : ""}
        <div class="pred-cd">
          <span class="confirm">✓ confirm: ${esc(p.confirm || "—")}</span>
          <span class="deny">✕ refute: ${esc(p.deny || "—")}</span>
        </div>
      </div>`;
    }).join("") || '<div class="news-src">no predictions</div>';
  }

  async function runForecast() {
    const btn = $("forecast-run");
    btn.disabled = true;
    $("predictions").innerHTML = '<div class="loading">ORACLE computing — fusing signals & querying DeepSeek…</div>';
    try {
      const fc = await getJSON("/api/forecast");
      renderPredictions(fc);
      renderSignals(fc.signals);   // forecast bundles fresh signals
    } catch (e) {
      $("predictions").innerHTML = `<div class="err">forecast failed: ${esc(e.message)}</div>`;
    } finally {
      btn.disabled = false;
    }
  }
  $("forecast-run").addEventListener("click", runForecast);

  // ── AGENT MESH (multi-agent harness, SSE streamed) ────────────────────
  const AGENT_COLORS = {
    GEOINT: "var(--red)", ECONINT: "var(--green)", GEOPHYS: "var(--amber)",
    CYBER: "#ff5db1", ORACLE: "#9d7bff",
  };
  let agentBusy = false;

  function agentCardHTML(name, role, body, mode) {
    const col = AGENT_COLORS[name] || "var(--cyan)";
    const tag = mode && mode !== "ai"
      ? `<span class="agent-mode ${esc(mode)}">${esc(mode)}</span>` : "";
    return `<div class="agent-card" id="agent-${esc(name)}" style="border-top-color:${col}">
      <div class="agent-name" style="color:${col}">⬡ ${esc(name)} ${tag}
        <span class="agent-role">${esc(role)}</span></div>
      <div class="agent-findings">${body}</div>
    </div>`;
  }

  async function runAgents(query) {
    if (agentBusy) return;
    const q = (query || $("agent-query").value).trim();
    if (!q) return;
    agentBusy = true;
    $("agent-run").disabled = true;
    const synth = $("agent-synthesis");
    synth.hidden = true; synth.innerHTML = "";
    $("agent-plan").innerHTML = "";
    const grid = $("agent-grid");
    grid.innerHTML = '<div class="loading">Routing task to the desk…</div>';

    try {
      const r = await fetch("/api/agents/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q }),
      });
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let sse = "";
      let first = true;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        sse += dec.decode(value, { stream: true });
        const parts = sse.split("\n\n");
        sse = parts.pop();
        for (const p of parts) {
          const m = p.match(/^data: (.*)$/m);
          if (!m || m[1] === "[DONE]") continue;
          let ev; try { ev = JSON.parse(m[1]); } catch { continue; }

          if (ev.type === "plan") {
            if (first) { grid.innerHTML = ""; first = false; }
            $("agent-plan").innerHTML =
              `<span class="plan-label">DISPATCHED:</span> ` +
              ev.plan.map((a) => {
                const col = AGENT_COLORS[a.name] || "var(--cyan)";
                return `<span class="plan-chip" style="color:${col};border-color:${col}" title="${esc(a.role)}">${esc(a.name)}</span>`;
              }).join("") +
              (ev.online ? "" : ` <span class="agent-mode offline">offline — set a DeepSeek key for AI analysis</span>`);
            // Pre-create pending cards in dispatch order.
            grid.innerHTML = ev.plan.map((a) =>
              agentCardHTML(a.name, a.role, '<span class="cursor">▌</span> analysing…', "")).join("");
          } else if (ev.type === "agent") {
            const a = ev.agent;
            const card = $("agent-" + a.name);
            const body = esc(a.findings).replace(/\n/g, "<br>");
            if (card) card.querySelector(".agent-findings").innerHTML = body;
            if (card && a.mode && a.mode !== "ai") {
              const nm = card.querySelector(".agent-name");
              if (nm && !nm.querySelector(".agent-mode"))
                nm.insertAdjacentHTML("beforeend", ` <span class="agent-mode ${esc(a.mode)}">${esc(a.mode)}</span>`);
            }
          } else if (ev.type === "synthesis") {
            synth.hidden = false;
            synth.innerHTML = `<div class="synth-label">◈ DIRECTOR'S FUSED BRIEFING</div>` +
              `<div class="synth-text">${esc(ev.synthesis.text).replace(/\n/g, "<br>")}</div>`;
          } else if (ev.type === "error") {
            grid.innerHTML = `<div class="err">harness error: ${esc(ev.error)}</div>`;
          }
        }
      }
    } catch (e) {
      grid.innerHTML = `<div class="err">agent mesh failed: ${esc(e.message)}</div>`;
    } finally {
      agentBusy = false;
      $("agent-run").disabled = false;
    }
  }
  $("agent-run").addEventListener("click", () => runAgents());
  $("agent-query").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runAgents();
  });

  // ── settings modal (paste API keys) ───────────────────────────────────
  const modal = $("settings-modal");
  function stateLabel(p) {
    if (!p) return "";
    if (p.configured) return p.source === "ui" ? "● set (this session)" : "● set (env)";
    return "○ not set";
  }
  async function openSettings() {
    try {
      const s = await getJSON("/api/settings");
      $("ds-state").textContent = stateLabel(s.deepseek);
      $("ds-state").className = "key-state " + (s.deepseek.configured ? "ok" : "off");
    } catch (e) { /* ignore */ }
    $("ds-key").value = "";
    $("settings-msg").textContent = "";
    modal.hidden = false;
  }
  function closeSettings() { modal.hidden = true; }
  async function saveSettings(clear) {
    // Empty string clears; only send the field if the operator touched it.
    const body = {};
    if (clear || $("ds-key").value) body.deepseek_api_key = clear ? "" : $("ds-key").value;
    $("settings-msg").textContent = "saving…";
    try {
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      $("settings-msg").textContent = clear ? "cleared." : "saved.";
      loadStatus();                       // flip AI CORE pill
      setTimeout(openSettings, 300);      // refresh the state labels
    } catch (e) {
      $("settings-msg").textContent = "save failed";
    }
  }
  $("settings-btn").addEventListener("click", openSettings);
  $("settings-close").addEventListener("click", closeSettings);
  $("settings-save").addEventListener("click", () => saveSettings(false));
  $("settings-clear").addEventListener("click", () => saveSettings(true));
  modal.addEventListener("click", (e) => { if (e.target === modal) closeSettings(); });

  // ── boot ─────────────────────────────────────────────────────────────
  function refreshAll() {
    loadStatus();
    loadNews();
    loadSurv();
    if (globeReady) {
      loadSatellite();
      loadWebcams();
      JarvisGlobe.reload();
    }
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
