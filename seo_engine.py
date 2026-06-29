"""
seo_engine.py — SEO Generation, Patching & Schema Builder
Part of the NextJobPost Automation Engine (D:/Automation)

Extends bot1.py with:
  - Gemini-powered metaTitle, metaDescription, FAQ, keyword generation
  - REST API patching of published jobs with generated SEO metadata
  - JSON-LD schema construction (JobPosting, FAQPage, BreadcrumbList)
  - Related job/result/admit-card linking suggestions
"""

import os
import json
import re
import asyncio
import logging
import aiohttp
from datetime import datetime

from dotenv import load_dotenv
load_dotenv(override=True)

# ── Config ────────────────────────────────────────────────────────────────────
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://nextjobpost.in")

# Detect environment to set appropriate default API url
IS_PRODUCTION = os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER") or os.getenv("PORT") is not None
DEFAULT_API_URL = "https://nextjobpost-backend.onrender.com/api/jobs" if IS_PRODUCTION else "http://localhost:4000/api/jobs"
API_URL = os.getenv("API_URL", DEFAULT_API_URL)

API_TOKEN = os.getenv("API_TOKEN", "")
OLD_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4ifQ.ts-o1us7bsOOJunK2dL4HNmz1ONh3tywCLj0D079k4M"
NEW_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"
if not API_TOKEN or API_TOKEN == OLD_TOKEN:
    API_TOKEN = NEW_TOKEN

API_KEY = os.getenv("API_KEY", "")  # Google Gemini API key

# ── Gemini client (reuse from bot1 if possible, else create here) ─────────────
_client_gemini = None

def _get_gemini_client():
    global _client_gemini
    if _client_gemini is None and API_KEY:
        try:
            from google import genai  # type: ignore
            _client_gemini = None  # Disabled Gemini Integration
        except Exception as e:
            logging.warning(f"[SEO] Could not init Gemini client: {e}")
    return _client_gemini


# ═══════════════════════════════════════════════════════════════════════════════
# 1. AI-POWERED SEO FIELD GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_seo_for_job(job: dict) -> dict:
    """
    Uses Google Gemini to generate:
      - metaTitle       (65-char high-CTR title)
      - metaDescription (150-155 char description)
      - seoKeywords     (list of 6-8 keywords)
      - faqs            (list of 5 {q, a} dicts)
      - shortSummary    (20-word OG preview — improves on existing if present)

    Returns a dict of just the generated SEO fields.
    Falls back to rule-based generation if Gemini is unavailable.
    """
    client = _get_gemini_client()

    title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "Pan India")
    education = job.get("education", "")
    vacancies = job.get("vacancies", "")
    salary = job.get("salary", "")
    post_type = job.get("postType", "Job")
    last_date = job.get("lastDate", "")
    is_govt = job.get("isGovernment", False)
    slug = job.get("slug", "")

    year = datetime.now().year

    # Format last_date nicely
    last_date_str = ""
    if last_date:
        try:
            if isinstance(last_date, str):
                last_date_str = last_date[:10]
            else:
                last_date_str = str(last_date)[:10]
        except Exception:
            pass

    # ── Try AI first ──────────────────────────────────────────────────────────
    if client:
        prompt = f"""
You are an expert SEO specialist for an Indian government & private job portal called NextJobPost.

Generate SEO metadata for this job posting. Return ONLY a raw JSON object (no markdown).

Job Details:
- Title: {title}
- Company: {company}
- Location: {location}
- Education Required: {education}
- Vacancies: {vacancies}
- Salary: {salary}
- Post Type: {post_type}
- Last Date: {last_date_str}
- Is Government Job: {is_govt}
- Year: {year}

Generate:
1. "metaTitle": A compelling, keyword-rich SEO title. Max 65 characters. Include year ({year}) and action word like "Apply Now", "Recruitment", "Vacancy". Example: "SSC CGL Recruitment {year} – 14582 Vacancies | Apply Now"
2. "metaDescription": A 148-155 character description. Include eligibility, last date if available, and a call to action. No competitor names.
3. "seoKeywords": Array of 6-8 keywords. Include: job title keyword, state keyword if location exists, qualification keyword, department keyword, year. Example: ["SSC CGL 2026", "SSC Jobs", "SSC CGL Vacancy 2026", "Govt Jobs India"]
4. "faqs": Array of exactly 5 objects with "q" and "a" keys. Questions should be what job seekers actually search for (eligibility, salary, last date, how to apply, selection process). Each answer max 80 words.
5. "shortSummary": A professional 18-22 word summary for Open Graph preview. No emojis. Example: "Apply for SSC CGL Recruitment {year}. Check eligibility, vacancies, salary, and last date to apply online."

Rules:
- NEVER include competitor websites (sarkariresult.com, freejobalert.com, etc.)
- Keep all content specific to this job posting
- Use Indian English
- metaTitle MUST be under 65 characters
- metaDescription MUST be 148-155 characters exactly
"""
        candidates = [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ]
        for model in candidates:
            try:
                from google.genai import types  # type: ignore
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                    ),
                )
                raw = response.text.strip()
                if raw.startswith("```json"):
                    raw = raw[7:-3].strip()
                elif raw.startswith("```"):
                    raw = raw[3:-3].strip()
                data = json.loads(raw)
                logging.info(f"[SEO] ✅ Generated SEO for '{title}' using {model}")
                return _validate_seo_fields(data, job)
            except Exception as e:
                logging.warning(f"[SEO] Model {model} failed: {e}")
                await asyncio.sleep(1)

    # ── Rule-based fallback ───────────────────────────────────────────────────
    logging.info(f"[SEO] Using rule-based fallback for '{title}'")
    return _rule_based_seo(job)


