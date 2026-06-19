"""
auto_optimize.py — Search Console Auto-Optimizer
Part of the NextJobPost Automation Engine (D:/Automation)

Scans GSC opportunities, generates optimized meta titles, descriptions, and FAQs,
and patches live database records to boost Search Engine CTR.
"""

import os
import sys
import json
import sqlite3
import asyncio
import logging
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
API_URL = os.getenv("API_URL", "https://nextjobpost-backend.onrender.com/api/jobs")
API_TOKEN = os.getenv("API_TOKEN", "")
API_KEY = os.getenv("API_KEY", "")

# Fallback token
OLD_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4ifQ.ts-o1us7bsOOJunK2dL4HNmz1ONh3tywCLj0D079k4M"
NEW_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"
if not API_TOKEN or API_TOKEN == OLD_TOKEN:
    API_TOKEN = NEW_TOKEN

# ═══════════════════════════════════════════════════════════════════════════════
# GET GSC OPPORTUNITIES FROM SQLITE
# ═══════════════════════════════════════════════════════════════════════════════

def get_high_priority_opportunities() -> list:
    """Retrieves high-impression, low-CTR opportunities that need optimization."""
    opportunities = []
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20.0)
        cur = conn.execute("""
            SELECT id, query, page, impressions, clicks, ctr, position, opportunity_type, suggestion 
            FROM seo_opportunities
            WHERE opportunity_type = 'high_impressions_low_ctr'
               OR (opportunity_type = 'technical_seo' AND query IN ('Missing Title', 'Missing Description', 'Title Length'))
            ORDER BY impressions DESC
            LIMIT 15
        """)
        rows = cur.fetchall()
        for r in rows:
            opportunities.append({
                "db_id": r[0],
                "query": r[1],
                "page": r[2],
                "impressions": r[3],
                "clicks": r[4],
                "ctr": r[5],
                "position": r[6],
                "type": r[7],
                "suggestion": r[8]
            })
        conn.close()
    except Exception as e:
        logging.warning(f"[AUTO-OPTIMIZER] SQLite query failed: {e}")
    return opportunities

# ═══════════════════════════════════════════════════════════════════════════════
# AI META REWRITING
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_job_details(slug: str) -> dict:
    """Fetches full job JSON object from backend by slug."""
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        try:
            url = f"{API_URL}/{slug}"
            async with session.get(url, headers=headers, timeout=10) as res:
                if res.status == 200:
                    data = await res.json()
                    return data.get("data")
        except Exception as e:
            logging.warning(f"[AUTO-OPTIMIZER] Could not fetch job '{slug}': {e}")
    return None

async def generate_better_metadata(job: dict, target_query: str) -> dict:
    """Uses Gemini to generate high-CTR title, description, and FAQs targeting the keyword query."""
    if not API_KEY:
        return _rule_based_improvements(job, target_query)
        
    try:
        from google import genai
        client = genai.Client(api_key=API_KEY)
        
        prompt = f"""
You are an expert search engine optimizer. We want to improve the click-through rate (CTR) of a landing page.
The target search query we want to rank higher for and get clicks from is: "{target_query}"

Current Page Details:
- Title: {job.get('title')}
- Company: {job.get('company')}
- Current Meta Title: {job.get('metaTitle', 'None')}
- Current Meta Description: {job.get('metaDescription', 'None')}
- Location: {job.get('location')}
- Vacancies: {job.get('vacancies', 'Not Mentioned')}
- Salary: {job.get('salary', 'Not Mentioned')}

Rewrite and improve the SEO tags for this page:
1. "metaTitle": Compelling title. Max 60 chars. Must target "{target_query}". Include salary or vacancies count or "Apply Online" to increase CTR.
2. "metaDescription": Compelling meta description. Max 155 chars. Explain eligibility, last date if any, and call to action.
3. "faqs": Array of exactly 5 Q&A objects. Answers under 60 words. Make them target common candidate search queries (e.g. eligibility, salary, exam date).

Return ONLY a raw JSON object (no markdown, no ```json backticks) with keys:
"metaTitle", "metaDescription", "faqs"
"""
        logging.info(f"[AUTO-OPTIMIZER] 🤖 Calling Gemini to optimize '{job.get('title')}' for query '{target_query}'...")
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
            
        data = json.loads(raw)
        if data.get("metaTitle") and data.get("metaDescription"):
            return data
    except Exception as e:
        logging.warning(f"[AUTO-OPTIMIZER] Gemini optimization failed: {e}. Falling back.")
        
    return _rule_based_improvements(job, target_query)

