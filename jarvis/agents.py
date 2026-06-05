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

from jarvis import deepseek, gdelt, markets, news, runtime, satellite, signals, surveillance


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
]

AGENTS_BY_NAME = {a.name: a for a in AGENTS}
# Default desk when a task doesn't clearly map to specialists.
CORE = ["GEOINT", "ECONINT", "GEOPHYS", "ORACLE"]


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
    return selected


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
