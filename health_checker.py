"""
health_checker.py — SEO Health Checker
Part of the NextJobPost Automation Engine (D:/Automation)

Runs every 30 minutes (called from bot1.py scheduler_task):
  - Checks sitemap.xml is accessible & valid
  - Checks robots.txt is accessible
  - Checks 5 random live job pages for meta title/description presence
  - Finds jobs missing metaTitle and logs them for batch SEO fix
  - Reports total issues to scraper.log
"""

import os
import re
import json
import asyncio
import logging
import aiohttp
import random
from datetime import datetime

import sys
from dotenv import load_dotenv

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

load_dotenv(override=True)

# ── Config ────────────────────────────────────────────────────────────────────
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://nextjobpost.in")
API_URL = os.getenv("API_URL", "https://nextjobpost-backend.onrender.com/api/jobs")
API_TOKEN = os.getenv("API_TOKEN", "")

REQUEST_TIMEOUT = 15  # seconds


# ═══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

async def check_sitemap(session: aiohttp.ClientSession) -> dict:
    """Checks sitemap.xml is accessible and looks like XML."""
    url = f"{SITE_BASE_URL}/sitemap.xml"
    try:
        async with session.get(url, timeout=REQUEST_TIMEOUT) as res:
            body = await res.text()
            is_xml = "<urlset" in body or "<sitemapindex" in body
            url_count = body.count("<url>")
            status = "✅ OK" if res.status == 200 and is_xml else f"❌ FAIL (status={res.status}, xml={is_xml})"
            return {"check": "sitemap", "status": res.status, "ok": res.status == 200 and is_xml, "urls": url_count, "result": status}
    except Exception as e:
        return {"check": "sitemap", "ok": False, "result": f"❌ ERROR: {e}"}


async def check_robots_txt(session: aiohttp.ClientSession) -> dict:
    """Checks robots.txt is accessible."""
    url = f"{SITE_BASE_URL}/robots.txt"
    try:
        async with session.get(url, timeout=REQUEST_TIMEOUT) as res:
            body = await res.text()
            has_sitemap = "sitemap" in body.lower()
            has_useragent = "user-agent" in body.lower()
            ok = res.status == 200 and has_useragent
            result = "✅ OK" if ok else f"❌ FAIL (status={res.status}, sitemap_ref={has_sitemap})"
            return {"check": "robots.txt", "ok": ok, "has_sitemap_ref": has_sitemap, "result": result}
    except Exception as e:
        return {"check": "robots.txt", "ok": False, "result": f"❌ ERROR: {e}"}


async def check_sitemap_sub(session: aiohttp.ClientSession, name: str) -> dict:
    """Checks a specific sub-sitemap is accessible."""
    url = f"{SITE_BASE_URL}/sitemap-{name}.xml"
    try:
        async with session.get(url, timeout=REQUEST_TIMEOUT) as res:
            body = await res.text()
            url_count = body.count("<url>")
            ok = res.status == 200 and "<urlset" in body
            return {"check": f"sitemap-{name}", "ok": ok, "urls": url_count, "result": "✅ OK" if ok else f"❌ FAIL ({res.status})"}
    except Exception as e:
        return {"check": f"sitemap-{name}", "ok": False, "result": f"❌ ERROR: {e}"}


async def check_job_pages(session: aiohttp.ClientSession, sample_size: int = 5) -> dict:
    """Fetches a few job slugs from API and checks their pages for meta tags."""
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    try:
        async with session.get(f"{API_URL}?limit=50&sort=-createdAt", headers=headers, timeout=REQUEST_TIMEOUT) as res:
            if res.status != 200:
                return {"check": "job_pages", "ok": False, "result": f"❌ API returned {res.status}"}
            data = await res.json()
            jobs = data.get("data", [])
            if not jobs:
                return {"check": "job_pages", "ok": True, "result": "⚠️ No jobs found in API"}
    except Exception as e:
        return {"check": "job_pages", "ok": False, "result": f"❌ API Error: {e}"}

    # Pick random sample
    sample = random.sample(jobs, min(sample_size, len(jobs)))
    pages_checked = 0
    pages_ok = 0
    pages_missing_meta = []

    for job in sample:
        slug = job.get("slug")
        if not slug:
            continue
        page_url = f"{SITE_BASE_URL}/{slug}"
        try:
            async with session.get(page_url, timeout=REQUEST_TIMEOUT) as pres:
                body = await pres.text()
                has_title = bool(re.search(r'<title[^>]*>[^<]{5,}</title>', body, re.IGNORECASE))
                has_meta_desc = bool(re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'][^"\']{10,}', body, re.IGNORECASE))
                has_og_title = "og:title" in body.lower()
                pages_checked += 1
                if has_title and has_meta_desc:
                    pages_ok += 1
                else:
                    pages_missing_meta.append({"slug": slug, "url": page_url, "has_title": has_title, "has_meta_desc": has_meta_desc, "has_og": has_og_title})
        except Exception as e:
            logging.warning(f"[HEALTH] Could not check page {page_url}: {e}")

    all_ok = len(pages_missing_meta) == 0
    result = f"✅ {pages_ok}/{pages_checked} pages have meta tags" if all_ok else f"⚠️ {len(pages_missing_meta)}/{pages_checked} pages MISSING meta tags"
    return {"check": "job_pages", "ok": all_ok, "checked": pages_checked, "ok_count": pages_ok, "missing_meta": pages_missing_meta, "result": result}