def _validate_seo_fields(data: dict, job: dict) -> dict:
    """Validates and trims AI-generated SEO fields to spec."""
    meta_title = str(data.get("metaTitle", "")).strip()[:65]
    meta_desc = str(data.get("metaDescription", "")).strip()[:160]
    keywords = data.get("seoKeywords", [])
    if not isinstance(keywords, list):
        keywords = [str(keywords)]
    keywords = [str(k).strip() for k in keywords[:8] if k]

    faqs = data.get("faqs", [])
    if not isinstance(faqs, list):
        faqs = []
    clean_faqs = []
    for faq in faqs[:5]:
        if isinstance(faq, dict) and faq.get("q") and faq.get("a"):
            clean_faqs.append({"q": str(faq["q"]).strip(), "a": str(faq["a"]).strip()})

    short_summary = str(data.get("shortSummary", "")).strip()[:200]

    # Fallback to rule-based if critical fields are empty
    if not meta_title or not meta_desc:
        fallback = _rule_based_seo(job)
        meta_title = meta_title or fallback["metaTitle"]
        meta_desc = meta_desc or fallback["metaDescription"]

    return {
        "metaTitle": meta_title,
        "metaDescription": meta_desc,
        "seoKeywords": keywords,
        "faqs": clean_faqs,
        "shortSummary": short_summary,
    }


