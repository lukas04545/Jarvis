/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S. — Orbital Intelligence Globe
   Primary: a photographic Earth on MapLibre GL (satellite raster tiles in
   GLOBE projection) with Google-Maps-style deep zoom. Intelligence markers
   (seismic, ISS, satellite events, public webcams, news) plot on top.
   Fallback: a dependency-free canvas wireframe globe when MapLibre or the tile
   CDN is unreachable (e.g. an offline / no-egress network).
   ═══════════════════════════════════════════════════════════════════════ */
window.JarvisGlobe = (() => {
  "use strict";
  const DEG = Math.PI / 180;

  // Keyless satellite imagery (Esri World Imagery, deep zoom to z19).
  const SAT_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
  const SAT_ATTR = "Imagery © Esri, Maxar, Earthstar Geographics";
  const ML_JS = "https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.js";
  const ML_CSS = "https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.css";
  const COASTLINE_URLS = [
    "https://cdn.jsdelivr.net/gh/martynafford/natural-earth-geojson@master/110m/physical/ne_110m_land.json",
  ];

  const REGION_CENTROIDS = {
    Global: [10, 0], MENA: [26, 45], Europe: [50, 10],
    Asia: [34, 100], Americas: [15, -90], Africa: [2, 20],
  };
  const SAT_COLORS = {
    FIRE: "#ff5a1b", VOLCANO: "#ff3b3b", STORM: "#38e1ff", ICE: "#dff6ff",
    ICEBERG: "#bfe9ff", FLOOD: "#5db6ff", DUST: "#caa86a", EVENT: "#ff9e1b",
  };
  const TYPES = ["seismic", "orbital", "satellite", "webcam", "news"];
  function colorForLevel(l) {
    return { CRITICAL: "#ff4d4d", SEVERE: "#ff5db1", ELEVATED: "#ff9e1b" }[l] || "#3ddc84";
  }

  let mode = null;            // 'map' | 'canvas'
  let onSelect = () => {};
  let cacheData = null;
  let points = [];
  const webcamsById = {};
  const api = {
    layers: { seismic: true, orbital: true, satellite: true, webcam: true, news: true },
    initialised: false,
  };

  // ── shared data ───────────────────────────────────────────────────────
  function buildPoints(c) {
    const out = [];
    if (!c) return out;
    const s = c.surv || {};
    if (s.seismic && s.seismic.events) {
      for (const q of s.seismic.events) {
        if (q.lat == null || q.lon == null) continue;
        out.push({ id: "q-" + (q.place || Math.random()), type: "seismic", lat: q.lat, lon: q.lon,
          color: colorForLevel(q.level), r: 4 + Math.min(q.mag || 0, 8),
          label: `M${q.mag} ${q.place}`, data: q });
      }
    }
    if (s.orbital && s.orbital.lat != null) {
      out.push({ id: "iss", type: "orbital", lat: s.orbital.lat, lon: s.orbital.lon,
        color: "#38e1ff", r: 6, label: `ISS · ${s.orbital.alt_km}km`, data: s.orbital });
    }
    const sat = c.sat || {};
    if (sat.events && sat.events.events) {
      for (const e of sat.events.events) {
        if (e.lat == null || e.lon == null) continue;
        out.push({ id: "s-" + e.id, type: "satellite", lat: e.lat, lon: e.lon,
          color: SAT_COLORS[e.tag] || SAT_COLORS.EVENT, r: 5, label: `${e.tag} · ${e.title}`, data: e });
      }
    }
    const cams = c.cams || {};
    for (const cam of (cams.webcams || [])) {
      if (cam.lat == null || cam.lon == null) continue;
      webcamsById[cam.id] = cam;
      out.push({ id: "w-" + cam.id, type: "webcam", lat: cam.lat, lon: cam.lon,
        color: "#3ddc84", r: 5, label: `◉ ${cam.title}`, data: cam });
    }
    const nd = c.newsData || {};
    for (const [region, count] of Object.entries(nd.regions || {})) {
      const ctr = REGION_CENTROIDS[region];
      if (!ctr) continue;
      out.push({ id: "n-" + region, type: "news", lat: ctr[0], lon: ctr[1], color: "#ff9e1b",
        r: 5 + Math.min(count, 10) * 0.7, label: `${region}: ${count} items`, data: { region, count } });
    }
    return out;
  }

  async function fetchJSON(u) { const r = await fetch(u); if (!r.ok) throw new Error(u); return r.json(); }
  async function fetchAll() {
    const [surv, cams, sat, newsData] = await Promise.all([
      fetchJSON("/api/surveillance").catch(() => null),
      fetchJSON("/api/webcams").catch(() => null),
      fetchJSON("/api/satellite").catch(() => null),
      fetchJSON("/api/news").catch(() => null),
    ]);
    cacheData = { surv, cams, sat, newsData };
    points = buildPoints(cacheData);
    return cacheData;
  }

  // ═══ MAPLIBRE PATH ═══════════════════════════════════════════════════
  let map = null, mapReady = false;

  function loadMapLibre() {
    if (window.maplibregl) return Promise.resolve(true);
    return new Promise((res) => {
      const link = document.createElement("link");
      link.rel = "stylesheet"; link.href = ML_CSS; document.head.appendChild(link);
      const s = document.createElement("script");
      s.src = ML_JS;
      s.onload = () => res(true);
      s.onerror = () => res(false);
      document.head.appendChild(s);
    });
  }

  function geojson() {
    return {
      type: "FeatureCollection",
      features: points.map((p) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        properties: { type: p.type, color: p.color, label: p.label, id: p.id,
          r: p.r, data: JSON.stringify(p.data) },
      })),
    };
  }

  function initMap() {
    map = new maplibregl.Map({
      container: "globe-map",
      style: {
        version: 8,
        projection: { type: "globe" },        // 3D globe (MapLibre GL v5+)
        glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
        sources: { sat: { type: "raster", tiles: [SAT_TILES], tileSize: 256, maxzoom: 19, attribution: SAT_ATTR } },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#04060c" } },
          { id: "sat", type: "raster", source: "sat" },
        ],
      },
      center: [0, 20], zoom: 1.4, minZoom: 0.5, maxZoom: 19,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    map.on("load", () => {
      try { map.setProjection({ type: "globe" }); } catch (e) { /* mercator fallback */ }
      map.addSource("intel", { type: "geojson", data: geojson() });
      for (const t of TYPES) {
        map.addLayer({
          id: "intel-" + t, type: "circle", source: "intel",
          filter: ["==", ["get", "type"], t],
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, ["*", 0.8, ["coalesce", ["get", "r"], 5]], 8, ["*", 1.8, ["coalesce", ["get", "r"], 5]]],
            "circle-color": ["get", "color"], "circle-opacity": 0.9,
            "circle-stroke-width": 1.2, "circle-stroke-color": "rgba(0,0,0,0.6)",
          },
        });
        map.on("click", "intel-" + t, onMapClick);
        map.on("mouseenter", "intel-" + t, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "intel-" + t, () => { map.getCanvas().style.cursor = ""; });
      }
      mapReady = true;
      applyLayerVisibility();
    });
    map.on("move", updateHudMap);
    mode = "map";
    setHint("drag to pan · scroll / pinch to zoom deep · tap a marker for intel");
  }

  function onMapClick(e) {
    const f = e.features && e.features[0];
    if (!f) return;
    let data = {}; try { data = JSON.parse(f.properties.data); } catch (x) { /* */ }
    const m = { type: f.properties.type, id: f.properties.id, label: f.properties.label, data };
    onSelect(m, m.type === "webcam" ? data : null);
    new maplibregl.Popup({ closeButton: false, offset: 10 })
      .setLngLat(e.lngLat).setHTML(`<div style="font:11px monospace;color:#0a0d12">${(f.properties.label || "").replace(/[<>]/g, "")}</div>`)
      .addTo(map);
  }

  function applyLayerVisibility() {
    if (!mapReady) return;
    for (const t of TYPES) {
      if (map.getLayer("intel-" + t))
        map.setLayoutProperty("intel-" + t, "visibility", api.layers[t] ? "visible" : "none");
    }
  }
  function setMapData() { if (mapReady && map.getSource("intel")) map.getSource("intel").setData(geojson()); }
  function updateHudMap() {
    const c = map.getCenter();
    setCoords(`LAT ${c.lat.toFixed(3)}  LON ${c.lng.toFixed(3)}  Z ${map.getZoom().toFixed(1)}  · satellite`);
  }

  // ═══ CANVAS FALLBACK PATH ════════════════════════════════════════════
  let cv, ctx, dpr = 1, W = 0, H = 0, cx = 0, cy = 0, baseR = 0;
  const rot = { lat: 18, lon: -20 };
  let zoom = 1, autospin = true, running = false, raf = null, coastlines = null;
  let rendered = [], selectedId = null;

  function project(latDeg, lonDeg) {
    const lat = latDeg * DEG, lon = lonDeg * DEG, lat0 = rot.lat * DEG, lon0 = rot.lon * DEG, dl = lon - lon0;
    const cosc = Math.sin(lat0) * Math.sin(lat) + Math.cos(lat0) * Math.cos(lat) * Math.cos(dl);
    const R = baseR * zoom;
    return { x: cx + R * Math.cos(lat) * Math.sin(dl),
      y: cy - R * (Math.cos(lat0) * Math.sin(lat) - Math.sin(lat0) * Math.cos(lat) * Math.cos(dl)),
      visible: cosc > 0 };
  }
  function strokePath(coords, lonLat) {
    ctx.beginPath(); let started = false;
    for (const c of coords) {
      const p = lonLat ? project(c[1], c[0]) : project(c[0], c[1]);
      if (!p.visible) { started = false; continue; }
      if (!started) { ctx.moveTo(p.x, p.y); started = true; } else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
  }
  function drawCanvas(t) {
    ctx.clearRect(0, 0, W, H);
    const R = baseR * zoom;
    const g = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R);
    g.addColorStop(0, "#10243a"); g.addColorStop(0.55, "#0a1626"); g.addColorStop(1, "#04080e");
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fillStyle = g; ctx.fill();
    ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, R + 1, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(56,225,255,0.35)"; ctx.lineWidth = 2; ctx.shadowColor = "rgba(56,225,255,0.5)"; ctx.shadowBlur = 18; ctx.stroke(); ctx.restore();
    ctx.strokeStyle = "rgba(56,225,255,0.10)"; ctx.lineWidth = 1;
    for (let lon = -180; lon < 180; lon += 30) { const pts = []; for (let lat = -90; lat <= 90; lat += 3) pts.push([lon, lat]); strokePath(pts, true); }
    for (let lat = -60; lat <= 60; lat += 30) { const pts = []; for (let lon = -180; lon <= 180; lon += 3) pts.push([lon, lat]); strokePath(pts, true); }
    if (coastlines) { ctx.strokeStyle = "rgba(61,220,132,0.55)"; for (const ring of coastlines) strokePath(ring, true); }
    rendered = [];
    for (const m of points) {
      if (!api.layers[m.type]) continue;
      const p = project(m.lat, m.lon); if (!p.visible) continue;
      const pulse = 0.6 + 0.4 * Math.sin(t / 300);
      ctx.beginPath(); ctx.arc(p.x, p.y, m.r + 4 * pulse, 0, Math.PI * 2); ctx.fillStyle = m.color + "33"; ctx.fill();
      ctx.beginPath(); ctx.arc(p.x, p.y, m.r, 0, Math.PI * 2); ctx.fillStyle = m.color; ctx.fill();
      if (m.id === selectedId) { ctx.beginPath(); ctx.arc(p.x, p.y, m.r + 7, 0, Math.PI * 2); ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke(); }
      rendered.push({ x: p.x, y: p.y, r: Math.max(m.r, 8), m });
    }
    setCoords(`LAT ${rot.lat.toFixed(1)}  LON ${(((rot.lon + 540) % 360) - 180).toFixed(1)}  ZOOM ${zoom.toFixed(1)}x · wireframe (offline)`);
  }
  function frame(t) { if (!running || mode !== "canvas") return; if (autospin) rot.lon = (rot.lon + 0.06) % 360; drawCanvas(t); raf = requestAnimationFrame(frame); }

  function bindCanvas() {
    let drag = false, lx = 0, ly = 0, moved = 0, pinch = 0;
    const down = (x, y) => { drag = true; lx = x; ly = y; moved = 0; autospin = false; };
    const move = (x, y) => { if (!drag) return; const dx = x - lx, dy = y - ly; moved += Math.abs(dx) + Math.abs(dy);
      rot.lon = (rot.lon - dx * 0.3 / zoom) % 360; rot.lat = Math.max(-89, Math.min(89, rot.lat + dy * 0.3 / zoom)); lx = x; ly = y; };
    const up = (x, y) => { drag = false; if (moved < 5) hit(x, y); setTimeout(() => { autospin = true; }, 4000); };
    const rel = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    cv.addEventListener("mousedown", (e) => down(...rel(e)));
    window.addEventListener("mousemove", (e) => { if (drag && cv) move(...rel(e)); });
    window.addEventListener("mouseup", (e) => { if (drag && cv) up(...rel(e)); });
    cv.addEventListener("wheel", (e) => { e.preventDefault(); zoom = Math.max(0.7, Math.min(6, zoom * (e.deltaY < 0 ? 1.12 : 0.89))); }, { passive: false });
    cv.addEventListener("touchstart", (e) => { const r = cv.getBoundingClientRect();
      if (e.touches.length === 1) down(e.touches[0].clientX - r.left, e.touches[0].clientY - r.top);
      else if (e.touches.length === 2) pinch = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); }, { passive: true });
    cv.addEventListener("touchmove", (e) => { const r = cv.getBoundingClientRect();
      if (e.touches.length === 1) move(e.touches[0].clientX - r.left, e.touches[0].clientY - r.top);
      else if (e.touches.length === 2) { const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); if (pinch) zoom = Math.max(0.7, Math.min(6, zoom * (d / pinch))); pinch = d; e.preventDefault(); } }, { passive: false });
    cv.addEventListener("touchend", (e) => { const t = e.changedTouches[0]; const r = cv.getBoundingClientRect(); if (t) up(t.clientX - r.left, t.clientY - r.top); pinch = 0; });
  }
  function hit(x, y) { let best = null, bd = 16; for (const o of rendered) { const d = Math.hypot(o.x - x, o.y - y); if (d < Math.max(bd, o.r)) { best = o.m; bd = d; } }
    if (best) { selectedId = best.id; onSelect(best, best.type === "webcam" ? webcamsById[best.data.id] : null); } }
  function resizeCanvas() { const r = cv.parentElement.getBoundingClientRect(); dpr = window.devicePixelRatio || 1; W = r.width; H = r.height;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + "px"; cv.style.height = H + "px"; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); cx = W / 2; cy = H / 2; baseR = Math.min(W, H) * 0.42; }
  async function loadCoastlines() { for (const u of COASTLINE_URLS) { try { const ctrl = new AbortController(); const to = setTimeout(() => ctrl.abort(), 6000);
    const r = await fetch(u, { signal: ctrl.signal }); clearTimeout(to); if (!r.ok) continue; coastlines = extractRings(await r.json()); return; } catch (e) { /* */ } } }
  function extractRings(gj) { const rings = []; for (const f of (gj.features || [])) { const g = f.geometry; if (!g) continue;
    if (g.type === "Polygon") g.coordinates.forEach((r) => rings.push(r));
    else if (g.type === "MultiPolygon") g.coordinates.forEach((p) => p.forEach((r) => rings.push(r))); } return rings; }
  function initCanvas() {
    cv = document.getElementById("globe"); cv.hidden = false;
    document.getElementById("globe-map").style.display = "none";
    ctx = cv.getContext("2d"); resizeCanvas(); bindCanvas(); window.addEventListener("resize", resizeCanvas);
    loadCoastlines(); mode = "canvas";
    setHint("drag to rotate · scroll / pinch to zoom · tap a marker (offline globe — connect for satellite Earth)");
  }

  // ── small helpers ─────────────────────────────────────────────────────
  function setCoords(t) { const el = document.getElementById("globe-coords"); if (el) el.textContent = t; }
  function setHint(t) { const el = document.getElementById("globe-hint"); if (el) el.textContent = t; }

  // ── public API ────────────────────────────────────────────────────────
  api.init = async function (canvasId, selectCb) {
    if (api.initialised) return;
    onSelect = selectCb || (() => {});
    api.initialised = true;
    await fetchAll();
    const ok = await loadMapLibre();
    if (ok && window.maplibregl) { try { initMap(); } catch (e) { initCanvas(); } }
    else { initCanvas(); }
    // init is async, so the external show() already ran (as a no-op while mode
    // was null). Start the renderer now that the mode is established.
    api.show();
  };
  api.show = function () {
    if (mode === "map" && map) setTimeout(() => map.resize(), 50);
    else if (mode === "canvas" && !running) { running = true; resizeCanvas(); raf = requestAnimationFrame(frame); }
  };
  api.hide = function () { if (mode === "canvas") { running = false; if (raf) cancelAnimationFrame(raf); } };
  api.reload = async function () { await fetchAll(); if (mode === "map") setMapData(); };
  api.setLayer = function (name, on) { api.layers[name] = on; if (mode === "map") applyLayerVisibility(); };
  api.select = function (id) {
    selectedId = id;
    if (mode === "map" && map) { const p = points.find((x) => x.id === id); if (p) map.flyTo({ center: [p.lon, p.lat], zoom: Math.max(map.getZoom(), 6) }); }
  };
  api._cache = null;
  return api;
})();
