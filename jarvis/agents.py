"""J.A.R.V.I.S. agent harness — orchestrator + specialised subagents.

A small but real multi-agent system layered over DeepSeek:

  * Each :class:`Agent` is a specialist with its own persona (system prompt) and
    a set of *tools* — the live data modules it is allowed to read. Given a task
    it gathers its tool context and produces a focused assessment.
  * The :func:`run_taskforce` orchestrator (the "Director") routes a task to the
    relevant subagents, runs them concurrently, then synthesises their findings
    into a single intelligence answer with attribution.

Degrades gracefully: with no DeepSeek key, each agent returns a clearly-labelled
data-derived briefing instead of model prose, so the harness stays demonstrable.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Iterator, List

from jarvis import deepseek, device, gdelt, markets, news, runtime, satellite, signals, surveillance


# ─────────────────────────────────────────────────────────────────────────
#  Tools — each returns a compact text digest the agents reason over.
# ─────────────────────────────────────────────────────────────────────────
def _headlines(topics: List[str] | None = None, limit: int = 12) -> str:
    items = news.get_news().get("items", [])
    if topics:
        items = [i for i in items if i["topic"] in topics]
    lines = [f"- [{i['time']} {i['region']}/{i['topic']}] {i['title']}" for i in items[:limit]]
    return "\n".join(lines) or "(no relevant headlines)"


def _gdelt_digest() -> str:
    themes = gdelt.get_gdelt().get("themes", {})
    parts = [f"{k}: vol {v.get('trend_pct','?')}% vs mean, tone {v.get('tone','?')}"
             for k, v in themes.items() if "tone" in v]
    return "; ".join(parts) or "(no GDELT data)"


def _markets_digest() -> str:
    m = markets.get_markets()
    movers = "; ".join(f"{i['symbol']} {i['chg']:+}%" for i in m.get("instruments", [])[:6])
    return f"sentiment {m.get('sentiment')} (risk index {m.get('risk_index')}); {movers}"


def _surveillance_digest() -> str:
    s = surveillance.get_surveillance()
    seis = s.get("seismic", {}) or {}
    top = (seis.get("events") or [{}])[0]
    return (f"threat posture {s.get('posture')}; peak seismic M{seis.get('peak_mag', 0)} "
            f"{top.get('place', '')}".strip())


def _satellite_digest() -> str:
    ev = (satellite.get_satellite().get("events") or {}).get("events", [])
    return "; ".join(f"{e['tag']}: {e['title']}" for e in ev[:6]) or "(no satellite events)"


def _signals_digest() -> str:
    sig = signals.build_signals()
    doms = sorted(sig["domains"].items(), key=lambda x: -x[1]["momentum"])[:5]
    mom = "; ".join(f"{d} z={v['momentum']} ({v['level']}, vol {v['volume']})" for d, v in doms)
    anom = "; ".join(sig["anomalies"][:4]) or "none"
    return f"top momentum → {mom} | anomalies: {anom}"


def _device_digest() -> str:
    d = device.get_device()
    if not d or not any(k in d for k in ("memory", "hardware", "screen")):
        return "(no device telemetry synced — open the DEVICE panel to grant access)"
    m, h = d.get("memory", {}), d.get("hardware", {})
    s, n = d.get("screen", {}), d.get("network", {})
    p, cap = d.get("power", {}), d.get("capture", {})
    inp = d.get("input", {})
    parts = []
    if h:
        parts.append(f"{h.get('cores', '?')} cores · {h.get('platform', '?')}")
    if m:
        parts.append(f"RAM~{m.get('deviceMemoryGB', '?')}GB · JS heap {m.get('jsHeapMB', '?')}MB · "
                     f"storage {m.get('storageUsageMB', '?')}/{m.get('storageQuotaMB', '?')}MB")
    if s:
        parts.append(f"screen {s.get('width', '?')}x{s.get('height', '?')}@{s.get('pixelRatio', '?')}x")
    if n:
        parts.append(f"net {n.get('effectiveType', '?')} {n.get('downlinkMbps', '?')}Mbps "
                     f"({'online' if n.get('online') else 'offline'})")
    if p:
        parts.append(f"battery {p.get('batteryLevel', '?')}{' charging' if p.get('charging') else ''}")
    if inp:
        parts.append(f"input {inp.get('keysPerMin', 0)} keys/min, {inp.get('pointerPerMin', 0)} ptr/min")
    if cap:
        parts.append(f"screen-share {'ON' if cap.get('screenSharing') else 'off'}, "
                     f"mic {'ON' if cap.get('micListening') else 'off'}")
    return "; ".join(parts)


TOOLS: Dict[str, Callable[[], str]] = {
    "headlines": lambda: _headlines(),
    "headlines:conflict": lambda: _headlines(["CONFLICT", "POLITICS"]),
    "headlines:markets": lambda: _headlines(["MARKETS"]),
    "headlines:disaster": lambda: _headlines(["DISASTER", "HEALTH"]),
    "headlines:cyber": lambda: _headlines(["CYBER", "TECH", "SPACE"]),
    "gdelt": _gdelt_digest,
    "markets": _markets_digest,
    "surveillance": _surveillance_digest,
    "satellite": _satellite_digest,
    "signals": _signals_digest,
    "device": _device_digest,
}


# ─────────────────────────────────────────────────────────────────────────
#  Agents
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class Agent:
    name: str
    role: str
    system: str
    tools: List[str]
    keywords: List[str] = field(default_factory=list)

    def gather(self) -> str:
        blocks = []
        for t in self.tools:
            fn = TOOLS.get(t)
            if fn:
                try:
                    blocks.append(f"[{t}]\n{fn()}")
                except Exception as exc:
                    blocks.append(f"[{t}] unavailable: {exc}")
        return "\n\n".join(blocks)

    def run(self, task: str) -> Dict:
        context = self.gather()
        if runtime.ai_online():
            messages = [
                {"role": "system", "content": self.system},
                {"role": "user", "content":
                    f"TASKING: {task}\n\nYOUR LIVE DATA:\n{context}\n\n"
                    "Give a focused assessment in <120 words: lead with your BLUF, "
                    "then 2-3 supporting points. Plain text. Flag uncertainty."},
            ]
            try:
                findings = deepseek.complete(messages, temperature=0.4, max_tokens=420)
                mode = "ai"
            except deepseek.DeepSeekError as exc:
                findings = f"[AGENT ERROR] {exc}"
                mode = "error"
        else:
            findings = (f"[OFFLINE] {self.role} working set (no DeepSeek key — "
                        f"showing source data):\n{context}")
            mode = "offline"
        return {"name": self.name, "role": self.role, "tools": self.tools,
                "mode": mode, "findings": findings}


AGENTS: List[Agent] = [
    Agent("GEOINT", "Geopolitical & conflict analyst",
          "You are GEOINT, a geopolitical intelligence analyst. Assess conflict "
          "risk, escalation, diplomacy and political stability from the data. Be "
          "precise and sober.",
          ["headlines:conflict", "gdelt", "surveillance"],
          ["war", "conflict", "military", "geopolit", "political", "coup", "border",
           "diploma", "sanction", "election", "protest"]),
    Agent("ECONINT", "Economic & markets analyst",
          "You are ECONINT, a markets and macroeconomic analyst. Read risk "
          "sentiment, commodities and financial stress; connect markets to events.",
          ["markets", "headlines:markets", "gdelt"],
          ["market", "econom", "inflation", "stocks", "oil", "trade", "currency",
           "crypto", "recession", "bond", "rate"]),
    Agent("GEOPHYS", "Disaster & earth-systems analyst",
          "You are GEOPHYS, a natural-hazards analyst. Assess seismic activity, "
          "satellite-detected events (fires/volcanoes/storms) and disaster impact.",
          ["surveillance", "satellite", "headlines:disaster"],
          ["earthquake", "quake", "volcan", "disaster", "flood", "storm", "fire",
           "hurricane", "tsunami", "seismic", "outbreak", "health"]),
    Agent("CYBER", "Cyber & technology threat analyst",
          "You are CYBER, a cyber and emerging-tech threat analyst. Assess cyber "
          "incidents, breaches, and technology/space developments.",
          ["headlines:cyber"],
          ["cyber", "hack", "breach", "ransomware", "malware", "ai ", "chip",
           "satellite", "space", "tech", "semiconductor"]),
    Agent("ORACLE", "Predictive forecaster",
          "You are the ORACLE, a forecasting analyst. From the signal momentum and "
          "anomalies, predict the most likely near-term developments with rough "
          "probabilities and time horizons.",
          ["signals", "gdelt"],
          ["predict", "forecast", "future", "next", "likely", "expect", "outlook",
           "anticipate", "will"]),
    Agent("OSINT", "Open-source intelligence generalist",
          "You are OSINT, a generalist open-source analyst. Give a clear, neutral "
          "synthesis of the overall situation from the open news picture.",
          ["headlines", "gdelt"],
          ["news", "situation", "overview", "summary", "happening", "global",
           "world", "brief", "what is going on", "current"]),
    Agent("MEDINT", "Health & biosecurity analyst",
          "You are MEDINT, a public-health and biosecurity analyst. Assess outbreaks, "
          "disease spread and health-system stress.",
          ["headlines:disaster", "gdelt"],
          ["health", "disease", "outbreak", "virus", "pandemic", "epidemic", "bio",
           "medical", "vaccine", "hospital"]),
    Agent("ENERGY", "Energy & supply-chain analyst",
          "You are ENERGY, an energy, commodities and supply-chain analyst. Assess "
          "oil/gas/power, critical commodities and logistics disruption.",
          ["markets", "headlines:markets", "gdelt"],
          ["energy", "oil", "gas", "power", "supply chain", "commodit", "opec",
           "pipeline", "shipping", "logistics", "grid", "fuel"]),
    Agent("CLIMATE", "Climate & environment analyst",
          "You are CLIMATE, an environment and climate-hazard analyst. Assess "
          "extreme weather, wildfires, floods, drought and environmental impact.",
          ["satellite", "surveillance", "headlines:disaster"],
          ["climate", "environment", "weather", "wildfire", "flood", "drought",
           "emission", "warming", "heatwave", "hurricane", "cyclone"]),
    Agent("SENTINEL", "Local device & sensor analyst",
          "You are SENTINEL, the operator's local device sensor analyst. Report the "
          "operator's device posture (compute, memory, screen, network, power, "
          "input/capture state) and flag any local constraints or anomalies.",
          ["device"],
          ["device", "screen", "memory", "ram", "cpu", "local", "system", "hardware",
           "battery", "sensor", "my computer", "my phone", "this machine"]),
    Agent("REDCELL", "Adversarial red-team analyst",
          "You are REDCELL, a red-team contrarian. Challenge the consensus: state the "
          "strongest alternative hypothesis, the biggest blind spot, and the worst "
          "plausible case the other desks may be underweighting. Be sharp, not "
          "reflexively negative.",
          ["signals", "headlines"],
          ["red team", "redcell", "worst case", "adversary", "challenge", "devil",
           "contrarian", "blind spot", "what could go wrong", "risk"]),
]

AGENTS_BY_NAME = {a.name: a for a in AGENTS}
# Default desk when a task doesn't clearly map to specialists.
CORE = ["OSINT", "GEOINT", "ECONINT", "GEOPHYS", "ORACLE"]
MAX_AGENTS = 7  # bound fan-out (latency / token cost) per tasking


def route(query: str) -> List[Agent]:
    """Pick the relevant subagents for a task (keyword routing + core fallback)."""
    q = (query or "").lower()
    selected = [a for a in AGENTS if any(k in q for k in a.keywords)]
    names = {a.name for a in selected}
    if not selected:
        selected = [AGENTS_BY_NAME[n] for n in CORE]
        names = set(CORE)
    # The ORACLE rides along on any forward-looking phrasing.
    if "ORACLE" not in names and any(w in q for w in ("predict", "forecast", "future", "next", "will", "likely")):
        selected.append(AGENTS_BY_NAME["ORACLE"])
        names.add("ORACLE")
    return selected[:MAX_AGENTS]


DIRECTOR_SYSTEM = (
    "You are J.A.R.V.I.S., the intelligence director coordinating a desk of "
    "specialist analysts. Fuse their reports into one coherent briefing for the "
    "Operator: a one-line BLUF, then the integrated picture, then the single most "
    "important watch item. Attribute key judgements to the desk that made them "
    "(e.g. 'GEOINT assesses…'). Resolve disagreements explicitly. <180 words."
)


def synthesise(query: str, results: List[Dict]) -> Dict:
    digest = "\n\n".join(f"=== {r['name']} ({r['role']}) ===\n{r['findings']}" for r in results)
    if runtime.ai_online():
        try:
            text = deepseek.complete(
                [{"role": "system", "content": DIRECTOR_SYSTEM},
                 {"role": "user", "content": f"OPERATOR TASKING: {query}\n\nDESK REPORTS:\n{digest}"}],
                temperature=0.35, max_tokens=520)
            return {"text": text, "mode": "ai"}
        except deepseek.DeepSeekError as exc:
            return {"text": f"[SYNTHESIS ERROR] {exc}", "mode": "error"}
    bluf = "; ".join(f"{r['name']} reporting" for r in results)
    return {"text": f"[OFFLINE] Director synthesis unavailable without a DeepSeek "
                    f"key. Desks engaged: {bluf}. See individual reports below.",
            "mode": "offline"}


def run_taskforce(query: str) -> Dict:
    """Blocking: route → run subagents concurrently → synthesise."""
    agents = route(query)
    results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=min(6, len(agents))) as pool:
        futures = {pool.submit(a.run, query): a for a in agents}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:
                a = futures[fut]
                results.append({"name": a.name, "role": a.role, "tools": a.tools,
                                "mode": "error", "findings": f"[ERROR] {exc}"})
    order = {a.name: i for i, a in enumerate(agents)}
    results.sort(key=lambda r: order.get(r["name"], 99))
    synthesis = synthesise(query, results)
    return {
        "query": query,
        "plan": [a.name for a in agents],
        "agents": results,
        "synthesis": synthesis,
        "online": runtime.ai_online(),
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }


def stream_taskforce(query: str) -> Iterator[Dict]:
    """Yield harness events as they happen (for SSE): plan, agent…, synthesis, done."""
    agents = route(query)
    yield {"type": "plan", "plan": [{"name": a.name, "role": a.role} for a in agents],
           "online": runtime.ai_online()}
    results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=min(6, len(agents))) as pool:
        futures = {pool.submit(a.run, query): a for a in agents}
        for fut in as_completed(futures):
            a = futures[fut]
            try:
                res = fut.result()
            except Exception as exc:
                res = {"name": a.name, "role": a.role, "tools": a.tools,
                       "mode": "error", "findings": f"[ERROR] {exc}"}
            results.append(res)
            yield {"type": "agent", "agent": res}
    order = {a.name: i for i, a in enumerate(agents)}
    results.sort(key=lambda r: order.get(r["name"], 99))
    synthesis = synthesise(query, results)
    yield {"type": "synthesis", "synthesis": synthesis}
    yield {"type": "done"}