def _rule_based_seo(job: dict) -> dict:
    """High-quality rule-based SEO generation when AI is unavailable."""
    title = job.get("title", "Job Opening")
    company = job.get("company", "")
    location = job.get("location", "Pan India")
    vacancies = job.get("vacancies", "")
    salary = job.get("salary", "")
    education = job.get("education", "")
    post_type = job.get("postType", "Job")
    last_date = job.get("lastDate", "")
    is_govt = job.get("isGovernment", False)
    year = datetime.now().year

    # ── Meta Title ────────────────────────────────────────────────────────────
    vac_part = f" – {vacancies}" if vacancies and vacancies != "Not Mentioned" else ""
    meta_title = f"{title} {year}{vac_part} | Apply Online"
    if len(meta_title) > 65:
        meta_title = f"{title[:45].rstrip()} {year} | Apply Now"
    meta_title = meta_title[:65]

    # ── Meta Description ──────────────────────────────────────────────────────
    parts = []
    if post_type in ("Result", "Answer Key"):
        parts.append(f"Check {title} result/answer key {year}.")
    elif post_type == "Admit Card":
        parts.append(f"Download {title} admit card {year}.")
    else:
        parts.append(f"Apply for {title} {year}.")
        if education and education != "Not Mentioned":
            parts.append(f"Eligibility: {education[:40]}.")
        if salary and salary != "Not Mentioned":
            parts.append(f"Salary: {salary[:30]}.")
        if last_date:
            ld_str = str(last_date)[:10]
            parts.append(f"Last Date: {ld_str}.")
        parts.append("Apply online at NextJobPost.")

    meta_desc = " ".join(parts)
    if len(meta_desc) > 155:
        meta_desc = meta_desc[:152] + "..."
    while len(meta_desc) < 140 and not post_type in ("Result", "Answer Key", "Admit Card"):
        meta_desc = meta_desc.rstrip(".") + ". Check eligibility & apply now."
        if len(meta_desc) > 155:
            meta_desc = meta_desc[:152] + "..."
            break

    # ── Keywords ──────────────────────────────────────────────────────────────
    keywords = [title, f"{title} {year}"]
    if company and company != "Not Mentioned":
        keywords.append(f"{company} Jobs")
    if location and location != "Not Mentioned" and location.lower() != "pan india":
        keywords.append(f"Jobs in {location}")
    if education and education != "Not Mentioned":
        keywords.append(f"{education} Jobs")
    if is_govt:
        keywords.extend(["Govt Jobs India", "Sarkari Naukri"])
    else:
        keywords.extend(["Private Jobs", "Jobs Apply Online"])
    keywords = list(dict.fromkeys(keywords))[:8]

    # ── FAQs ──────────────────────────────────────────────────────────────────
    faqs = []
    faqs.append({
        "q": f"What is the last date to apply for {title}?",
        "a": f"The last date to apply for {title} is {str(last_date)[:10] if last_date else 'mentioned in the official notification'}. Candidates are advised to submit applications well before the deadline."
    })
    if education and education != "Not Mentioned":
        faqs.append({
            "q": f"What is the educational qualification required for {title}?",
            "a": f"Candidates must have {education} from a recognized board or university. Please refer to the official notification for complete eligibility details."
        })
    if salary and salary != "Not Mentioned":
        faqs.append({
            "q": f"What is the salary for {title}?",
            "a": f"The pay scale for this position is {salary}. Additional allowances (DA, HRA, TA) as per government norms may also apply."
        })
    if vacancies and vacancies != "Not Mentioned":
        faqs.append({
            "q": f"How many vacancies are available for {title}?",
            "a": f"A total of {vacancies} vacancies have been announced for {title} {year}. The number of posts may vary based on category-wise reservation."
        })
    faqs.append({
        "q": f"How to apply for {title}?",
        "a": f"Visit the official website or apply directly via the Apply Now link on NextJobPost. Fill in the application form, upload required documents, and submit before the last date."
    })

    # ── Short Summary ─────────────────────────────────────────────────────────
    short_summary = f"Apply for {title} {year}. Check eligibility, vacancies, salary, and last date to apply online at NextJobPost."[:200]

    return {
        "metaTitle": meta_title,
        "metaDescription": meta_desc,
        "seoKeywords": keywords,
        "faqs": faqs,
        "shortSummary": short_summary,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. API PATCHER — Writes generated SEO back to the live job via PUT /api/jobs/:id
# ═══════════════════════════════════════════════════════════════════════════════

async def patch_seo_metadata(job_id: str, seo_data: dict, session: aiohttp.ClientSession = None) -> bool:
    """
    Patches a published job with the generated SEO fields via PUT /api/jobs/:id.
    Uses the admin JWT token from API_TOKEN env var.
    Returns True on success.
    """
    if not job_id or not API_TOKEN:
        logging.warning("[SEO] Cannot patch — missing job_id or API_TOKEN")
        return False

    patch_url = API_URL.replace("/jobs", f"/jobs/{job_id}")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_TOKEN}",
    }

    # Only send fields the API knows about
    payload = {}
    if seo_data.get("metaTitle"):
        payload["metaTitle"] = seo_data["metaTitle"]
    if seo_data.get("metaDescription"):
        payload["metaDescription"] = seo_data["metaDescription"]
    # shortSummary maps to `description` in the Job model
    if seo_data.get("shortSummary"):
        payload["description"] = seo_data["shortSummary"]
    if seo_data.get("jobDescription"):
        payload["jobDescription"] = seo_data["jobDescription"]

    if not payload:
        return False

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        async with session.put(patch_url, json=payload, headers=headers, timeout=20) as res:
            if res.status in (200, 201):
                logging.info(f"[SEO] ✅ Patched SEO metadata for job {job_id}")
                return True
            else:
                body = await res.text()
                logging.warning(f"[SEO] ⚠️ Patch failed ({res.status}): {body[:200]}")
                return False
    except Exception as e:
        logging.error(f"[SEO] ❌ Patch error for {job_id}: {e}")
        return False
    finally:
        if close_session:
            await session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. JSON-LD SCHEMA BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def build_job_posting_schema(job: dict, slug: str) -> dict:
    """Builds a valid Google JobPosting schema dict."""
    title = job.get("title", "")
    company = job.get("company", "NextJobPost")
    location = job.get("location", "Pan India")
    salary = job.get("salary", "")
    description = job.get("jobDescription") or job.get("description") or title
    created_at = job.get("createdAt", datetime.utcnow().isoformat())
    last_date = job.get("lastDate", "")

    schema = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": _strip_html(description)[:500] if description else title,
        "datePosted": str(created_at)[:10],
        "hiringOrganization": {
            "@type": "Organization",
            "name": company if company and company != "Not Mentioned" else "Government of India",
            "logo": f"{SITE_BASE_URL}/logo.png",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": location if location and location != "Not Mentioned" else "Pan India",
                "addressCountry": "IN",
            },
        },
        "directApply": True,
    }

    if last_date:
        schema["validThrough"] = str(last_date)[:10]

    if salary and salary != "Not Mentioned":
        schema["baseSalary"] = {
            "@type": "MonetaryAmount",
            "currency": "INR",
            "value": {
                "@type": "QuantitativeValue",
                "description": salary,
            },
        }

    job_type = job.get("type", "")
    type_map = {
        "Full-Time": "FULL_TIME",
        "Part-Time": "PART_TIME",
        "Internship": "INTERN",
        "Contract": "CONTRACTOR",
        "Remote": "FULL_TIME",
        "Hybrid": "FULL_TIME",
    }
    if job_type in type_map:
        schema["employmentType"] = type_map[job_type]

    return schema


