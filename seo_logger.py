"""
seo_logger.py — Shared Automation Run Logger
Part of the NextJobPost Automation Engine (D:/Automation)

Called by bot1.py after each scheduled SEO task completes to post a run
result to the Node.js backend so the AdminDashboard can show a daily report.
"""

import os
import time
import logging
import asyncio
import aiohttp
from datetime import datetime

# Force UTF-8 encoding
import sys
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass

# ── Config ────────────────────────────────────────────────────────────────────
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://nextjobpost.in")

OLD_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4ifQ.ts-o1us7bsOOJunK2dL4HNmz1ONh3tywCLj0D079k4M"
NEW_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"

def _get_token():
    token = os.getenv("API_TOKEN", "")
    if not token or token == OLD_TOKEN:
        return NEW_TOKEN
    return token

# ── Valid task names (must match SeoAutomationLog schema enum) ────────────────
TASK_HEALTH_CHECKER   = "health_checker"
TASK_GSC_SYNC         = "gsc_keyword_sync"
TASK_INDEX_TRACKER    = "index_tracker"
TASK_AUTO_OPTIMIZER   = "auto_optimizer"
TASK_CONTENT_REFRESH  = "content_refresh"
TASK_GAP_FINDER       = "keyword_gap_finder"

# ── Logger ────────────────────────────────────────────────────────────────────
async def log_task_result(
    task_name: str,
    status: str,           # "success" | "failed" | "skipped"
    message: str = "",
    details: dict = None,
    duration_ms: int = 0
):
    """
    Posts a single SEO automation task result to the Node.js backend.
    Silently fails if backend is unavailable so it never breaks the main bot.
    """
    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json"
    }
    payload = {
        "taskName":   task_name,
        "status":     status,
        "message":    message,
        "details":    details or {},
        "durationMs": duration_ms,
        "ranAt":      datetime.utcnow().isoformat()
    }
    url = f"{SITE_BASE_URL}/api/seo/automation-logs"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=10) as res:
                if res.status == 200:
                    logging.info(f"[SEO-LOGGER] Logged '{task_name}' -> {status}")
                else:
                    body = await res.text()
                    logging.warning(f"[SEO-LOGGER] Log post failed ({res.status}): {body[:120]}")
    except Exception as e:
        # Never let logging crash the main bot
        logging.warning(f"[SEO-LOGGER] Could not post log for '{task_name}': {e}")


class TaskTimer:
    """Context-manager style timer for measuring task duration."""
    def __init__(self):
        self._start = None

    def start(self):
        self._start = time.monotonic()

    def elapsed_ms(self) -> int:
        if self._start is None:
            return 0
        return int((time.monotonic() - self._start) * 1000)
