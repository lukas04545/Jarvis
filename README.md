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
| **◉ Orbital Globe** | A second tab renders an interactive 3D globe (zero dependencies — canvas orthographic projection). Drag to rotate, scroll/pinch to zoom, and tap any marker for intel. All live layers plot on it: seismic, ISS, satellite events, public webcams, news clusters. |
| **🛰 Live satellite data** | Keyless open feeds: **NASA EONET** satellite-detected natural events (wildfires, volcanoes, storms…), **NASA EPIC/DSCOVR** full-disc Earth imagery, and the **CelesTrak** active-satellite catalog count. |
| **◉ Public webcams** | **Free & keyless.** Live London traffic cameras via the public **TfL JamCams** feed (geolocated, refreshing JPEGs) plus a curated worldwide public list — plotted on the globe and viewable in-terminal. See [Ethics & scope](#ethics--scope). |
| **⚙ Paste-your-key settings** | A Settings panel to paste your DeepSeek key at runtime — no file editing. Stored server-side, gitignored, never returned to the browser; the AI core flips ONLINE instantly. (Every data feed is free/keyless; only the AI core uses a key.) |
| **⊹ ORACLE — event prediction** | A forecasting engine that fuses every signal into a quantitative vector, then produces **probabilistic predictions of future events** — each with probability, confidence, time horizon, drivers, and confirm/refute indicators. Heuristic baseline + DeepSeek structured forecasts. |
| **Maximised data ingestion** | ~24 news feeds (wires, finance, conflict, cyber, space, science, health) pulled **concurrently**, plus **markets** (CoinGecko crypto + Stooq indices/commodities/FX) and **GDELT** global media volume & tone. |
| **⌬ Agent Mesh** | A multi-agent harness: Director J.A.R.V.I.S. routes a tasking to **11 specialist subagents** (GEOINT, ECONINT, GEOPHYS, CYBER, ORACLE, OSINT, MEDINT, ENERGY, CLIMATE, SENTINEL, REDCELL), each with its own persona and data tools, run **concurrently** over DeepSeek and streamed live (SSE) — then fused into one attributed briefing. |
| **⊟ Device Sensors** | Consent-gated access to the operator's **own** device via standard browser APIs: memory/hardware/screen/network/power telemetry, **screen capture** (`getDisplayMedia`, frames stay local), and **voice input** (Web Speech API → JARVIS) plus a local input-activity meter. Telemetry syncs to the **SENTINEL** agent. See [Ethics & scope](#ethics--scope). |

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

## Run on Android 📱

J.A.R.V.I.S. runs on Android two ways — use either, or both together.

### A) Install as an app (PWA)

The terminal is a fully installable Progressive Web App with offline shell
caching, a service worker, and a mobile-tuned layout (the console leads, the
function bar becomes a scrollable tap strip).

1. Start a Jarvis server somewhere reachable from the phone — your laptop on
   the same Wi-Fi (`python app.py`), the phone itself (option B), or any host.
2. Open `http://<server-ip>:8765` in **Chrome on Android**.
3. Tap the **⤓ INSTALL** button in the top bar (or *menu → Add to Home screen*).
4. Launch it from your home screen — it opens full-screen, no browser chrome,
   with its own ◈ icon. Long-pressing the icon exposes shortcuts
   (Briefing / Wire / Surveillance).

> Installability needs HTTPS **or** `localhost`. Over plain-HTTP LAN, Chrome
> still renders everything; for the install prompt put it behind HTTPS (e.g. a
> `ngrok`/`cloudflared` tunnel) or run on-device (option B, served at
> `localhost`).

### B) Run the backend on the phone (Termux)

Run the whole Flask backend natively on Android — no external server needed.

```bash
# In Termux (install from F-Droid):
pkg install git
git clone <this-repo> && cd Jarvis
bash android/termux-setup.sh
```

The script installs Python + build tools, creates a venv, installs deps, takes
a wake-lock, and serves on `http://localhost:8765` (and your LAN IP). Then
install it to the home screen via option A — at `localhost` the install prompt
works without HTTPS.

### Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DEEPSEEK_API_KEY` | *(empty)* | DeepSeek key. Empty ⇒ AI core runs **OFFLINE** with labelled stub replies. |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API endpoint. |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Model id. |
| `JARVIS_HOST` / `JARVIS_PORT` | `0.0.0.0` / `8765` | Server bind. |
| `JARVIS_CACHE_TTL` | `180` | Feed cache window (seconds). |

> Get a key at <https://platform.deepseek.com>.

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
  runtime.py            runtime-mutable API keys (pasted in Settings)
  news.py               RSS aggregation, dedupe, region/topic tagging
  surveillance.py       USGS / ISS / NOAA sensor grid + threat posture
  satellite.py          live open satellite data (NASA EONET/EPIC, CelesTrak)
  webcams.py            public webcam directory (TfL JamCams + curated, keyless)
  markets.py            crypto (CoinGecko) + indices/commodities (Stooq)
  gdelt.py              GDELT global media volume + tone signals
  signals.py            quantitative signal vector + momentum + anomalies
  forecast.py           ORACLE — heuristic + DeepSeek event predictions
  agents.py             multi-agent harness (Director + 11 specialist subagents)
  device.py             device-telemetry store (in-memory, sanitised, local)
  briefing.py           AI briefing synthesis from the live picture
  cache.py              thread-safe TTL cache (stale-on-error)
  fallback.py           SIMULATED sample datasets
templates/index.html    terminal + globe layout, tabs, settings modal
static/css/terminal.css Bloomberg-style phosphor UI (+ mobile/PWA responsive)
static/js/terminal.js   client controller (feeds, console, tabs, settings, webcams)
static/js/globe.js      dependency-free 3D orbital intelligence globe
static/js/device.js     local device sensors (telemetry, screen, voice, input)
static/js/sw.js         service worker (offline shell, network-first API)
static/manifest.webmanifest  PWA manifest (icons, shortcuts)
static/icons/*.png      generated app icons (any + maskable)
tools/make_icons.py     dependency-free PNG icon generator
android/termux-setup.sh on-device backend setup for Android/Termux
tests/test_jarvis.py    network-free unit + API + PWA tests
```

## API

| Method | Route | Returns |
|---|---|---|
| `GET` | `/api/status` | system + AI core + provider status |
| `GET`/`POST` | `/api/settings` | provider status / paste API keys (keys never returned) |
| `GET` | `/api/news` | aggregated, filterable news stream |
| `GET` | `/api/surveillance` | seismic + orbital + space-weather picture |
| `GET` | `/api/satellite` | NASA EONET events + EPIC Earth image + sat catalog |
| `GET` | `/api/webcams` | public webcam directory (keyless TfL JamCams + curated) |
| `GET` | `/api/markets` | crypto + indices + commodities + risk gauge |
| `GET` | `/api/gdelt` | global media coverage volume + tone by theme |
| `GET` | `/api/signals` | unified quantitative signal vector + anomalies |
| `GET` | `/api/forecast` | **ORACLE** — probabilistic predictions of future events |
| `POST` | `/api/agents` · `/api/agents/stream` | **Agent Mesh** — multi-agent taskforce (JSON / SSE) |
| `GET`/`POST` | `/api/device` | device telemetry store (read / report from own browser) |
| `GET` | `/api/briefing` | AI situational briefing |
| `POST` | `/api/chat` · `/api/chat/stream` | JARVIS reply (JSON / SSE) |

## ⊹ ORACLE — predicting future events

The ORACLE turns the firehose of data into falsifiable forecasts:

1. **Ingest** — ~24 news feeds (concurrent), markets, GDELT, seismic, satellite.
2. **Signals** (`signals.py`) — distil into a numeric vector: per-domain and
   per-region coverage **volume** and **momentum** (z-score vs a rolling
   in-memory baseline that sharpens as the server runs), media **tone**, market
   **risk**, geophysical posture, satellite tallies — and flag **anomalies**.
3. **Forecast** (`forecast.py`) —
   * a transparent **heuristic** layer maps momentum/tone/risk → probabilities
     (always on, even offline);
   * **DeepSeek** reasons over the full vector and returns richer predictions as
     strict JSON; the two are merged and de-duplicated.
4. **Output** — each prediction carries a `probability`, `confidence`,
   `horizon` (24h/7d/30d), `drivers`, and `confirm`/`deny` indicators, so it can
   be tracked and scored — not just asserted.

Run it from the **⊹ ORACLE · FORECAST** tab, or type `FORECAST` in the console.
Probabilities are model estimates over the stated horizon, not certainties.

## ⌬ Agent Mesh — the multi-agent harness

A small but real multi-agent system (`agents.py`) layered over DeepSeek:

- **Subagents** — each `Agent` is a specialist with its own persona and a set of
  *tools* (the live data modules it may read):
  | Agent | Desk | Tools |
  |---|---|---|
  | GEOINT | geopolitics & conflict | conflict headlines, GDELT, surveillance |
  | ECONINT | markets & macro | markets, market headlines, GDELT |
  | GEOPHYS | disasters & earth systems | seismic, satellite events, disaster news |
  | CYBER | cyber & tech threats | cyber/tech/space headlines |
  | ORACLE | forecasting | signal momentum + GDELT |
  | OSINT | open-source generalist | all headlines, GDELT |
  | MEDINT | health & biosecurity | health/disaster headlines, GDELT |
  | ENERGY | energy & supply chains | markets, market headlines, GDELT |
  | CLIMATE | climate & environment | satellite, surveillance, disaster news |
  | SENTINEL | local device & sensors | device telemetry |
  | REDCELL | adversarial red-team | signals, headlines |
- **Director** — `run_taskforce(query)` **routes** the tasking to the relevant
  desks (keyword routing + a core-desk fallback), runs them **concurrently**,
  then **synthesises** their reports into one briefing with attribution
  ("GEOINT assesses…"). `stream_taskforce` emits `plan → agent… → synthesis`
  events over SSE for a live build-up in the UI.
- **Graceful offline** — with no DeepSeek key each desk returns a clearly
  labelled, data-derived working set instead of model prose, so the harness
  stays demonstrable.

Use the **⌬ AGENT MESH** tab, or type `AGENTS <tasking>` in the console
(e.g. `AGENTS assess escalation risk in the South China Sea`).

## Tests

```bash
. .venv/bin/activate && pip install pytest
python -m pytest -q          # 43 passing, no network required
```

## Ethics & scope

This is a situational-awareness aggregator for **open, public data** — not a
covert collection tool.

- All data sources are **public and keyless** (USGS, NOAA, NASA, CelesTrak,
  CoinGecko, Stooq, GDELT, TfL).
- The webcam feature surfaces **only webcams their owners have intentionally
  published** — official **TfL** (Transport for London) public traffic cameras,
  plus a curated list of well-known public live streams. It deliberately does
  **not** scan, probe, or access unsecured/private cameras. Accessing a device
  its owner has not made public is unauthorised and unlawful; this tool provides
  no such capability.
- The only optional key is **DeepSeek** (the AI core); it is stored server-side
  only (`.jarvis_secrets.json`, chmod 600, gitignored) and never sent back to
  the browser.
- **Device Sensors** touch only the operator's **own** device, through standard
  permission-gated browser APIs, and only when the operator chooses to. Screen
  capture and microphone use the browser's own consent prompts; **screen frames
  and audio never leave the device** — only non-sensitive telemetry (hardware
  specs, screen geometry, network class, battery, input-rate counters) is sent
  to the local server for the SENTINEL agent. The input meter counts event
  *rates* only — it is not a keylogger and never captures or transmits content.