def build_faq_schema(faqs: list) -> dict:
    """Builds FAQPage schema from a list of {q, a} dicts."""
    if not faqs:
        return {}
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": faq["q"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": faq["a"],
                },
            }
            for faq in faqs
            if faq.get("q") and faq.get("a")
        ],
    }


def build_breadcrumb_schema(job: dict, slug: str) -> dict:
    """Builds BreadcrumbList schema for a job detail page."""
    title = job.get("title", "Job")
    is_govt = job.get("isGovernment", False)
    post_type = job.get("postType", "Job")

    # Choose category
    if post_type == "Result":
        cat_name, cat_path = "Results", "/results"
    elif post_type == "Admit Card":
        cat_name, cat_path = "Admit Cards", "/admit-cards"
    elif post_type == "Answer Key":
        cat_name, cat_path = "Answer Keys", "/answer-keys"
    elif is_govt:
        cat_name, cat_path = "Govt Jobs", "/govt-jobs"
    else:
        cat_name, cat_path = "Jobs", "/private-jobs"

    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE_BASE_URL},
            {"@type": "ListItem", "position": 2, "name": cat_name, "item": f"{SITE_BASE_URL}{cat_path}"},
            {"@type": "ListItem", "position": 3, "name": title, "item": f"{SITE_BASE_URL}/{slug}"},
        ],
    }


def build_organization_schema() -> dict:
    """Builds the Organization schema for NextJobPost."""
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "NextJobPost",
        "url": SITE_BASE_URL,
        "logo": f"{SITE_BASE_URL}/logo.png",
        "sameAs": [
            "https://www.linkedin.com/in/next-job-post-199b5b371",
            "https://t.me/nextjobpost",
        ],
    }


def build_all_schemas(job: dict, slug: str, faqs: list = None) -> list:
    """Returns a list of all applicable schemas for a job page."""
    schemas = []
    schemas.append(build_organization_schema())
    schemas.append(build_job_posting_schema(job, slug))
    schemas.append(build_breadcrumb_schema(job, slug))
    if faqs:
        faq_schema = build_faq_schema(faqs)
        if faq_schema:
            schemas.append(faq_schema)
    return schemas


