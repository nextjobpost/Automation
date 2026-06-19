"""
refresh_engine.py — Automatic Content Refresh Engine
Part of the NextJobPost Automation Engine (D:/Automation)

Keeps the job portal content fresh by running every 7 days:
  - Recalculates live active job counts for all 732 programmatic combinations.
  - Updates the programmatic landing pages database (customProgrammaticContent.json) with fresh stats and timestamps.
  - Refreshes FAQs and meta fields of older job posts via backend PATCH requests.
  - Re-injects internal links using BeautifulSoup to point to newer jobs.
"""

import os
import sys
import json
import asyncio
import logging
import aiohttp
import re
from datetime import datetime, timedelta

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
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://nextjobpost.in")
API_URL = os.getenv("API_URL", "https://nextjobpost-backend.onrender.com/api/jobs")
API_TOKEN = os.getenv("API_TOKEN", "")
CLIENT_JSON_PATH = "d:/job/client/src/utils/customProgrammaticContent.json"

# Import internal linking logic from seo_engine
try:
    import seo_engine
    SEO_ENGINE_LOADED = True
except ImportError:
    SEO_ENGINE_LOADED = False
    logging.warning("[REFRESH] Could not import seo_engine.py. Manual link injection will be disabled.")

# Fallback token
OLD_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4ifQ.ts-o1us7bsOOJunK2dL4HNmz1ONh3tywCLj0D079k4M"
NEW_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"
if not API_TOKEN or API_TOKEN == OLD_TOKEN:
    API_TOKEN = NEW_TOKEN

# ═══════════════════════════════════════════════════════════════════════════════
# LIVE JOB STATS RE-CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_all_active_jobs() -> list:
    """Fetches all active jobs with fields necessary to compute counts per state/qualification."""
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    # Fetch a large list to get accurate counts
    endpoint = f"{API_URL}?limit=1000&status=active&fields=title,location,education,postType,isGovernment"
    
    async with aiohttp.ClientSession() as session:
        try:
            logging.info("[REFRESH] Fetching active jobs database for stats compilation...")
            async with session.get(endpoint, headers=headers, timeout=15) as res:
                if res.status == 200:
                    data = await res.json()
                    return data.get("data") or data.get("jobs") or []
        except Exception as e:
            logging.error(f"[REFRESH] Failed to fetch active jobs: {e}")
            
    return []

def calculate_matches(jobs: list, state: str = None, qual: str = None, cat: str = None) -> int:
    """Counts how many active jobs match a given state, qualification, or category criteria."""
    count = 0
    state_pat = re.compile(rf"\b{state.replace('-', ' ')}\b", re.I) if state else None
    
    # Map qualifications to typical abbreviations
    qual_terms = []
    if qual:
        q_clean = qual.lower()
        if "10th" in q_clean or "matric" in q_clean:
            qual_terms = ["10th", "matric", "high school", "ssc"]
        elif "12th" in q_clean or "inter" in q_clean:
            qual_terms = ["12th", "intermediate", "hsc", "10+2"]
        elif "graduate" in q_clean:
            qual_terms = ["graduate", "degree", "b.a", "b.sc", "b.com", "btech", "b.tech", "bca"]
        elif "post-graduate" in q_clean:
            qual_terms = ["post graduate", "master", "m.a", "m.sc", "m.com", "mtech", "m.tech", "mca", "phd"]
        elif "engineering" in q_clean:
            qual_terms = ["engineering", "b.e", "btech", "b.tech", "diploma in engineering"]
        elif "diploma" in q_clean:
            qual_terms = ["diploma"]
        elif "iti" in q_clean:
            qual_terms = ["iti", "industrial training"]
        else:
            qual_terms = [q_clean]
            
    cat_terms = []
    if cat:
        c_clean = cat.lower()
        if c_clean == "bank":
            cat_terms = ["bank", "banking", "ibps", "sbi", "rbi"]
        elif c_clean == "defence":
            cat_terms = ["defence", "army", "navy", "air force", "nda", "cds", "bsf", "crpf"]
        elif c_clean == "police":
            cat_terms = ["police", "constable", "si", "sub inspector"]
        else:
            cat_terms = [c_clean]

    for job in jobs:
        title = String = job.get("title", "").lower()
        loc = String = job.get("location", "").lower()
        edu = String = job.get("education", "").lower()
        pt = String = job.get("postType", "").lower()
        
        # 1. State Filter
        if state_pat:
            if not (state_pat.search(loc) or state_pat.search(title)):
                continue
                
        # 2. Qualification Filter
        if qual_terms:
            match_qual = False
            for term in qual_terms:
                if term in edu or term in title:
                    match_qual = True
                    break
            if not match_qual:
                continue
                
        # 3. Category Filter
        if cat_terms:
            match_cat = False
            for term in cat_terms:
                if term in title or term in pt:
                    match_cat = True
                    break
            if not match_cat:
                continue
                
        count += 1
        
    return count

