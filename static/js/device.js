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
    refresh();
  }

  // ── voice input (Web Speech API → JARVIS input) ───────────────────────
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  function startVoice() {
    if (!SR) { $("voice-state").textContent = "unsupported in this browser"; return; }
    rec = new SR(); rec.lang = "en-US"; rec.continuous = true; rec.interimResults = true;
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