# ═══════════════════════════════════════════════════════════════════════════════
# 4. KEYWORD EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════════

def extract_keywords_from_job(job: dict) -> list:
    """
    Extracts a ranked list of SEO keywords from job fields.
    Useful for programmatic SEO page matching.
    """
    keywords = set()
    year = str(datetime.now().year)

    title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "")
    education = job.get("education", "")
    is_govt = job.get("isGovernment", False)

    # Primary keyword — job title
    if title:
        keywords.add(title)
        keywords.add(f"{title} {year}")
        keywords.add(f"{title} Recruitment {year}")

    # Company keyword
    if company and company not in ("Not Mentioned", ""):
        keywords.add(f"{company} Jobs")
        keywords.add(f"{company} Recruitment {year}")

    # Location keyword
    if location and location.lower() not in ("pan india", "not mentioned", ""):
        keywords.add(f"Jobs in {location}")
        keywords.add(f"Government Jobs in {location}" if is_govt else f"Private Jobs in {location}")
        if title:
            keywords.add(f"{title} {location}")

    # Education/Qualification keyword
    qual_map = {
        "10th": "10th Pass Jobs",
        "12th": "12th Pass Jobs",
        "b.tech": "BTech Jobs",
        "b.e": "BE Jobs",
        "graduate": "Graduate Jobs",
        "diploma": "Diploma Jobs",
        "iti": "ITI Jobs",
        "mba": "MBA Jobs",
        "medical": "Medical Jobs",
    }
    if education:
        edu_lower = education.lower()
        for key, kw in qual_map.items():
            if key in edu_lower:
                keywords.add(kw)
                break

    # Generic govt/private
    if is_govt:
        keywords.add("Sarkari Naukri")
        keywords.add(f"Sarkari Naukri {year}")
        keywords.add("Govt Jobs India")
    else:
        keywords.add("Private Jobs India")
        keywords.add(f"Jobs Apply Online {year}")

    return sorted(list(keywords))[:10]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. RELATED CONTENT FINDER
# ═══════════════════════════════════════════════════════════════════════════════

async def find_related_jobs(job: dict, limit: int = 5) -> list:
    """
    Fetches related jobs/results/admit-cards from the live API.
    Uses company name and location as search signals.
    Returns list of {title, slug, postType} dicts.
    """
    company = job.get("company", "")
    location = job.get("location", "")
    post_type = job.get("postType", "Job")

    # Decide what to look for based on post type
    if post_type == "Result":
        search_query = company or job.get("title", "")[:30]
        filter_params = f"?q={search_query}&postType=Result&limit={limit}"
    elif post_type == "Admit Card":
        search_query = company or job.get("title", "")[:30]
        filter_params = f"?q={search_query}&postType=Admit Card&limit={limit}"
    else:
        # For regular jobs: find similar jobs by company or location
        if company and company != "Not Mentioned":
            filter_params = f"?q={company}&limit={limit}&excludePostType=Syllabus"
        elif location and location not in ("Pan India", "Not Mentioned"):
            filter_params = f"?location={location}&limit={limit}&excludePostType=Syllabus"
        else:
            return []

    url = f"{API_URL}{filter_params}"
    headers = {"Content-Type": "application/json"}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as res:
                if res.status == 200:
                    data = await res.json()
                    jobs_list = data.get("data") or data.get("jobs") or []
                    return [
                        {
                            "title": j.get("title", ""),
                            "slug": j.get("slug", ""),
                            "postType": j.get("postType", "Job"),
                            "url": f"{SITE_BASE_URL}/{j.get('slug', '')}",
                        }
                        for j in jobs_list[:limit]
                        if j.get("slug") and j.get("slug") != job.get("slug")
                    ]
    except Exception as e:
        logging.warning(f"[SEO] Could not fetch related jobs: {e}")

    return []


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FULL SEO PIPELINE — call this after a job is successfully posted
# ═══════════════════════════════════════════════════════════════════════════════