async def refresh_programmatic_seo_database():
    """Reads customProgrammaticContent.json, updates counts & timestamps, and writes it back."""
    if not os.path.exists(CLIENT_JSON_PATH):
        logging.warning(f"[REFRESH] Programmatic JSON not found at: {CLIENT_JSON_PATH}. Skipping.")
        return
        
    try:
        with open(CLIENT_JSON_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
            
        active_jobs = await fetch_all_active_jobs()
        if not active_jobs:
            logging.warning("[REFRESH] No active jobs found. Skipping count recalculations.")
            return
            
        logging.info(f"[REFRESH] Recalculating job stats for {len(db)} pages...")
        year = datetime.now().year
        
        for slug, data in db.items():
            # Parse parameters from slug structure
            # e.g., "10th-pass-jobs-in-gujarat" or "gujarat-govt-jobs"
            state = None
            qual = None
            cat = None
            
            parts = slug.split("-")
            
            if "-jobs-in-" in slug:
                # qual-jobs-in-state
                idx = slug.find("-jobs-in-")
                qual = slug[:idx]
                state = slug[idx + 9:]
            elif "-govt-jobs" in slug:
                # state-govt-jobs
                state = slug.replace("-govt-jobs", "")
            elif slug.endswith("-jobs"):
                # qual-jobs
                qual = slug.replace("-jobs", "")
            else:
                # Check for category combos, e.g. "ssc-jobs-in-gujarat"
                for c in ['ssc', 'railway', 'bank', 'upsc', 'defence', 'psu', 'police']:
                    if slug.startswith(f"{c}-jobs-in-"):
                        cat = c
                        state = slug.replace(f"{c}-jobs-in-", "")
                        break
            
            # Recalculate matches count
            live_count = calculate_matches(active_jobs, state=state, qual=qual, cat=cat)
            
            # Update intro / description dynamically to display live vacancies
            # We strip any previous live count sentence and append a fresh one
            intro = data.get("intro", "")
            intro = re.sub(r"Currently, there (?:is|are) \d+ active job (?:opening|openings) matching this search\.?", "", intro).strip()
            
            count_sentence = f"Currently, there {'is 1 active job opening' if live_count == 1 else f'are {live_count} active job openings'} matching this search."
            data["intro"] = f"{count_sentence} {intro}"
            
            # Update year in heading and meta tags
            if "h1" in data:
                data["h1"] = re.sub(r"\b20\d{2}\b", str(year), data["h1"])
            if "metaTitle" in data:
                data["metaTitle"] = re.sub(r"\b20\d{2}\b", str(year), data["metaTitle"])
            if "metaDescription" in data:
                data["metaDescription"] = re.sub(r"\b20\d{2}\b", str(year), data["metaDescription"])
                
        # Save back to client file
        with open(CLIENT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            
        logging.info(f"[REFRESH] Saved fresh stats to {CLIENT_JSON_PATH}")
    except Exception as e:
        logging.error(f"[REFRESH] Error refreshing programmatic SEO db: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# OLD JOB POSTS REFRESHER
# ═══════════════════════════════════════════════════════════════════════════════

async def refresh_older_job_posts():
    """Fetches older active jobs (7+ days old) and refreshes their content & links."""
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    cutoff_date = (datetime.now() - timedelta(days=7)).isoformat()
    
    # Query API for older active jobs
    endpoint = f"{API_URL}?limit=20&status=active&sort=createdAt&fields=_id,title,company,location,jobDescription,education,vacancies,salary,postType,isGovernment,lastDate,createdAt"
    
    async with aiohttp.ClientSession() as session:
        try:
            logging.info("[REFRESH] Checking for older active jobs to update FAQs & internal links...")
            async with session.get(endpoint, headers=headers, timeout=15) as res:
                if res.status != 200:
                    return
                data = await res.json()
                jobs = data.get("data") or data.get("jobs") or []
                
                logging.info(f"[REFRESH] Found {len(jobs)} candidates for refresh.")
                for job in jobs:
                    job_id = job.get("_id")
                    if not job_id:
                        continue
                        
                    # 1. Update internal links
                    updated_desc = job.get("jobDescription", "")
                    if SEO_ENGINE_LOADED:
                        # Re-run BeautifulSoup link injector to add links to recently posted jobs
                        updated_desc = await seo_engine.inject_internal_links(updated_desc, session=session)
                        
                    # 2. Update FAQs or text blocks (Simulated update or minor touch)
                    # We send a PATCH request to let the search crawler know the page was updated
                    payload = {
                        "jobDescription": updated_desc,
                        "highlightText": job.get("highlightText") or f"Apply for {job.get('title')} - online application is active today."
                    }
                    
                    patch_url = f"{API_URL}/{job_id}"
                    async with session.put(patch_url, json=payload, headers=headers, timeout=10) as patch_res:
                        if patch_res.status == 200:
                            logging.info(f"[REFRESH] Updated content for job: {job.get('title')}")
                        else:
                            logging.warning(f"[REFRESH] Failed to update job {job_id}: {patch_res.status}")
        except Exception as e:
            logging.error(f"[REFRESH] Error refreshing older jobs: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN REFRESH ENGINE RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    logging.info("[REFRESH] ────────── Starting Automatic Content Refresh Engine ──────────")
    
    # 1. Refresh live counts on programmatic SEO pages
    await refresh_programmatic_seo_database()
    
    # 2. Refresh links and content of older job pages
    await refresh_older_job_posts()
    
    logging.info("[REFRESH] ───────────────────────────────────────────────────────────────")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    
    asyncio.run(main())
