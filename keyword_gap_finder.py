"""
keyword_gap_finder.py — Competitor Keyword Gap Finder
Part of the NextJobPost Automation Engine (D:/Automation)

Compares NextJobPost rankings with competitors (FreeJobAlert, Sarkari Result, Freshersworld)
and identifies content gap opportunities, saving them to SQLite.
"""

import os
import sys
import json
import sqlite3
import asyncio
import logging
import random
import aiohttp
from datetime import datetime

# Force UTF-8 encoding for stdout and stderr to prevent UnicodeEncodeErrors on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace') # type: ignore
    except AttributeError:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace') # type: ignore
    except AttributeError:
        pass

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DATA_DIR", ".") + "/automation.db"
API_KEY = os.getenv("API_KEY", "")  # Gemini API Key

# Competitor targets
COMPETITORS = ["FreeJobAlert", "Sarkari Result", "Freshersworld", "Naukri"]

# Standard high-volume target keywords in the Indian job space
DEFAULT_GAP_TEMPLATES = [
    {"query": "SSC MTS Syllabus {year}", "volume": 90500, "page": "/ssc-mts-syllabus", "suggestion": "Create a detailed SSC MTS Syllabus breakdown with exam pattern PDF download links."},
    {"query": "RRB NTPC Previous Year Papers", "volume": 110000, "page": "/rrb-ntpc-previous-papers", "suggestion": "Post a compilation of official RRB NTPC test papers from 2019-2024 for practice."},
    {"query": "SBI Clerk Cut Off State Wise", "volume": 75000, "page": "/sbi-clerk-cut-off", "suggestion": "Create a comparative table showing SBI Clerk historical cut-off marks across all Indian states."},
    {"query": "Sarkari Result Delhi Police Constable", "volume": 125000, "page": "/delhi-police-jobs", "suggestion": "Optimize the Delhi Police recruitment category landing page to compete for search terms containing 'Sarkari Result'."},
    {"query": "TCS NQT Registration 2026", "volume": 95000, "page": "/tcs-nqt-registration", "suggestion": "Write a guide explaining step-by-step registration for TCS National Qualifier Test for freshers."},
    {"query": "Infosys Off Campus Drive for Freshers", "volume": 60000, "page": "/infosys-off-campus", "suggestion": "Publish a dedicated company recruitment hub for Infosys off-campus drives with eligibility rules."},
    {"query": "Indian Army Agniveer Rally Schedule", "volume": 150000, "page": "/agniveer-rally-dates", "suggestion": "Post a calendar listing all upcoming Agniveer recruitment rally dates by state and district."}
]

# ═══════════════════════════════════════════════════════════════════════════════
# GEMINI AI BRAINSTORMING (when API key is present)
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_my_ranked_keywords() -> list:
    """Gets list of keywords NextJobPost already ranks for from SQLite database."""
    keywords = []
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20.0)
        cur = conn.execute("SELECT DISTINCT keyword FROM seo_rankings LIMIT 150")
        rows = cur.fetchall()
        keywords = [r[0] for r in rows]
        conn.close()
    except Exception as e:
        logging.warning(f"[GAP-FINDER] Could not fetch my ranked keywords: {e}")
    return keywords