async def run_seo_pipeline(job: dict, job_id: str, slug: str, session: aiohttp.ClientSession = None):
    """
    Master SEO pipeline called right after send_to_api() succeeds.
    Steps:
      1. Generate SEO fields (metaTitle, metaDescription, FAQs, keywords)
      2. Patch back to API via PUT /api/jobs/:id
      3. Log schemas for debugging
    """
    if not job_id:
        logging.warning("[SEO] Skipping pipeline — no job_id returned from API")
        return

    logging.info(f"[SEO] 🚀 Starting SEO pipeline for: {job.get('title', '')}")

    try:
        # Step 1 — Generate
        seo_data = await generate_seo_for_job(job)
        logging.info(f"[SEO] 📝 metaTitle: {seo_data.get('metaTitle', '')}")
        logging.info(f"[SEO] 📝 metaDesc:  {seo_data.get('metaDescription', '')}")
        logging.info(f"[SEO] 🔑 Keywords:  {seo_data.get('seoKeywords', [])}")

        # Step 2 — Patch to API
        # First, run internal linking engine to auto-inject relevant anchor tags
        try:
            desc_html = job.get("jobDescription") or job.get("description") or ""
            linked_html = await auto_inject_internal_links(job_id, desc_html, session=session)
            if linked_html:
                seo_data["jobDescription"] = linked_html
                job["jobDescription"] = linked_html  # update local dict too
        except Exception as le:
            logging.error(f"[SEO] ❌ Internal linking engine error: {le}")

        await patch_seo_metadata(job_id, seo_data, session=session)

        # Step 3 — Build & log schemas
        faqs = seo_data.get("faqs", [])
        schemas = build_all_schemas(job, slug, faqs)
        logging.info(f"[SEO] 🏗️  Built {len(schemas)} JSON-LD schemas for /{slug}")

        # Step 4 — Extract & log keywords
        keywords = extract_keywords_from_job(job)
        logging.info(f"[SEO] 🔍 Extracted keywords: {keywords}")

    except Exception as e:
        logging.error(f"[SEO] ❌ Pipeline error for job_id={job_id}: {e}")



# ═══════════════════════════════════════════════════════════════════════════════
# 7. AUTO INTERNAL LINKING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

