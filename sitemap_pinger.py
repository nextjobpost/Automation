"""
sitemap_pinger.py — Google & Bing Sitemap Pinger
Part of the NextJobPost Automation Engine (D:/Automation)

Called after every successful job post to notify search engines
of new content via their official ping endpoints.
"""

import os
import asyncio
import logging
import aiohttp
from datetime import datetime
from urllib.parse import quote

# ── Config ────────────────────────────────────────────────────────────────────
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://nextjobpost.in")

SITEMAP_URL = f"{SITE_BASE_URL}/sitemap.xml"

PING_ENDPOINTS = [
    f"https://www.google.com/ping?sitemap={quote(SITEMAP_URL, safe='')}",
    f"https://www.bing.com/ping?sitemap={quote(SITEMAP_URL, safe='')}",
]

# Track last ping time to avoid spamming
_last_ping_time: float = 0
MIN_PING_INTERVAL = 300  # Minimum 5 minutes between pings


async def ping_search_engines(force: bool = False) -> dict:
    """
    Pings Google and Bing sitemap ping endpoints.
    Throttled to at most once every 5 minutes unless force=True.

    Returns dict with results for each engine.
    """
    global _last_ping_time
    import time

    now = time.time()
    if not force and (now - _last_ping_time) < MIN_PING_INTERVAL:
        remaining = int(MIN_PING_INTERVAL - (now - _last_ping_time))
        logging.info(f"[PING] ⏳ Skipping sitemap ping — throttled. Next in {remaining}s")
        return {"skipped": True, "reason": "throttled"}

    _last_ping_time = now
    results = {}
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logging.info(f"[PING] 📡 Pinging search engines at {timestamp}...")

    async with aiohttp.ClientSession() as session:
        for endpoint in PING_ENDPOINTS:
            engine = "Google" if "google.com" in endpoint else "Bing"
            try:
                async with session.get(endpoint, timeout=10) as res:
                    ok = res.status in (200, 201, 202, 204)
                    logging.info(f"[PING] {'✅' if ok else '⚠️'} {engine}: HTTP {res.status}")
                    results[engine] = {"status": res.status, "ok": ok}
            except asyncio.TimeoutError:
                logging.warning(f"[PING] ⏱️ {engine}: Request timed out")
                results[engine] = {"status": "timeout", "ok": False}
            except Exception as e:
                logging.warning(f"[PING] ❌ {engine}: {e}")
                results[engine] = {"status": "error", "ok": False, "error": str(e)}

    success_count = sum(1 for r in results.values() if r.get("ok"))
    logging.info(f"[PING] ✅ {success_count}/{len(results)} engines pinged successfully")
    return results


# Convenience alias matching the name used in bot1.py integration
async def ping_all(force: bool = False) -> dict:
    """Alias for ping_search_engines — call this from bot1.py after posting."""
    return await ping_search_engines(force=force)


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(override=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    result = asyncio.run(ping_all(force=True))
    print(f"\nPing Results: {result}")
