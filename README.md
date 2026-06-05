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
templates/index.html    terminal layout (+ PWA meta + SW registration)
static/css/terminal.css Bloomberg-style phosphor UI (+ mobile/PWA responsive)
static/js/terminal.js   client controller (feeds, console, SSE, commands, install)
static/js/sw.js         service worker (offline shell, network-first API)
static/manifest.webmanifest  PWA manifest (icons, shortcuts)
static/icons/*.png      generated app icons (any + maskable)
tools/make_icons.py     dependency-free PNG icon generator
android/termux-setup.sh on-device backend setup for Android/Termux
tests/test_jarvis.py    network-free unit + API + PWA tests
```

## Tests

```bash
. .venv/bin/activate && pip install pytest
python -m pytest -q          # 16 passing, no network required
```

## Notes

All surveillance sources are **public, keyless OSINT** feeds. This is a
situational-awareness aggregator for open data — not a covert collection tool.