def _rule_based_improvements(job: dict, target_query: str) -> dict:
    """Prepares rule-based SEO meta improvements when Gemini is not present."""
    title = job.get("title", "")
    company = job.get("company", "")
    vac = job.get("vacancies", "")
    year = datetime.now().year
    
    # Generate high-CTR Title
    vac_text = f" ({vac} Vacancies)" if vac and vac != "Not Mentioned" else ""
    meta_title = f"{target_query.title()}{vac_text} - Apply Online {year}"
    if len(meta_title) > 65:
        meta_title = f"{target_query.title()} {year} | Apply Now"
    meta_title = meta_title[:65]
    
    # Generate meta description
    meta_desc = f"Apply Online for {title} at {company}. Check eligibility, salary, vacancies, and click here to submit your application."
    if len(meta_desc) > 155:
        meta_desc = meta_desc[:150] + "..."
        
    # Standard FAQs
    faqs = [
        {"q": f"How to apply for {target_query}?", "a": "Visit NextJobPost, check the official notification requirements, and click the direct apply link to submit your details online."},
        {"q": f"What is the salary for {title}?", "a": f"The salary ranges are {job.get('salary', 'as per official recruitment guidelines')}. Additional benefits may apply."},
        {"q": f"What is the eligibility for {target_query}?", "a": f"Candidates with a background in {job.get('education', 'the required field')} are eligible to apply. Check details online."}
    ]
    
    return {
        "metaTitle": meta_title,
        "metaDescription": meta_desc,
        "faqs": faqs
    }

# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTE UPDATES / REST API
# ═══════════════════════════════════════════════════════════════════════════════

async def patch_optimized_seo(job_id: str, seo_data: dict) -> bool:
    """Updates the job on the Node backend via PUT /api/jobs/:id."""
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "metaTitle": seo_data["metaTitle"],
        "metaDescription": seo_data["metaDescription"]
    }
    # If the backend schema stores FAQs directly inside the job description or structured fields
    if seo_data.get("faqs"):
        payload["faqs"] = seo_data["faqs"]
        
    async with aiohttp.ClientSession() as session:
        try:
            patch_url = f"{API_URL}/{job_id}"
            async with session.put(patch_url, json=payload, headers=headers, timeout=10) as res:
                if res.status == 200:
                    return True
        except Exception as e:
            logging.error(f"[AUTO-OPTIMIZER] Failed to patch job {job_id}: {e}")
    return False

def remove_completed_opportunity(db_id: int):
    """Removes the optimized opportunity from SQLite so it doesn't get processed again."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20.0)
        conn.execute("DELETE FROM seo_opportunities WHERE id = ?", (db_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.warning(f"[AUTO-OPTIMIZER] Failed to delete SQLite record: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# MASTER EXECUTIVE RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    logging.info("[AUTO-OPTIMIZER] ────────── Starting Search Console Auto-Optimizer ──────────")
    
    # 1. Fetch high priority CTR opportunities
    opportunities = get_high_priority_opportunities()
    logging.info(f"[AUTO-OPTIMIZER] Found {len(opportunities)} low-performing pages to optimize")
    
    optimized_count = 0
    for opp in opportunities:
        page_url = opp.get("page", "")
        # Extract slug from page URL (e.g. "https://nextjobpost.in/ssc-cgl-recruitment" -> "ssc-cgl-recruitment")
        slug = page_url.replace("https://nextjobpost.in", "").strip("/")
        
        if not slug or "/" in slug:
            # Skip homepage or programmatic combo pages for now
            continue
            
        # 2. Fetch current job record
        job = await fetch_job_details(slug)
        if not job or not job.get("_id"):
            logging.info(f"[AUTO-OPTIMIZER] Job '{slug}' not found on backend. Skipping.")
            continue
            
        # 3. Generate improved tags targeting the query
        better_seo = await generate_better_metadata(job, opp["query"])
        
        # 4. Patch backend database
        success = await patch_optimized_seo(job["_id"], better_seo)
        if success:
            logging.info(f"[AUTO-OPTIMIZER] ✅ Optimized page: /{slug} | Target keyword: '{opp['query']}'")
            logging.info(f"                 New Title: '{better_seo['metaTitle']}'")
            
            # 5. Clean up completed tasks from database
            remove_completed_opportunity(opp["db_id"])
            optimized_count += 1
            await asyncio.sleep(1.5)  # Throttle API calls
            
    logging.info(f"[AUTO-OPTIMIZER] Completed optimization of {optimized_count} pages.")
    logging.info("[AUTO-OPTIMIZER] ─────────────────────────────────────────────────────────────")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    
    asyncio.run(main())
