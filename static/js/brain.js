/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S. — Neural Memory ("the brain"), 3D
   Persistent memories are NEURONS (dots); shared keywords are SYNAPSES (lines).
   A 3D force-directed layout runs in space; nodes are projected with
   perspective (depth → size + fog), the whole network auto-rotates, and you can
   drag to orbit, scroll to zoom, and click a neuron to inspect it.
   Self-contained — pure canvas, no dependencies, works offline.
   ═══════════════════════════════════════════════════════════════════════ */
window.JarvisBrain = (() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const KIND_COLORS = {
    note: "#38e1ff", taskforce: "#ff9e1b", chat: "#3ddc84",
    osint: "#ff5db1", intel: "#9d7bff", fact: "#7ad6c0", news: "#5db6ff",
  };
  const FOCAL = 900;          // perspective focal length
  const BOUND = 230;          // containment sphere radius

  let cv, ctx, dpr = 1, W = 0, H = 0, cx = 0, cy = 0;
  let running = false, raf = null, inited = false;
  let nodes = [], edges = [], byId = {};
  let selected = null;
  let rotX = -0.3, rotY = 0, zoom = 1, autoRotate = true;

  function color(kind) { return KIND_COLORS[kind] || "#8aa0b4"; }

  // ── data ──────────────────────────────────────────────────────────────
  async function load() {
    try {
      const g = await (await fetch("/api/memory")).json();
      sync(g); renderStats(g);
    } catch (e) { /* ignore */ }
    refreshIngest();
  }
  async function refreshIngest() {
    try {
      const s = await (await fetch("/api/ingest")).json();
      const el = document.getElementById("ingest-status");
      if (el) el.textContent = s.auto
        ? `auto · ${s.runs} runs · ${s.processor}` : `manual · ${s.processor}`;
    } catch (e) { /* ignore */ }
  }
  async function ingestNow() {
    const btn = document.getElementById("ingest-now");
    if (btn) { btn.disabled = true; btn.textContent = "⟳ scraping & distilling…"; }
    try {
      const r = await (await fetch("/api/ingest", { method: "POST" })).json();
      if (r.neurons != null) { const el = document.getElementById("ingest-status"); if (el) el.textContent = `+${r.last_count} · ${r.processor} · ${r.neurons} neurons`; }
    } catch (e) { /* ignore */ }
    if (btn) { btn.disabled = false; btn.textContent = "⟳ INGEST NEWS NOW"; }
    load();
  }
  function sync(g) {
    const prev = byId; byId = {};
    nodes = (g.neurons || []).map((n) => {
      const old = prev[n.id];
      const node = old || {
        x: (Math.random() - 0.5) * 240, y: (Math.random() - 0.5) * 240, z: (Math.random() - 0.5) * 240,
        vx: 0, vy: 0, vz: 0,
      };
      Object.assign(node, n);
      byId[n.id] = node;
      return node;
    });
    edges = (g.edges || []).filter((e) => byId[e.a] && byId[e.b]);
  }
  function renderStats(g) {
    const el = $("brain-stats");
    if (el) el.textContent = `${g.count} neurons · ${g.synapses} synapses · 3D`;
    const k = $("brain-kinds");
    if (k && g.stats) k.innerHTML = Object.entries(g.stats.kinds || {})
      .map(([kind, n]) => `<span class="kind-chip" style="color:${color(kind)};border-color:${color(kind)}">${esc(kind)} ${n}</span>`).join("");
  }

  // ── 3D physics ────────────────────────────────────────────────────────
  function step() {
    for (const n of nodes) {           // centering
      n.vx += -n.x * 0.0016; n.vy += -n.y * 0.0016; n.vz += -n.z * 0.0016;
    }
    for (let i = 0; i < nodes.length; i++) {   // repulsion
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
        let d2 = dx * dx + dy * dy + dz * dz || 0.01;
        if (d2 > 90000) continue;
        const d = Math.sqrt(d2), f = 1600 / d2;
        dx /= d; dy /= d; dz /= d;
        a.vx += dx * f; a.vy += dy * f; a.vz += dz * f;
        b.vx -= dx * f; b.vy -= dy * f; b.vz -= dz * f;
      }
    }
    for (const e of edges) {            // synapse springs
      const a = byId[e.a], b = byId[e.b];
      let dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
      const d = Math.hypot(dx, dy, dz) || 0.01;
      const target = 70 + (1 - e.w) * 80;
      const f = (d - target) * 0.01;
      dx /= d; dy /= d; dz /= d;
      a.vx += dx * f; a.vy += dy * f; a.vz += dz * f;
      b.vx -= dx * f; b.vy -= dy * f; b.vz -= dz * f;
    }
    for (const n of nodes) {
      n.vx *= 0.86; n.vy *= 0.86; n.vz *= 0.86;
      n.x += Math.max(-5, Math.min(5, n.vx));
      n.y += Math.max(-5, Math.min(5, n.vy));
      n.z += Math.max(-5, Math.min(5, n.vz));
      const r = Math.hypot(n.x, n.y, n.z);
      if (r > BOUND) { const s = BOUND / r; n.x *= s; n.y *= s; n.z *= s; }
    }
  }

  // ── projection ────────────────────────────────────────────────────────
  function project(n) {
    const cosy = Math.cos(rotY), siny = Math.sin(rotY);
    let x = n.x * cosy - n.z * siny;
    let z = n.x * siny + n.z * cosy;
    const cosx = Math.cos(rotX), sinx = Math.sin(rotX);
    let y = n.y * cosx - z * sinx;
    z = n.y * sinx + z * cosx;
    const scale = FOCAL / (FOCAL - z) * zoom;
    n.sx = cx + x * scale; n.sy = cy + y * scale; n.depth = z; n.scale = scale;
  }
  function radius(n) { return (3.5 + Math.min(8, (n.degree || 0)) * 0.7 + Math.min(4, Math.log2((n.activations || 1) + 1))) * n.scale; }
  function fog(z) { return Math.max(0.25, Math.min(1, (z + BOUND) / (2 * BOUND) * 0.85 + 0.3)); }

  function draw(t) {
    ctx.clearRect(0, 0, W, H);
    for (const n of nodes) project(n);
    // synapses
    for (const e of edges) {
      const a = byId[e.a], b = byId[e.b];
      const al = (0.06 + e.w * 0.4) * fog((a.depth + b.depth) / 2);
      ctx.beginPath(); ctx.moveTo(a.sx, a.sy); ctx.lineTo(b.sx, b.sy);
      ctx.strokeStyle = `rgba(56,225,255,${al.toFixed(3)})`;
      ctx.lineWidth = (0.4 + e.w * 1.4) * Math.min(a.scale, b.scale);
      ctx.stroke();
    }
    // neurons, far→near
    const order = [...nodes].sort((p, q) => p.depth - q.depth);
    for (const n of order) {
      const r = Math.max(1.5, radius(n)), col = color(n.kind), a = fog(n.depth);
      const pulse = 0.6 + 0.4 * Math.sin(t / 600 + n.x * 0.05);
      ctx.globalAlpha = a * 0.25;
      ctx.beginPath(); ctx.arc(n.sx, n.sy, r + 5 * n.scale, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill();
      ctx.globalAlpha = a * pulse;
      ctx.beginPath(); ctx.arc(n.sx, n.sy, r, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill();
      ctx.globalAlpha = 1;
      if (n === selected) {
        ctx.beginPath(); ctx.arc(n.sx, n.sy, r + 4, 0, Math.PI * 2); ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.3; ctx.stroke();
        ctx.fillStyle = "#dfeaf4"; ctx.font = "10px 'IBM Plex Mono', monospace";
        ctx.fillText((n.text || "").slice(0, 40), n.sx + r + 6, n.sy + 3);
      }
    }
    if (!nodes.length) {
      ctx.fillStyle = "#6b7886"; ctx.font = "12px 'IBM Plex Mono', monospace"; ctx.textAlign = "center";
      ctx.fillText("brain empty — imprint a memory below or run the agent mesh", W / 2, H / 2);
      ctx.textAlign = "left";
    }
  }

  function frame(t) {
    if (!running) return;
    if (autoRotate) rotY += 0.0035;
    step(); draw(t);
    raf = requestAnimationFrame(frame);
  }

  // ── interaction (orbit / zoom / select) ───────────────────────────────
  function rel(e) { const r = cv.getBoundingClientRect(); const p = e.touches ? e.touches[0] : e; return { x: p.clientX - r.left, y: p.clientY - r.top }; }
  function at(x, y) {
    let best = null, bestDepth = -1e9;
    for (const n of nodes) {
      const r = Math.max(radius(n), 9);
      if (Math.hypot(n.sx - x, n.sy - y) < r + 4 && n.depth > bestDepth) { best = n; bestDepth = n.depth; }
    }
    return best;
  }
  let dragging = false, lx = 0, ly = 0, moved = 0, pinch = 0;
  function down(e) { const { x, y } = rel(e); dragging = true; lx = x; ly = y; moved = 0; autoRotate = false; }
  function move(e) {
    if (!dragging) return;
    const { x, y } = rel(e); const dx = x - lx, dy = y - ly;
    moved += Math.abs(dx) + Math.abs(dy);
    rotY += dx * 0.01; rotX = Math.max(-1.45, Math.min(1.45, rotX + dy * 0.01));
    lx = x; ly = y;
  }
  function up(e) {
    dragging = false;
    if (moved < 5) { const { x, y } = rel(e.changedTouches ? { touches: e.changedTouches } : e); const n = at(x, y); if (n) { selected = n; showDetail(n); } }
    setTimeout(() => { autoRotate = true; }, 4000);
  }

  function showDetail(n) {
    const el = $("brain-detail"); if (!el) return;
    const m = n.meta || {};
    let metaHtml = "";
    if (m.source) metaHtml += `<div class="kv"><span>SOURCE</span><b>${esc(m.source)}</b></div>`;
    if (m.region || m.topic) metaHtml += `<div class="kv"><span>CONTEXT</span><b>${esc([m.region, m.topic].filter(Boolean).join(" · "))}</b></div>`;
    if (m.time) metaHtml += `<div class="kv"><span>SEEN</span><b>${esc(m.time)}</b></div>`;
    if (m.link) metaHtml += `<div class="kv"><span>LINK</span><b><a href="${esc(m.link)}" target="_blank" rel="noopener">open ↗</a></b></div>`;
    el.innerHTML =
      `<div class="vision-head" style="color:${color(n.kind)}">⬡ ${esc(n.kind).toUpperCase()} NEURON</div>` +
      `<div class="brain-mem">${esc(n.text)}</div>` +
      metaHtml +
      `<div class="news-src">${n.degree || 0} synapses · activated ${n.activations || 1}× · ${new Date((n.created || 0) * 1000).toISOString().slice(0, 16)}Z</div>` +
      `<button class="btn-ghost" id="brain-forget">✕ FORGET</button>`;
    const b = $("brain-forget");
    if (b) b.addEventListener("click", async () => { await fetch("/api/memory/" + n.id, { method: "DELETE" }); selected = null; el.innerHTML = "Select a neuron to inspect the memory."; load(); });
  }
  async function imprint(text) {
    text = (text || "").trim(); if (!text) return;
    await fetch("/api/memory", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, kind: "note" }) });
    $("brain-input").value = ""; load();
  }

  function resize() {
    const rect = cv.parentElement.getBoundingClientRect();
    dpr = window.devicePixelRatio || 1; W = rect.width; H = rect.height;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + "px"; cv.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); cx = W / 2; cy = H / 2;
  }
  function init() {
    cv = $("brain-canvas"); if (!cv) return;
    if (!inited) {
      ctx = cv.getContext("2d"); resize(); window.addEventListener("resize", resize);
      cv.addEventListener("mousedown", down);
      window.addEventListener("mousemove", (e) => { if (dragging) move(e); });
      window.addEventListener("mouseup", (e) => { if (dragging) up(e); });
      cv.addEventListener("wheel", (e) => { e.preventDefault(); zoom = Math.max(0.4, Math.min(3.5, zoom * (e.deltaY < 0 ? 1.1 : 0.9))); }, { passive: false });
      cv.addEventListener("touchstart", (e) => { if (e.touches.length === 2) pinch = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); else down(e); }, { passive: true });
      cv.addEventListener("touchmove", (e) => {
        if (e.touches.length === 2) { const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); if (pinch) zoom = Math.max(0.4, Math.min(3.5, zoom * (d / pinch))); pinch = d; e.preventDefault(); }
        else move(e);
      }, { passive: false });
      cv.addEventListener("touchend", (e) => { pinch = 0; up(e); });
      $("brain-add").addEventListener("click", () => imprint($("brain-input").value));
      $("brain-input").addEventListener("keydown", (e) => { if (e.key === "Enter") imprint(e.target.value); });
      $("brain-refresh").addEventListener("click", load);
      const ing = document.getElementById("ingest-now");
      if (ing) ing.addEventListener("click", ingestNow);
      inited = true;
    }
    resize(); load();
    if (!running) { running = true; raf = requestAnimationFrame(frame); }
  }
  function show() { if (!inited) { init(); return; } resize(); load(); if (!running) { running = true; raf = requestAnimationFrame(frame); } }
  function hide() { running = false; if (raf) cancelAnimationFrame(raf); }

  return { init, show, hide, reload: load };
})();
