/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S. — Neural Memory ("the brain")
   Persistent memories are NEURONS (dots); shared keywords are SYNAPSES (lines).
   A lightweight force-directed layout animates the graph on a canvas; clicking
   a neuron inspects the memory. Self-contained, no dependencies.
   ═══════════════════════════════════════════════════════════════════════ */
window.JarvisBrain = (() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const KIND_COLORS = {
    note: "#38e1ff", taskforce: "#ff9e1b", chat: "#3ddc84",
    osint: "#ff5db1", intel: "#9d7bff", fact: "#7ad6c0",
  };

  let cv, ctx, dpr = 1, W = 0, H = 0;
  let running = false, raf = null, inited = false;
  let nodes = [], edges = [], byId = {};
  let selected = null, hover = null;
  let dragNode = null;

  function color(kind) { return KIND_COLORS[kind] || "#8aa0b4"; }

  // ── data ──────────────────────────────────────────────────────────────
  async function load() {
    try {
      const g = await (await fetch("/api/memory")).json();
      sync(g);
      renderStats(g);
    } catch (e) { /* ignore */ }
  }

  function sync(g) {
    const prev = byId; byId = {};
    nodes = (g.neurons || []).map((n) => {
      const old = prev[n.id];
      const node = old || { x: W / 2 + (Math.random() - 0.5) * 200, y: H / 2 + (Math.random() - 0.5) * 200, vx: 0, vy: 0 };
      Object.assign(node, n);
      byId[n.id] = node;
      return node;
    });
    edges = (g.edges || []).filter((e) => byId[e.a] && byId[e.b]);
  }

  function renderStats(g) {
    const el = $("brain-stats");
    if (el) el.textContent = `${g.count} neurons · ${g.synapses} synapses`;
    const k = $("brain-kinds");
    if (k && g.stats) k.innerHTML = Object.entries(g.stats.kinds || {})
      .map(([kind, n]) => `<span class="kind-chip" style="color:${color(kind)};border-color:${color(kind)}">${esc(kind)} ${n}</span>`).join("");
  }

  // ── physics (force-directed) ──────────────────────────────────────────
  function step() {
    const cx = W / 2, cy = H / 2;
    for (const n of nodes) {
      if (n === dragNode) continue;
      n.vx += (cx - n.x) * 0.0008;      // gentle centering
      n.vy += (cy - n.y) * 0.0008;
    }
    // repulsion
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy || 0.01;
        if (d2 > 60000) continue;
        const f = 900 / d2;
        const d = Math.sqrt(d2);
        dx /= d; dy /= d;
        a.vx += dx * f; a.vy += dy * f;
        b.vx -= dx * f; b.vy -= dy * f;
      }
    }
    // spring along synapses
    for (const e of edges) {
      const a = byId[e.a], b = byId[e.b];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 0.01;
      const target = 70 + (1 - e.w) * 90;
      const f = (d - target) * 0.01;
      const ux = dx / d, uy = dy / d;
      a.vx += ux * f; a.vy += uy * f;
      b.vx -= ux * f; b.vy -= uy * f;
    }
    for (const n of nodes) {
      if (n === dragNode) continue;
      n.vx *= 0.85; n.vy *= 0.85;
      n.x += Math.max(-6, Math.min(6, n.vx));
      n.y += Math.max(-6, Math.min(6, n.vy));
      n.x = Math.max(14, Math.min(W - 14, n.x));
      n.y = Math.max(14, Math.min(H - 14, n.y));
    }
  }

  function radius(n) { return 4 + Math.min(8, (n.degree || 0)) * 0.8 + Math.min(4, Math.log2((n.activations || 1) + 1)); }

  function draw(t) {
    ctx.clearRect(0, 0, W, H);
    // synapses
    for (const e of edges) {
      const a = byId[e.a], b = byId[e.b];
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = `rgba(56,225,255,${0.08 + e.w * 0.35})`;
      ctx.lineWidth = 0.5 + e.w * 1.5;
      ctx.stroke();
    }
    // neurons
    for (const n of nodes) {
      const r = radius(n), col = color(n.kind);
      const pulse = 0.6 + 0.4 * Math.sin(t / 600 + n.x * 0.05);
      ctx.beginPath(); ctx.arc(n.x, n.y, r + 5, 0, Math.PI * 2);
      ctx.fillStyle = col + "22"; ctx.fill();
      ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = col; ctx.globalAlpha = pulse; ctx.fill(); ctx.globalAlpha = 1;
      if (n === selected || n === hover) {
        ctx.beginPath(); ctx.arc(n.x, n.y, r + 4, 0, Math.PI * 2);
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.2; ctx.stroke();
        ctx.fillStyle = "#dfeaf4"; ctx.font = "10px 'IBM Plex Mono', monospace";
        ctx.fillText((n.text || "").slice(0, 36), n.x + r + 6, n.y + 3);
      }
    }
    if (!nodes.length) {
      ctx.fillStyle = "#6b7886"; ctx.font = "12px 'IBM Plex Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText("brain empty — imprint a memory below or run the agent mesh", W / 2, H / 2);
      ctx.textAlign = "left";
    }
  }

  function frame(t) {
    if (!running) return;
    step(); draw(t);
    raf = requestAnimationFrame(frame);
  }

  // ── interaction ───────────────────────────────────────────────────────
  function at(x, y) {
    let best = null, bd = 16;
    for (const n of nodes) {
      const d = Math.hypot(n.x - x, n.y - y);
      if (d < Math.max(bd, radius(n) + 4)) { best = n; bd = d; }
    }
    return best;
  }
  function rel(e) {
    const r = cv.getBoundingClientRect();
    const p = e.touches ? e.touches[0] : e;
    return { x: p.clientX - r.left, y: p.clientY - r.top };
  }
  function onDown(e) { const { x, y } = rel(e); dragNode = at(x, y); if (dragNode) { selected = dragNode; showDetail(dragNode); } }
  function onMove(e) {
    const { x, y } = rel(e);
    if (dragNode) { dragNode.x = x; dragNode.y = y; dragNode.vx = dragNode.vy = 0; }
    else hover = at(x, y);
  }
  function onUp() { dragNode = null; }

  function showDetail(n) {
    const el = $("brain-detail");
    if (!el) return;
    el.innerHTML =
      `<div class="vision-head" style="color:${color(n.kind)}">⬡ ${esc(n.kind).toUpperCase()} NEURON</div>` +
      `<div class="brain-mem">${esc(n.text)}</div>` +
      `<div class="news-src">${n.degree || 0} synapses · activated ${n.activations || 1}× · ` +
      `${new Date((n.created || 0) * 1000).toISOString().slice(0, 16)}Z</div>` +
      `<button class="btn-ghost" id="brain-forget" data-id="${esc(n.id)}">✕ FORGET</button>`;
    const b = $("brain-forget");
    if (b) b.addEventListener("click", async () => {
      await fetch("/api/memory/" + n.id, { method: "DELETE" });
      selected = null; el.innerHTML = "Select a neuron to inspect the memory."; load();
    });
  }

  async function imprint(text) {
    text = (text || "").trim();
    if (!text) return;
    await fetch("/api/memory", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, kind: "note" }) });
    $("brain-input").value = "";
    load();
  }

  // ── sizing / lifecycle ────────────────────────────────────────────────
  function resize() {
    const rect = cv.parentElement.getBoundingClientRect();
    dpr = window.devicePixelRatio || 1;
    W = rect.width; H = rect.height;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + "px"; cv.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function init() {
    cv = $("brain-canvas");
    if (!cv) return;
    if (!inited) {
      ctx = cv.getContext("2d");
      resize();
      window.addEventListener("resize", resize);
      cv.addEventListener("mousedown", onDown);
      window.addEventListener("mousemove", (e) => { if (cv) onMove(e); });
      window.addEventListener("mouseup", onUp);
      cv.addEventListener("touchstart", onDown, { passive: true });
      cv.addEventListener("touchmove", (e) => { onMove(e); }, { passive: true });
      cv.addEventListener("touchend", onUp);
      $("brain-add").addEventListener("click", () => imprint($("brain-input").value));
      $("brain-input").addEventListener("keydown", (e) => { if (e.key === "Enter") imprint(e.target.value); });
      $("brain-refresh").addEventListener("click", load);
      inited = true;
    }
    resize();
    load();
    if (!running) { running = true; raf = requestAnimationFrame(frame); }
  }
  function show() { if (inited) { running = running || (raf = requestAnimationFrame(frame), true); load(); } else init(); }
  function hide() { running = false; if (raf) cancelAnimationFrame(raf); }

  return { init, show, hide, reload: load };
})();