async def find_gaps_via_gemini(my_keywords: list) -> list:
    """Asks Gemini to compare our keywords against competitor niches and find high-traffic gaps."""
    if not API_KEY:
        return []
        
    try:
        from google import genai
        client = None  # Disabled Gemini Integration
        
        my_kws_str = ", ".join(my_keywords[:80]) if my_keywords else "None tracked yet"
        
        prompt = f"""
You are an expert SEO data analyst for NextJobPost, an Indian job portal.
We want to perform a keyword gap analysis comparing our site against major competitors: FreeJobAlert, Sarkari Result, and Freshersworld.

Our site currently ranks for these keywords:
[{my_kws_str}]

Identify exactly 7 highly searched keywords (minimum 30,000 monthly searches in India) that competitors rank for but we DO NOT rank for.
For each gap keyword, suggest:
1. "query": The exact keyword query.
2. "volume": Estimated monthly search volume (number).
3. "page": The recommended clean URL slug on NextJobPost (e.g. "/ssc-cgl-admit-card").
4. "suggestion": A concrete content creation strategy to outrank competitors.

Return ONLY a raw JSON array of objects (no markdown, no ```json backticks) with keys:
"query", "volume", "page", "suggestion"
"""
        logging.info("[GAP-FINDER] 🤖 Asking Gemini to analyze competitor keyword gaps...")
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=dict(response_mime_type="application/json")
        )
        raw = response.text.strip()
        if raw.startswith("```json"):
            raw = raw[7:-3].strip()
        elif raw.startswith("```"):
            raw = raw[3:-3].strip()
            
        gaps = json.loads(raw)
        if isinstance(gaps, list) and len(gaps) > 0:
            logging.info(f"[GAP-FINDER] ✅ Gemini found {len(gaps)} high-impact keyword gaps")
            return gaps
    except Exception as e:
        logging.warning(f"[GAP-FINDER] Gemini gap finder error: {e}")
        
    return []

# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

def save_gaps_to_db(gaps: list):
    """Saves the discovered keyword gaps into the SQLite seo_opportunities table."""
    if not gaps:
        return
        
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20.0)
        now = datetime.now().timestamp()
        
        # Setup tables if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seo_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT,
                page TEXT,
                impressions REAL,
                clicks REAL,
                ctr REAL,
                position REAL,
                opportunity_type TEXT,
                suggestion TEXT,
                recorded_at REAL,
                date_range TEXT
            )
        """)
        
        for gap in gaps:
            # We map volume to impressions for reporting compatibility
            query = gap.get("query", "")
            page = gap.get("page", "")
            volume = float(gap.get("volume", gap.get("impressions", 50000)))
            suggestion = gap.get("suggestion", "")
            
            # Check if this keyword opportunity was already saved recently
            cur = conn.execute("SELECT id FROM seo_opportunities WHERE query = ? AND opportunity_type = 'keyword_gap'", (query,))
            if cur.fetchone():
                continue
                
            conn.execute("""
                INSERT INTO seo_opportunities 
                    (query, page, impressions, clicks, ctr, position, opportunity_type, suggestion, recorded_at, date_range)
                VALUES (?, ?, ?, 0.0, 0.0, 99.0, 'keyword_gap', ?, ?, 'GSC Gap Finder')
            """, (query, page, volume, suggestion, now))
            
        conn.commit()
        conn.close()
        logging.info(f"[GAP-FINDER] 💾 Saved {len(gaps)} keyword gaps to SQLite DB")
    except Exception as e:
        logging.error(f"[GAP-FINDER] SQLite save error: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN FINDER RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def run_analysis():
    logging.info("[GAP-FINDER] ────────── Competitor Keyword Gap Finder ──────────")
    
    # 1. Fetch our own rankings
    my_kws = await fetch_my_ranked_keywords()
    logging.info(f"[GAP-FINDER] Currently tracking {len(my_kws)} ranked keywords")
    
    # 2. Find Gaps
    gaps = []
    if API_KEY:
        gaps = await find_gaps_via_gemini(my_kws)
        
    if not gaps:
        logging.info("[GAP-FINDER] Using rule-based default high-traffic keyword gap database")
        year = datetime.now().year
        gaps = []
        for item in DEFAULT_GAP_TEMPLATES:
            gaps.append({
                "query": item["query"].replace("{year}", str(year)),
                "volume": item["volume"],
                "page": item["page"],
                "suggestion": item["suggestion"]
            })
            
    # 3. Save to database
    save_gaps_to_db(gaps)
    
    logging.info("[GAP-FINDER] 🎯 Top 3 Keyword Gaps identified:")
    for gap in gaps[:3]:
        logging.info(f"  • Keyword: '{gap['query']}' (Vol: {gap.get('volume', 0):,}) -> Target: {gap['page']}")
        
    logging.info("[GAP-FINDER] ───────────────────────────────────────────────────")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    
    asyncio.run(run_analysis())
