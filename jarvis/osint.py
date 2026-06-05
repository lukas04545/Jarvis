"""Email-exposure OSINT — account discovery (holehe) + breach directories.

Authorised / defensive use only
===============================
This surfaces an email address's public *exposure* footprint, the way tools like
**holehe** (https://github.com/megadose/holehe) and **Have I Been Pwned** do:

* account discovery — which sites an address is *registered* on (holehe queries
  password-reset / signup endpoints; it returns booleans, never credentials);
* breach directories — which known breaches an address appears in, as
  **metadata only** (breach name, domain, date, record count, data-class
  categories). Plaintext passwords and leaked record contents are NEVER
  returned.

Guardrails: one address per request, an explicit authorisation flag is required,
and a simple rate limit caps lookups. Intended for checking your *own* exposure
or authorised investigations — not mass collection or targeting third parties.

Network notes: live `holehe` runs are opt-in (`JARVIS_ENABLE_HOLEHE=1`) and
bounded; the HIBP breach API needs a key (set HIBP_API_KEY / paste in Settings).
Without these, a clearly-flagged SIMULATED footprint is returned so the feature
stays demonstrable — exactly like the rest of the terminal.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from typing import Dict, List

import requests

from config import config
from jarvis import runtime

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HIBP_URL = "https://haveibeenpwned.com/api/v3/breachedaccount/{}"

# Sites holehe-style account discovery covers (subset, for the structured view).
SITES = [
    "github", "gitlab", "twitter/x", "instagram", "spotify", "adobe", "amazon",
    "pinterest", "wordpress", "discord", "imgur", "lastpass", "patreon",
    "tumblr", "venmo", "duolingo", "ebay", "rambler",
]

# Minimal rate limiter (per process) to discourage abuse / mass enumeration.
_LOCK = threading.Lock()
_HITS: List[float] = []
_MAX_PER_MIN = 8


def _rate_ok() -> bool:
    now = time.time()
    with _LOCK:
        while _HITS and now - _HITS[0] > 60:
            _HITS.pop(0)
        if len(_HITS) >= _MAX_PER_MIN:
            return False
        _HITS.append(now)
        return True


def _simulated_accounts(email: str) -> List[Dict]:
    # Deterministic pseudo-result from the address hash so the demo is stable.
    h = hashlib.sha256(email.lower().encode()).digest()
    out = []
    for i, site in enumerate(SITES):
        exists = bool(h[i % len(h)] & (1 << (i % 8)))
        out.append({"site": site, "exists": exists, "rateLimit": False})
    return out


def _simulated_breaches(email: str) -> List[Dict]:
    h = hashlib.sha256(("b" + email.lower()).encode()).digest()
    pool = [
        {"name": "Collection1", "domain": "", "date": "2019-01", "pwnCount": 772904991,
         "dataClasses": ["Email addresses", "Passwords"]},
        {"name": "LinkedIn", "domain": "linkedin.com", "date": "2016-05", "pwnCount": 164611595,
         "dataClasses": ["Email addresses", "Passwords"]},
        {"name": "Adobe", "domain": "adobe.com", "date": "2013-10", "pwnCount": 152445165,
         "dataClasses": ["Email addresses", "Password hints", "Passwords", "Usernames"]},
        {"name": "Dropbox", "domain": "dropbox.com", "date": "2012-07", "pwnCount": 68648009,
         "dataClasses": ["Email addresses", "Passwords"]},
    ]
    return [b for i, b in enumerate(pool) if h[i] & 1]


def _hibp_breaches(email: str, key: str) -> List[Dict]:
    resp = requests.get(
        HIBP_URL.format(requests.utils.quote(email)),
        headers={"hibp-api-key": key, "user-agent": "JARVIS-Terminal/1.0"},
        params={"truncateResponse": "false"},
        timeout=config.HTTP_TIMEOUT,
    )
    if resp.status_code == 404:
        return []  # no breaches found
    resp.raise_for_status()
    out = []
    for b in resp.json():
        out.append({
            "name": b.get("Name") or b.get("Title", ""),
            "domain": b.get("Domain", ""),
            "date": (b.get("BreachDate") or "")[:7],
            "pwnCount": b.get("PwnCount", 0),
            # Data-class *categories* only — never the actual leaked values.
            "dataClasses": (b.get("DataClasses") or [])[:8],
        })
    return out


def _run_holehe(email: str):
    """Best-effort live holehe run (opt-in + bounded). Returns list or None."""
    if os.environ.get("JARVIS_ENABLE_HOLEHE") != "1":
        return None
    result = {"data": None}

    def worker():
        try:
            import trio
            import httpx
            from holehe.core import import_submodules, get_functions

            modules = import_submodules("holehe.modules")
            funcs = get_functions(modules)[:25]  # bound fan-out

            async def main():
                out: List[Dict] = []
                async with httpx.AsyncClient() as client:
                    for _, fn in funcs:
                        try:
                            await fn(email, client, out)
                        except Exception:
                            continue
                return out

            raw = trio.run(main)
            result["data"] = [{"site": r.get("name", "?"), "exists": bool(r.get("exists")),
                               "rateLimit": bool(r.get("rateLimit"))} for r in raw]
        except Exception:
            result["data"] = None

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=20)
    return result["data"]


def check_email(email: str, authorized: bool = False) -> Dict:
    """Return the exposure footprint for one email (authorised use only)."""
    email = (email or "").strip()
    if not EMAIL_RE.match(email):
        return {"error": "invalid email address"}
    if not authorized:
        return {"error": "authorization required",
                "notice": "Confirm you are authorised to check this address (e.g. your own)."}
    if not _rate_ok():
        return {"error": "rate limit — slow down (max 8 lookups/min)"}

    # ── accounts (holehe) ─────────────────────────────────────────────────
    accounts = _run_holehe(email)
    accounts_sim = accounts is None
    if accounts_sim:
        accounts = _simulated_accounts(email)

    # ── breaches (HIBP metadata) ──────────────────────────────────────────
    hibp = runtime.hibp_key()
    breaches_sim = True
    breaches: List[Dict] = []
    if hibp:
        try:
            breaches = _hibp_breaches(email, hibp)
            breaches_sim = False
        except Exception:
            breaches = _simulated_breaches(email)
    else:
        breaches = _simulated_breaches(email)

    found = [a for a in accounts if a.get("exists")]
    return {
        "email": email,
        "accounts": accounts,
        "accounts_found": len(found),
        "accounts_checked": len(accounts),
        "breaches": breaches,
        "breach_count": len(breaches),
        "simulated": accounts_sim or breaches_sim,
        "sources": {"accounts": "holehe" if not accounts_sim else "simulated",
                    "breaches": "hibp" if not breaches_sim else "simulated"},
        "notice": "Exposure metadata only — no passwords or leaked record contents are retrieved. "
                  "For authorised / self-exposure checks.",
    }
