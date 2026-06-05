/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S. — Local Device Sensors
   Consent-gated access to the OPERATOR'S OWN device via standard browser APIs:
     • Telemetry  — memory/hardware/screen/network/power (read-only).
     • Screen     — getDisplayMedia screen-share (browser prompt); frames stay
                    local, never uploaded.
     • Input      — Web Speech API mic (voice → JARVIS input) + a local
                    keystroke/pointer activity meter.
   Non-sensitive telemetry is synced to /api/device so the SENTINEL agent can
   read the device posture. Screen frames and audio are NOT sent to the server.
   ═══════════════════════════════════════════════════════════════════════ */
window.JarvisDevice = (() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  let inited = false;
  let screenStream = null;
  let rec = null, recognizing = false, transcript = "";
  const keyTimes = [], ptrTimes = [];
  let lastPtr = 0;
  let tessLoading = null, lastVision = null;

  // Language map drives BOTH speech recognition (BCP-47) and OCR (Tesseract).
  const LANGS = {
    en: { speech: "en-US", ocr: "eng" },
    de: { speech: "de-DE", ocr: "deu" },
    es: { speech: "es-ES", ocr: "spa" },
    fr: { speech: "fr-FR", ocr: "fra" },
  };
  function curLang() {
    const s = $("lang-select");
    return LANGS[(s && s.value) || "en"] || LANGS.en;
  }

  // ── input activity meter (this page only) ─────────────────────────────
  const onKey = () => keyTimes.push(Date.now());
  const onPtr = () => { const t = Date.now(); if (t - lastPtr > 150) { lastPtr = t; ptrTimes.push(t); } };
  function rate(arr) { const cut = Date.now() - 60000; while (arr.length && arr[0] < cut) arr.shift(); return arr.length; }
  function bar(label, val, max, col) {
    const pct = Math.min(100, (val / max) * 100);
    return `<div class="sig-row"><span class="sig-name">${label}</span>` +
      `<div class="sig-bar"><div class="sig-fill" style="width:${pct}%;background:${col}"></div></div>` +
      `<span class="sig-val">${val}/min</span></div>`;
  }
  function renderMeter() {
    const el = $("input-meter"); if (!el) return;
    el.innerHTML = bar("keystrokes", rate(keyTimes), 200, "var(--cyan)") +
                   bar("pointer", rate(ptrTimes), 400, "var(--green)");
  }

  // ── telemetry ─────────────────────────────────────────────────────────
  async function collect() {
    const nav = navigator;
    const memory = { deviceMemoryGB: nav.deviceMemory || null };
    if (window.performance && performance.memory)
      memory.jsHeapMB = Math.round(performance.memory.usedJSHeapSize / 1048576);
    try {
      if (nav.storage && nav.storage.estimate) {
        const e = await nav.storage.estimate();
        memory.storageUsageMB = Math.round((e.usage || 0) / 1048576);
        memory.storageQuotaMB = Math.round((e.quota || 0) / 1048576);
      }
    } catch (e) { /* ignore */ }

    const hardware = {
      cores: nav.hardwareConcurrency || null,
      platform: nav.platform || "",
      ua: (nav.userAgent || "").slice(0, 160),
      languages: Array.from(nav.languages || []),
    };
    const sc = window.screen || {};
    const screen = {
      width: sc.width, height: sc.height, availWidth: sc.availWidth, availHeight: sc.availHeight,
      colorDepth: sc.colorDepth, pixelRatio: window.devicePixelRatio,
      orientation: (sc.orientation && sc.orientation.type) || "",
    };
    const network = { online: nav.onLine };
    const c = nav.connection || nav.webkitConnection;
    if (c) { network.effectiveType = c.effectiveType; network.downlinkMbps = c.downlink; network.rttMs = c.rtt; }
    const power = {};
    try {
      if (nav.getBattery) { const b = await nav.getBattery(); power.batteryLevel = Math.round(b.level * 100) + "%"; power.charging = b.charging; }
    } catch (e) { /* ignore */ }
    const locale = { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone };
    const input = { keysPerMin: rate(keyTimes), pointerPerMin: rate(ptrTimes) };
    const capture = { screenSharing: !!screenStream, micListening: recognizing };
    return { memory, hardware, screen, network, power, locale, input, capture };
  }

  function kv(label, value) {
    return value === undefined || value === null || value === ""
      ? "" : `<div class="kv"><span>${label}</span><b>${esc(value)}</b></div>`;
  }
  function renderTelemetry(t) {
    const el = $("device-telemetry"); if (!el) return;
    const m = t.memory, h = t.hardware, s = t.screen, n = t.network, p = t.power;
    el.innerHTML =
      `<div class="dev-sec">COMPUTE</div>` +
      kv("CPU cores", h.cores) + kv("Platform", h.platform) +
      kv("Device memory", m.deviceMemoryGB ? m.deviceMemoryGB + " GB" : "n/a") +
      kv("JS heap", m.jsHeapMB ? m.jsHeapMB + " MB" : null) +
      kv("Storage", m.storageQuotaMB ? `${m.storageUsageMB} / ${m.storageQuotaMB} MB` : null) +
      `<div class="dev-sec">SCREEN</div>` +
      kv("Resolution", `${s.width}×${s.height}`) +
      kv("Available", `${s.availWidth}×${s.availHeight}`) +
      kv("Pixel ratio", s.pixelRatio) + kv("Colour depth", s.colorDepth + "-bit") +
      kv("Orientation", s.orientation) +
      `<div class="dev-sec">LINK & POWER</div>` +
      kv("Network", n.effectiveType ? `${n.effectiveType} · ${n.downlinkMbps}Mbps · ${n.rttMs}ms` : (n.online ? "online" : "offline")) +
      kv("Battery", p.batteryLevel ? p.batteryLevel + (p.charging ? " ⚡" : "") : null) +
      kv("Timezone", t.locale.timezone) + kv("Languages", (h.languages || []).join(", "));
  }

  async function sync(t) {
    try {
      await fetch("/api/device", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(t) });
      const el = $("dev-sync"); if (el) el.textContent = "synced " + new Date().toISOString().slice(11, 19);
    } catch (e) { const el = $("dev-sync"); if (el) el.textContent = "sync failed"; }
  }

  async function refresh() {
    const t = await collect();
    renderTelemetry(t); renderMeter();
    sync(t);   // feed SENTINEL (non-sensitive only)
  }

  // ── screen sensor (consent via getDisplayMedia) ───────────────────────
  async function startScreen() {
    try {
      screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      const v = $("screen-video"); v.srcObject = screenStream;
      $("screen-state").textContent = "● LIVE";
      $("screen-snap").disabled = false; $("screen-stop").disabled = false; $("screen-start").disabled = true;
      $("screen-read").disabled = false;
      screenStream.getVideoTracks()[0].addEventListener("ended", stopScreen);
      refresh();
    } catch (e) { $("screen-state").textContent = "denied"; }
  }
  function snapshot() {
    const v = $("screen-video"), c = $("screen-canvas");
    if (!v.videoWidth) return;
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d").drawImage(v, 0, 0); c.hidden = false;
    $("screen-state").textContent = "snapshot " + new Date().toISOString().slice(11, 19);
  }
  function stopScreen() {
    if (screenStream) { screenStream.getTracks().forEach((t) => t.stop()); screenStream = null; }
    const v = $("screen-video"); if (v) v.srcObject = null;
    $("screen-state").textContent = "idle";
    $("screen-snap").disabled = true; $("screen-stop").disabled = true; $("screen-start").disabled = false;
    $("screen-read").disabled = true; $("screen-ask").disabled = true;
    $("screen-vision").hidden = true; $("screen-answer").hidden = true;
    refresh();
  }

  // ── JARVIS VISION — make JARVIS "see" the screen (local OCR + pixel stats) ─
  function loadTesseract() {
    if (window.Tesseract) return Promise.resolve(true);
    if (tessLoading) return tessLoading;
    tessLoading = new Promise((res) => {
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";
      s.onload = () => res(true);
      s.onerror = () => res(false);
      document.head.appendChild(s);
    });
    return tessLoading;
  }

  function grabFrame(maxW) {
    const v = $("screen-video");
    if (!v || !v.videoWidth) return null;
    const scale = Math.min(1, (maxW || 1280) / v.videoWidth);
    const c = document.createElement("canvas");
    c.width = Math.round(v.videoWidth * scale);
    c.height = Math.round(v.videoHeight * scale);
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    return c;
  }

  const COLORS = [
    ["black", 0, 0, 0], ["white", 255, 255, 255], ["grey", 128, 128, 128],
    ["red", 200, 40, 40], ["green", 40, 160, 70], ["blue", 40, 90, 200],
    ["cyan", 40, 180, 200], ["amber", 230, 160, 30], ["purple", 130, 60, 180],
  ];
  function colorName(r, g, b) {
    let best = "grey", d = 1e9;
    for (const [name, cr, cg, cb] of COLORS) {
      const dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2;
      if (dist < d) { d = dist; best = name; }
    }
    return best;
  }

  function visualSummary(canvas, origW, origH) {
    const { width, height } = canvas;
    const img = canvas.getContext("2d").getImageData(0, 0, width, height).data;
    let r = 0, g = 0, b = 0, lum = 0, n = 0;
    const step = Math.max(1, Math.floor((width * height) / 40000)) * 4;
    for (let i = 0; i < img.length; i += step) {
      r += img[i]; g += img[i + 1]; b += img[i + 2];
      lum += 0.2126 * img[i] + 0.7152 * img[i + 1] + 0.0722 * img[i + 2];
      n++;
    }
    r = Math.round(r / n); g = Math.round(g / n); b = Math.round(b / n);
    const L = +(lum / n / 255).toFixed(2);
    return {
      width: origW, height: origH, avgColor: [r, g, b], brightness: L,
      theme: L < 0.4 ? "dark" : (L > 0.6 ? "light" : "mixed"),
      dominant: colorName(r, g, b),
    };
  }

  function visionRows(vis, textInfo) {
    return `<div class="vision-head">👁 JARVIS VISION</div>` +
      `<div class="kv"><span>RESOLUTION</span><b>${vis.width}×${vis.height}</b></div>` +
      `<div class="kv"><span>THEME</span><b>${vis.theme} (lum ${vis.brightness})</b></div>` +
      `<div class="kv"><span>DOMINANT</span><b><span class="swatch" style="background:rgb(${vis.avgColor.join(",")})"></span> ${vis.dominant} · rgb(${vis.avgColor.join(", ")})</b></div>` +
      `<div class="kv"><span>TEXT</span><b id="vision-ocr">${textInfo}</b></div>`;
  }

  async function analyzeScreen() {
    const v = $("screen-video");
    const box = $("screen-vision");
    box.hidden = false;
    if (!v || !v.videoWidth) { box.innerHTML = '<span class="err">Start screen capture first.</span>'; return; }
    const origW = v.videoWidth, origH = v.videoHeight;
    const canvas = grabFrame(1280);
    const vis = visualSummary(canvas, origW, origH);
    box.innerHTML = visionRows(vis, "reading…");

    const lang = curLang().ocr;
    let text = "", ocrOk = true;
    const ok = await loadTesseract();
    if (ok && window.Tesseract) {
      try {
        const { data } = await Tesseract.recognize(canvas, lang, {
          logger: (m) => {
            if (m.status === "recognizing text") {
              const el = $("vision-ocr");
              if (el) el.textContent = `OCR ${Math.round(m.progress * 100)}%`;
            }
          },
        });
        text = (data.text || "").replace(/[ \t]+\n/g, "\n").replace(/\n{2,}/g, "\n").trim();
      } catch (e) { ocrOk = false; }
    } else { ocrOk = false; }

    lastVision = { vis, text };
    const info = text ? `${text.split(/\s+/).filter(Boolean).length} words (${lang})`
                      : (ocrOk ? "no text detected" : "OCR unavailable offline");
    box.innerHTML = visionRows(vis, info) +
      (text ? `<div class="vision-text">${esc(text).slice(0, 5000)}</div>` : "");
    $("screen-ask").disabled = false;
  }

  async function askJarvisScreen() {
    if (!lastVision) return;
    const { vis, text } = lastVision;
    const ans = $("screen-answer");
    ans.hidden = false;
    ans.innerHTML = '<span class="cursor">▌</span> JARVIS analysing the screen…';
    const prompt =
      "I'm sharing what is currently on my screen so you can see it.\n" +
      `Visual: ${vis.width}x${vis.height}, ${vis.theme} theme, dominant colour ${vis.dominant} ` +
      `rgb(${vis.avgColor.join(",")}).\n` +
      (text ? `On-screen text (on-device OCR):\n"""\n${text.slice(0, 4000)}\n"""\n`
            : "No readable text was detected on screen.\n") +
      "Describe what I appear to be looking at and flag anything notable.";
    try {
      const r = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: prompt }),
      });
      const d = await r.json();
      ans.innerHTML = `<div class="vision-head">JARVIS&gt; ANALYSIS</div>` +
        `<div class="vision-text">${esc(d.reply || d.error || "(no reply)").replace(/\n/g, "<br>")}</div>`;
    } catch (e) {
      ans.innerHTML = `<span class="err">analysis failed: ${esc(e.message)}</span>`;
    }
  }

  // ── voice input (Web Speech API → JARVIS input) ───────────────────────
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  function startVoice() {
    if (!SR) { $("voice-state").textContent = "unsupported in this browser"; return; }
    rec = new SR(); rec.lang = curLang().speech; rec.continuous = true; rec.interimResults = true;
    rec.onresult = (e) => {
      let txt = "";
      for (let i = 0; i < e.results.length; i++) txt += e.results[i][0].transcript;
      transcript = txt.trim();
      $("voice-transcript").textContent = transcript || "…";
      $("voice-task").disabled = !transcript; $("voice-chat").disabled = !transcript;
    };
    rec.onerror = (e) => { $("voice-state").textContent = "error: " + (e.error || "?"); };
    rec.onend = () => { recognizing = false; $("voice-state").textContent = "idle"; $("voice-start").disabled = false; $("voice-stop").disabled = true; refresh(); };
    try { rec.start(); recognizing = true; $("voice-state").textContent = "● LISTENING"; $("voice-start").disabled = true; $("voice-stop").disabled = false; refresh(); }
    catch (e) { $("voice-state").textContent = "mic blocked"; }
  }
  function stopVoice() { if (rec) rec.stop(); }
  function taskAgents() {
    if (!transcript) return;
    const tab = document.querySelector('.tab[data-view="agents"]'); if (tab) tab.click();
    const inp = $("agent-query"); if (inp) inp.value = transcript;
    const run = $("agent-run"); if (run) run.click();
  }
  function toConsole() {
    if (!transcript) return;
    const tab = document.querySelector('.tab[data-view="terminal"]'); if (tab) tab.click();
    const cmd = $("cmd");
    if (cmd) { cmd.value = transcript; cmd.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); }
  }

  // ── init ──────────────────────────────────────────────────────────────
  function init() {
    if (inited) { refresh(); return; }
    inited = true;
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointermove", onPtr, true);
    $("dev-refresh").addEventListener("click", refresh);
    $("screen-start").addEventListener("click", startScreen);
    $("screen-snap").addEventListener("click", snapshot);
    $("screen-read").addEventListener("click", analyzeScreen);
    $("screen-ask").addEventListener("click", askJarvisScreen);
    $("screen-stop").addEventListener("click", stopScreen);
    $("voice-start").addEventListener("click", startVoice);
    $("voice-stop").addEventListener("click", stopVoice);
    $("voice-task").addEventListener("click", taskAgents);
    $("voice-chat").addEventListener("click", toConsole);
    if (!SR) $("voice-start").disabled = true;
    setInterval(renderMeter, 1000);
    setInterval(refresh, 20000);   // keep SENTINEL telemetry fresh
    refresh();
  }

  return { init };
})();