async def auto_inject_internal_links(job_id: str, job_description_html: str, session: aiohttp.ClientSession = None) -> str:
    """
    Scans the HTML job description and injects internal links to static pages
    and dynamic job postings on NextJobPost to boost internal link equity.
    """
    if not job_description_html:
        return ""

    from bs4 import BeautifulSoup
    import re

    # 1. Static keywords map
    keyword_map = {
        "upsc": f"{SITE_BASE_URL}/upsc-jobs",
        "ssc": f"{SITE_BASE_URL}/ssc-jobs",
        "railway": f"{SITE_BASE_URL}/railway-jobs",
        "bank jobs": f"{SITE_BASE_URL}/banking-jobs",
        "banking jobs": f"{SITE_BASE_URL}/banking-jobs",
        "defence jobs": f"{SITE_BASE_URL}/defence-jobs",
        "police jobs": f"{SITE_BASE_URL}/police-jobs-in-india",
        "sarkari naukri": SITE_BASE_URL,
        "admit card": f"{SITE_BASE_URL}/admit-cards",
        "admit cards": f"{SITE_BASE_URL}/admit-cards",
        "exam result": f"{SITE_BASE_URL}/results",
        "exam results": f"{SITE_BASE_URL}/results",
        "answer key": f"{SITE_BASE_URL}/answer-keys",
        "answer keys": f"{SITE_BASE_URL}/answer-keys",
        "10th pass": f"{SITE_BASE_URL}/10th-pass-jobs",
        "12th pass": f"{SITE_BASE_URL}/12th-pass-jobs",
        "diploma jobs": f"{SITE_BASE_URL}/diploma-jobs",
        "iti jobs": f"{SITE_BASE_URL}/iti-jobs",
        "engineering jobs": f"{SITE_BASE_URL}/engineering-freshers",
        "software jobs": f"{SITE_BASE_URL}/software-jobs",
    }

    # 2. Fetch active jobs to build dynamic link targets
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        headers = {"Content-Type": "application/json"}
        if API_TOKEN:
            headers["Authorization"] = f"Bearer {API_TOKEN}"
        
        # Fetch last 50 jobs
        async with session.get(f"{API_URL}?limit=50", headers=headers, timeout=10) as res:
            if res.status == 200:
                data = await res.json()
                jobs_list = data.get("data") or data.get("jobs") or []
                for j in jobs_list:
                    slug = j.get("slug")
                    title = j.get("title")
                    company = j.get("company")
                    jid = j.get("_id") or j.get("id")
                    
                    if not slug or jid == job_id:
                        continue
                    
                    # Generate some linking phrases
                    if company and company not in ("Not Mentioned", ""):
                        # E.g. "DRDO Recruitment" -> /drdo-dysl-recruitment-2026
                        phrase = f"{company} recruitment"
                        if len(phrase) > 5 and phrase.lower() not in keyword_map:
                            keyword_map[phrase.lower()] = f"{SITE_BASE_URL}/{slug}"
                        
                        phrase_job = f"{company} job"
                        if len(phrase_job) > 5 and phrase_job.lower() not in keyword_map:
                            keyword_map[phrase_job.lower()] = f"{SITE_BASE_URL}/{slug}"
                    
                    if title and len(title) > 10:
                        # Add title keywords if unique enough
                        clean_title = re.sub(r'\(.*?\)', '', title).strip() # Remove parentheses
                        clean_title = re.sub(r'\s+', ' ', clean_title)
                        # Take first 4 words of title if it is long
                        words = clean_title.split()
                        if len(words) >= 3:
                            phrase_title = " ".join(words[:4])
                            if len(phrase_title) > 8 and phrase_title.lower() not in keyword_map:
                                keyword_map[phrase_title.lower()] = f"{SITE_BASE_URL}/{slug}"
    except Exception as e:
        logging.warning(f"[SEO] Error fetching jobs for link map: {e}")
    finally:
        if close_session:
            await session.close()

    # Sort keywords by length in descending order to match longer phrases first
    sorted_keywords = sorted(keyword_map.keys(), key=len, reverse=True)

    # 3. Parse HTML and inject
    soup = BeautifulSoup(job_description_html, "html.parser")
    
    links_injected = 0
    max_links = 4
    injected_urls = set()

    # Walk the tree and find text nodes
    def walk_and_inject(node):
        nonlocal links_injected
        if links_injected >= max_links:
            return

        if node.name in ('a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'code', 'pre', 'script', 'style'):
            return

        # bs4 text nodes are NavigableString
        from bs4 import NavigableString
        children = list(node.children)
        for child in children:
            if isinstance(child, NavigableString):
                text_content = str(child)
                if not text_content.strip():
                    continue
                
                # Check for keyword matches in text_content
                new_child = None
                for kw in sorted_keywords:
                    url = keyword_map[kw]
                    if url in injected_urls:
                        continue # Don't link to the same page twice in one description
                        
                    # Match case-insensitively with word boundaries
                    pattern = re.compile(rf"\b({re.escape(kw)})\b", re.IGNORECASE)
                    match = pattern.search(text_content)
                    if match:
                        matched_text = match.group(1)
                        # Split string around match
                        start_idx = match.start()
                        end_idx = match.end()
                        
                        left_text = text_content[:start_idx]
                        right_text = text_content[end_idx:]
                        
                        # Create new HTML nodes
                        left_node = NavigableString(left_text) if left_text else None
                        
                        # Link element
                        link_node = soup.new_tag("a", href=url)
                        link_node['style'] = "color:#6366f1;font-weight:600;text-decoration:underline"
                        link_node.string = matched_text
                        
                        right_node = NavigableString(right_text) if right_text else None
                        
                        # Replace NavigableString
                        idx = node.contents.index(child)
                        child.extract()
                        
                        current_idx = idx
                        if left_node:
                            node.insert(current_idx, left_node)
                            current_idx += 1
                        node.insert(current_idx, link_node)
                        current_idx += 1
                        if right_node:
                            node.insert(current_idx, right_node)
                        
                        links_injected += 1
                        injected_urls.add(url)
                        break
            else:
                walk_and_inject(child)

    walk_and_inject(soup)
    return str(soup)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _strip_html(text: str) -> str:
    """Strips HTML tags for use in schema text fields."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", str(text)).strip()
