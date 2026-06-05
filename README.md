# J.A.R.V.I.S. — Global Intelligence Terminal

> *Just A Rather Very Intelligent System.* A Bloomberg-terminal-styled,
> DeepSeek-powered situational-awareness console with **global news tracking**
> and **open-source global surveillance**.

```
◈ J.A.R.V.I.S.  GLOBAL INTELLIGENCE TERMINAL          UTC 14:22:07  AI CORE ●ONLINE  POSTURE ●NOMINAL
┌─ WORLD WIRE ────────┐┌─ J.A.R.V.I.S. AI CONSOLE ─────┐┌─ GLOBAL SURVEILLANCE ─┐
│ 14:21 CONFLICT  …   ││ OPR> sitrep                    ││ ◢ SEISMIC // USGS     │
│ 14:19 MARKETS   …   ││ JARVIS> BLUF: posture nominal… ││ M5.8 Honshu, Japan    │
│ 14:18 POLITICS  …   ││ ▌                              ││ ◢ ORBITAL // ISS      │
└─────────────────────┘└────────────────────────────────┘└───────────────────────┘
 F1 HELP  F2 WIRE  F3 SURV  F4 BRIEF  F5 REFRESH  F6 CLEAR              ● LIVE
```

## What it does

| Capability | How |
|---|---|
| **AI core (J.A.R.V.I.S.)** | DeepSeek chat-completions, streamed token-by-token into the console, with a senior-analyst persona. |
| **Global news tracking** | Aggregates 8 international RSS wires (BBC, Al Jazeera, DW, NHK, France24, CNA, AP, Reuters), dedupes, and auto-tags each item by **region** and **topic** (CONFLICT / MARKETS / POLITICS / DISASTER / TECH / HEALTH). |
| **Global surveillance** | Live OSINT sensor grid — **USGS** seismic activity, **ISS** orbital position, **NOAA** space-weather alerts — rolled into a single threat *posture* (NOMINAL → CRITICAL). |
| **AI situational briefing** | `BRIEF` / F4 packs the live wire + sensor picture into DeepSeek and returns a BLUF-style intelligence briefing. |
| **Interactive terminal** | Command line (`HELP`, `NEWS`, `SURV`, `BRIEF`, `REFRESH`, `CLEAR`, or free-text chat), function keys F1–F6, topic filters, scrolling ticker, CRT styling. |

## Quick start

```bash
./run.sh                 # creates venv, installs deps, starts the server
# → open http://localhost:8765
```

Or manually:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then paste your DeepSeek key into .env
python app.py
```

### Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DEEPSEEK_API_KEY` | *(empty)* | DeepSeek key. Empty ⇒ AI core runs **OFFLINE** with labelled stub replies. |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API endpoint. |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Model id. |
| `JARVIS_HOST` / `JARVIS_PORT` | `0.0.0.0` / `8765` | Server bind. |
| `JARVIS_CACHE_TTL` | `180` | Feed cache window (seconds). |

> Get a key at <https://platform.deepseek.com>.

## API

| Method | Route | Returns |
|---|---|---|
| `GET` | `/api/status` | system + AI core status |
| `GET` | `/api/news?topic=&region=` | aggregated, filterable news stream |
| `GET` | `/api/surveillance` | seismic + orbital + space-weather picture |
| `GET` | `/api/briefing` | AI situational briefing |
| `POST` | `/api/chat` | blocking JARVIS reply — `{"message": "..."}` |
| `POST` | `/api/chat/stream` | SSE token stream of the reply |

## Resilience

- **Stale-on-error caching** — a dead upstream serves the last good value instead of going dark.
- **Per-sensor isolation** — one failed feed degrades only its own panel.
- **SIMULATED fallback** — if *every* live feed is unreachable (e.g. a no-egress
  network), the terminal serves a clearly **SIM-badged** sample dataset so it
  stays demonstrable. Synthetic data is never presented as live.
- **OFFLINE AI** — with no key, the console returns labelled stubs rather than erroring.

## Architecture

```
app.py                  Flask routes (UI + JSON/SSE API)
config.py               env-driven configuration
jarvis/
  deepseek.py           DeepSeek client (blocking + streaming) + JARVIS persona
  news.py               RSS aggregation, dedupe, region/topic tagging
  surveillance.py       USGS / ISS / NOAA sensor grid + threat posture
  briefing.py           AI briefing synthesis from the live picture
  cache.py              thread-safe TTL cache (stale-on-error)
  fallback.py           SIMULATED sample datasets
templates/index.html    terminal layout
static/css/terminal.css Bloomberg-style phosphor UI
static/js/terminal.js   client controller (feeds, console, SSE, commands)
tests/test_jarvis.py    network-free unit + API tests
```

## Tests

```bash
. .venv/bin/activate && pip install pytest
python -m pytest -q          # 16 passing, no network required
```

## Notes

All surveillance sources are **public, keyless OSINT** feeds. This is a
situational-awareness aggregator for open data — not a covert collection tool.