async def find_jobs_missing_seo(session: aiohttp.ClientSession, limit: int = 20) -> list:
    """
    Finds jobs that have no metaTitle set.
    Returns list of job dicts that need SEO generation.
    """
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    missing = []
    try:
        async with session.get(f"{API_URL}?limit={limit}&sort=-createdAt&fields=_id,title,slug,metaTitle,metaDescription,company,location,salary,education,vacancies,lastDate,postType,isGovernment,jobDescription", headers=headers, timeout=REQUEST_TIMEOUT) as res:
            if res.status != 200:
                return []
            data = await res.json()
            jobs = data.get("data", [])
            for job in jobs:
                if not job.get("metaTitle") or len(str(job.get("metaTitle", ""))) < 10:
                    missing.append(job)
    except Exception as e:
        logging.warning(f"[HEALTH] Could not check for jobs missing SEO: {e}")

    if missing:
        logging.info(f"[HEALTH] 🔍 Found {len(missing)} jobs missing SEO metadata")
    return missing


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN HEALTH CHECK RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def run_health_check():
    """
    Master health check function.
    Runs all checks and logs a summary report.
    Called every 30 minutes from bot1.py scheduler_task.
    """
    logging.info("[HEALTH] ───────────── SEO Health Check Starting ─────────────")
    start_time = datetime.now()

    results = []
    async with aiohttp.ClientSession() as session:
        # Run checks concurrently
        checks = await asyncio.gather(
            check_sitemap(session),
            check_robots_txt(session),
            check_sitemap_sub(session, "jobs"),
            check_sitemap_sub(session, "results"),
            check_sitemap_sub(session, "admitcards"),
            check_sitemap_sub(session, "pages"),
            check_job_pages(session, sample_size=5),
            return_exceptions=True,
        )
        for check in checks:
            if isinstance(check, Exception):
                results.append({"ok": False, "result": f"❌ Exception: {check}"})
            else:
                results.append(check)

        # Find & log jobs missing SEO metadata
        missing_seo = await find_jobs_missing_seo(session)

    # ── Summary ───────────────────────────────────────────────────────────────
    total = len(results)
    passed = sum(1 for r in results if r.get("ok", False))
    failed = total - passed
    elapsed = (datetime.now() - start_time).total_seconds()

    logging.info(f"[HEALTH] ─── Results: {passed}/{total} checks passed ({elapsed:.1f}s) ───")
    for r in results:
        logging.info(f"[HEALTH]   • {r.get('check', 'unknown')}: {r.get('result', '')}")

    if missing_seo:
        slugs = [j.get("slug", j.get("_id", "?")) for j in missing_seo[:5]]
        logging.warning(f"[HEALTH] ⚠️  {len(missing_seo)} jobs need SEO generation: {slugs}...")

        # Auto-trigger SEO generation for jobs missing metadata
        try:
            from seo_engine import run_seo_pipeline, patch_seo_metadata, generate_seo_for_job
            async with aiohttp.ClientSession() as fix_session:
                for job in missing_seo[:5]:  # Process at most 5 per health check cycle
                    job_id = str(job.get("_id", ""))
                    slug = job.get("slug", "")
                    if job_id and slug:
                        seo_data = await generate_seo_for_job(job)
                        await patch_seo_metadata(job_id, seo_data, session=fix_session)
                        logging.info(f"[HEALTH] ✅ Auto-fixed SEO for: {job.get('title', slug)}")
                        await asyncio.sleep(1)  # Rate limit
        except Exception as e:
            logging.error(f"[HEALTH] ❌ Auto-fix failed: {e}")

    if failed > 0:
        logging.warning(f"[HEALTH] ⚠️  {failed} check(s) FAILED — see above for details")
    else:
        logging.info("[HEALTH] ✅ All checks passed!")

    logging.info("[HEALTH] ──────────────────────────────────────────────────────")

    return {
        "passed": passed,
        "failed": failed,
        "total": total,
        "missing_seo": len(missing_seo),
        "elapsed_s": elapsed,
    }


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

    asyncio.run(run_health_check())
