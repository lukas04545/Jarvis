/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S. — Orbital Intelligence Globe
   A self-contained, dependency-free 3D globe (canvas 2D orthographic
   projection). Plots live intelligence — seismic, orbital, satellite events,
   public webcams, news — as markers you can rotate into view and zoom on.

   Coastlines are fetched from a public CDN when online; if unreachable, the
   globe falls back to a graticule wireframe so it always renders.
   ═══════════════════════════════════════════════════════════════════════ */
window.JarvisGlobe = (() => {
  "use strict";

  const DEG = Math.PI / 180;
  const COASTLINE_URLS = [
    "https://cdn.jsdelivr.net/gh/martynafford/natural-earth-geojson@master/110m/physical/ne_110m_land.json",
    "https://raw.githubusercontent.com/martynafford/natural-earth-geojson/master/110m/physical/ne_110m_land.json",
  ];

  const REGION_CENTROIDS = {
    Global: [10, 0], MENA: [26, 45], Europe: [50, 10],
    Asia: [34, 100], Americas: [15, -90], Africa: [2, 20],
  };

  const SAT_COLORS = {
    FIRE: "#ff5a1b", VOLCANO: "#ff3b3b", STORM: "#38e1ff", ICE: "#dff6ff",
    ICEBERG: "#bfe9ff", FLOOD: "#5db6ff", DUST: "#caa86a", EVENT: "#ff9e1b",
  };

  let cv, ctx, dpr = 1;
  let W = 0, H = 0, cx = 0, cy = 0, baseR = 0;
  const rot = { lat: 18, lon: -20 };
  let zoom = 1;
  let autospin = true;
  let running = false;
  let rafId = null;

  let coastlines = null;      // array of rings: [[lon,lat], ...]
  let markers = [];           // {type, lat, lon, color, r, label, level, data}
  let rendered = [];          // {x,y,r,marker} for hit-testing
  let selectedId = null;
  let onSelect = () => {};
  const webcamsById = {};

  // ── projection ───────────────────────────────────────────────────────
  function project(latDeg, lonDeg) {
    const lat = latDeg * DEG, lon = lonDeg * DEG;
    const lat0 = rot.lat * DEG, lon0 = rot.lon * DEG;
    const dl = lon - lon0;
    const cosc = Math.sin(lat0) * Math.sin(lat) +
                 Math.cos(lat0) * Math.cos(lat) * Math.cos(dl);
    const R = baseR * zoom;
    const x = R * Math.cos(lat) * Math.sin(dl);
    const y = R * (Math.cos(lat0) * Math.sin(lat) -
                   Math.sin(lat0) * Math.cos(lat) * Math.cos(dl));
    return { x: cx + x, y: cy - y, visible: cosc > 0 };
  }

  // ── drawing ──────────────────────────────────────────────────────────
  function drawSphere() {
    const R = baseR * zoom;
    // Ocean disk with off-centre radial shading → 3D relief.
    const g = ctx.createRadialGradient(
      cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R);
    g.addColorStop(0, "#10243a");
    g.addColorStop(0.55, "#0a1626");
    g.addColorStop(1, "#04080e");
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.fillStyle = g;
    ctx.fill();
    // Atmosphere glow.
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, R + 1, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(56,225,255,0.35)";
    ctx.lineWidth = 2;
    ctx.shadowColor = "rgba(56,225,255,0.5)";
    ctx.shadowBlur = 18;
    ctx.stroke();
    ctx.restore();
  }

  function drawGraticule() {
    ctx.strokeStyle = "rgba(56,225,255,0.10)";
    ctx.lineWidth = 1;
    // Meridians
    for (let lon = -180; lon < 180; lon += 30) {
      ctx.beginPath();
      let started = false;
      for (let lat = -90; lat <= 90; lat += 3) {
        const p = project(lat, lon);
        if (!p.visible) { started = false; continue; }
        if (!started) { ctx.moveTo(p.x, p.y); started = true; }
        else ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();
    }
    // Parallels
    for (let lat = -60; lat <= 60; lat += 30) {
      ctx.beginPath();
      let started = false;
      for (let lon = -180; lon <= 180; lon += 3) {
        const p = project(lat, lon);
        if (!p.visible) { started = false; continue; }
        if (!started) { ctx.moveTo(p.x, p.y); started = true; }
        else ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();
    }
  }

  function drawCoastlines() {
    if (!coastlines) return;
    ctx.strokeStyle = "rgba(61,220,132,0.55)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const ring of coastlines) {
      let started = false;
      for (let i = 0; i < ring.length; i++) {
        const p = project(ring[i][1], ring[i][0]);
        if (!p.visible) { started = false; continue; }
        if (!started) { ctx.moveTo(p.x, p.y); started = true; }
        else ctx.lineTo(p.x, p.y);
      }
    }
    ctx.stroke();
  }

  function drawMarkers(t) {
    rendered = [];
    for (const m of markers) {
      const p = project(m.lat, m.lon);
      if (!p.visible) continue;
      const pulse = m.pulse ? 0.5 + 0.5 * Math.sin(t / 300) : 1;
      const r = m.r;
      // glow halo
      ctx.beginPath();
      ctx.arc(p.x, p.y, r + 4 * pulse, 0, Math.PI * 2);
      ctx.fillStyle = m.color + "33";
      ctx.fill();
      // core
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fillStyle = m.color;
      ctx.fill();
      if (m.type === "orbital") {
        // ISS — draw a small ring to distinguish the satellite.
        ctx.beginPath();
        ctx.arc(p.x, p.y, r + 5, 0, Math.PI * 2);
        ctx.strokeStyle = m.color;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      if (m.id === selectedId) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, r + 7, 0, Math.PI * 2);
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.fillStyle = "#e8f4ff";
        ctx.font = "11px 'IBM Plex Mono', monospace";
        ctx.fillText(m.label || "", p.x + r + 6, p.y - r);
      }
      rendered.push({ x: p.x, y: p.y, r: Math.max(r, 8), marker: m });
    }
  }

  function frame(t) {
    if (!running) return;
    if (autospin) rot.lon = (rot.lon + 0.06) % 360;
    ctx.clearRect(0, 0, W, H);
    drawSphere();
    drawGraticule();
    drawCoastlines();
    drawMarkers(t);
    updateHud();
    rafId = requestAnimationFrame(frame);
  }

  function updateHud() {
    const el = document.getElementById("globe-coords");
    if (el) {
      el.textContent =
        `LAT ${rot.lat.toFixed(1)}  LON ${(((rot.lon + 540) % 360) - 180).toFixed(1)}  ` +
        `ZOOM ${zoom.toFixed(1)}x  MARKERS ${markers.length}`;
    }
  }

  // ── data ─────────────────────────────────────────────────────────────
  function colorForLevel(level) {
    return { CRITICAL: "#ff4d4d", SEVERE: "#ff5db1", ELEVATED: "#ff9e1b" }[level] || "#3ddc84";
  }

  function buildMarkers(surv, cams, sat, newsData) {
    const out = [];
    const layers = JarvisGlobe.layers;

    if (layers.seismic && surv && surv.seismic && surv.seismic.events) {
      for (const q of surv.seismic.events) {
        if (q.lat == null || q.lon == null) continue;
        out.push({
          id: "q-" + (q.place || Math.random()), type: "seismic",
          lat: q.lat, lon: q.lon, color: colorForLevel(q.level),
          r: 3 + Math.min(q.mag, 8), pulse: q.level === "CRITICAL" || q.level === "SEVERE",
          label: `M${q.mag} ${q.place}`, level: q.level, data: q,
        });
      }
    }
    if (layers.orbital && surv && surv.orbital && surv.orbital.lat != null) {
      const o = surv.orbital;
      out.push({
        id: "iss", type: "orbital", lat: o.lat, lon: o.lon, color: "#38e1ff",
        r: 5, pulse: true, label: `ISS · ${o.alt_km}km`, data: o,
      });
    }
    if (layers.satellite && sat && sat.events && sat.events.events) {
      for (const e of sat.events.events) {
        if (e.lat == null || e.lon == null) continue;
        out.push({
          id: "s-" + e.id, type: "satellite", lat: e.lat, lon: e.lon,
          color: SAT_COLORS[e.tag] || SAT_COLORS.EVENT, r: 4, pulse: true,
          label: `${e.tag} · ${e.title}`, data: e,
        });
      }
    }
    if (layers.webcam && cams && cams.webcams) {
      for (const c of cams.webcams) {
        if (c.lat == null || c.lon == null) continue;
        webcamsById[c.id] = c;
        out.push({
          id: "w-" + c.id, type: "webcam", lat: c.lat, lon: c.lon,
          color: "#3ddc84", r: 4, label: `◉ ${c.title}`, data: c,
        });
      }
    }
    if (layers.news && newsData && newsData.regions) {
      for (const [region, count] of Object.entries(newsData.regions)) {
        const c = REGION_CENTROIDS[region];
        if (!c) continue;
        out.push({
          id: "n-" + region, type: "news", lat: c[0], lon: c[1], color: "#ff9e1b",
          r: 4 + Math.min(count, 10) * 0.6, label: `${region}: ${count} items`,
          data: { region, count },
        });
      }
    }
    return out;
  }

  async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url);
    return r.json();
  }

  async function reloadData() {
    const [surv, cams, sat, newsData] = await Promise.all([
      fetchJSON("/api/surveillance").catch(() => null),
      fetchJSON("/api/webcams").catch(() => null),
      fetchJSON("/api/satellite").catch(() => null),
      fetchJSON("/api/news").catch(() => null),
    ]);
    JarvisGlobe._cache = { surv, cams, sat, newsData };
    markers = buildMarkers(surv, cams, sat, newsData);
    return { surv, cams, sat, newsData };
  }

  function rebuild() {
    const c = JarvisGlobe._cache;
    if (c) markers = buildMarkers(c.surv, c.cams, c.sat, c.newsData);
  }

  async function loadCoastlines() {
    for (const url of COASTLINE_URLS) {
      try {
        const ctrl = new AbortController();
        const to = setTimeout(() => ctrl.abort(), 6000);
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(to);
        if (!r.ok) continue;
        const gj = await r.json();
        coastlines = extractRings(gj);
        return;
      } catch (e) { /* try next / fall back to graticule */ }
    }
  }

  function extractRings(gj) {
    const rings = [];
    const feats = gj.features || (gj.type === "Feature" ? [gj] : []);
    for (const f of feats) {
      const g = f.geometry;
      if (!g) continue;
      if (g.type === "Polygon") g.coordinates.forEach((r) => rings.push(r));
      else if (g.type === "MultiPolygon")
        g.coordinates.forEach((poly) => poly.forEach((r) => rings.push(r)));
      else if (g.type === "LineString") rings.push(g.coordinates);
      else if (g.type === "MultiLineString") g.coordinates.forEach((r) => rings.push(r));
    }
    return rings;
  }

  // ── interaction ──────────────────────────────────────────────────────
  function bindEvents() {
    let dragging = false, lastX = 0, lastY = 0, moved = 0;
    let pinchDist = 0;

    const down = (x, y) => { dragging = true; lastX = x; lastY = y; moved = 0; autospin = false; };
    const move = (x, y) => {
      if (!dragging) return;
      const dx = x - lastX, dy = y - lastY;
      moved += Math.abs(dx) + Math.abs(dy);
      rot.lon = (rot.lon - dx * 0.3 / zoom) % 360;
      rot.lat = Math.max(-89, Math.min(89, rot.lat + dy * 0.3 / zoom));
      lastX = x; lastY = y;
    };
    const up = (x, y) => {
      dragging = false;
      if (moved < 5) hitTest(x, y);
      setTimeout(() => { autospin = true; }, 4000);
    };

    cv.addEventListener("mousedown", (e) => down(e.offsetX, e.offsetY));
    window.addEventListener("mousemove", (e) => {
      if (dragging) move(e.clientX - cv.getBoundingClientRect().left,
                          e.clientY - cv.getBoundingClientRect().top);
    });
    window.addEventListener("mouseup", (e) => {
      if (dragging) up(e.clientX - cv.getBoundingClientRect().left,
                       e.clientY - cv.getBoundingClientRect().top);
    });
    cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      zoom = Math.max(0.7, Math.min(6, zoom * (e.deltaY < 0 ? 1.12 : 0.89)));
    }, { passive: false });

    // Touch
    cv.addEventListener("touchstart", (e) => {
      const rect = cv.getBoundingClientRect();
      if (e.touches.length === 1)
        down(e.touches[0].clientX - rect.left, e.touches[0].clientY - rect.top);
      else if (e.touches.length === 2)
        pinchDist = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY);
    }, { passive: true });
    cv.addEventListener("touchmove", (e) => {
      const rect = cv.getBoundingClientRect();
      if (e.touches.length === 1)
        move(e.touches[0].clientX - rect.left, e.touches[0].clientY - rect.top);
      else if (e.touches.length === 2) {
        const d = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY);
        if (pinchDist) zoom = Math.max(0.7, Math.min(6, zoom * (d / pinchDist)));
        pinchDist = d;
        e.preventDefault();
      }
    }, { passive: false });
    cv.addEventListener("touchend", (e) => {
      const rect = cv.getBoundingClientRect();
      const t = e.changedTouches[0];
      if (t) up(t.clientX - rect.left, t.clientY - rect.top);
      pinchDist = 0;
    });
  }

  function hitTest(x, y) {
    let best = null, bestD = 16;
    for (const r of rendered) {
      const d = Math.hypot(r.x - x, r.y - y);
      if (d < Math.max(bestD, r.r)) { best = r.marker; bestD = d; }
    }
    if (best) {
      selectedId = best.id;
      onSelect(best, best.type === "webcam" ? webcamsById[best.data.id] : null);
    }
  }

  // ── sizing ───────────────────────────────────────────────────────────
  function resize() {
    if (!cv) return;
    const rect = cv.parentElement.getBoundingClientRect();
    dpr = window.devicePixelRatio || 1;
    W = rect.width; H = rect.height;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + "px"; cv.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cx = W / 2; cy = H / 2;
    baseR = Math.min(W, H) * 0.42;
  }

  // ── public API ───────────────────────────────────────────────────────
  return {
    layers: { seismic: true, orbital: true, satellite: true, webcam: true, news: true },
    _cache: null,
    initialised: false,

    init(canvasId, selectCb) {
      cv = document.getElementById(canvasId);
      if (!cv) return;
      ctx = cv.getContext("2d");
      onSelect = selectCb || (() => {});
      resize();
      bindEvents();
      window.addEventListener("resize", resize);
      this.initialised = true;
      loadCoastlines();
      reloadData();
    },
    show() {
      if (!this.initialised) return;
      resize();
      if (!running) { running = true; rafId = requestAnimationFrame(frame); }
    },
    hide() { running = false; if (rafId) cancelAnimationFrame(rafId); },
    reload: reloadData,
    setLayer(name, on) { this.layers[name] = on; rebuild(); },
    select(id) { selectedId = id; },
  };
})();
