#!/data/data/com.termux/files/usr/bin/bash
# ──────────────────────────────────────────────────────────────────────────
#  J.A.R.V.I.S. — on-device setup for Android via Termux
#
#  Runs the full Flask backend natively on your phone, so the terminal works
#  without any external server.
#
#  1. Install Termux (from F-Droid — the Play Store build is outdated).
#  2. Copy this repo to the phone, or: pkg install git && git clone <repo>
#  3. From the repo root run:  bash android/termux-setup.sh
#  4. Open the printed URL (http://localhost:8765) in your Android browser
#     and use the ⤓ INSTALL button to add it to your home screen.
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▸ J.A.R.V.I.S. — Termux setup"

# Termux ships a rolling Python; install build deps for native wheels.
echo "▸ installing system packages (python, rust, build tools)…"
pkg update -y >/dev/null 2>&1 || true
pkg install -y python rust binutils >/dev/null 2>&1 || \
  pkg install -y python rust binutils

# Keep the CPU awake so the server isn't suspended in the background.
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock || true

echo "▸ creating virtualenv…"
python -m venv .venv
./.venv/bin/pip install --upgrade pip setuptools wheel >/dev/null

echo "▸ installing Python dependencies…"
./.venv/bin/pip install -r requirements.txt
# pytest powers the DEV agent's test gate (so it can verify changes / auto-roll-back)
./.venv/bin/pip install -q pytest || true

if [ ! -f .env ]; then
  cp .env.example .env
  echo "▸ wrote .env — add your DEEPSEEK_API_KEY to bring the AI core online."
fi

# Bind to all interfaces so you can also reach it from other devices on the LAN.
IP="$(ip route get 1 2>/dev/null | awk '{print $7; exit}' || echo localhost)"
echo
echo "▸ launching J.A.R.V.I.S."
echo "  • on this phone:   http://localhost:8765"
echo "  • on your LAN:     http://${IP}:8765"
echo
exec ./.venv/bin/python app.py
