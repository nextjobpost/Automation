"""
fix_aiims_post.py
=================
Fixes the AIIMS CRE-5 Group B & C Recruitment 2026 post on nextjobpost.in
by fetching the full article content from govtjobsalert.in, then updating the
existing post via the NextJobPost backend API with all the missing details.

Run: python fix_aiims_post.py
"""

import os
import re
import json
import sys
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Force UTF-8 on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass

load_dotenv(override=True)

# ── Config ──────────────────────────────────────────────────────────────
SOURCE_URL   = "https://govtjobsalert.in/aiims-cre-5-recruitment-2026/"
API_URL      = os.getenv("API_URL", "https://nextjobpost-backend.onrender.com/api/jobs")
ADMIN_URL    = os.getenv("ADMIN_URL", "https://nextjobpost-backend.onrender.com/api/admin/login")
API_TOKEN    = os.getenv(
    "API_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9"
    ".QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"
)

HEADERS_SCRAPE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── Known data extracted from govtjobsalert.in ──────────────────────────
AIIMS_DATA = {
    "title": "AIIMS CRE-5 Group B and C Recruitment 2026",
    "company": "AIIMS",
    "eligibility": "10th Pass / 12th Pass / ITI / Diploma / B.Sc / Graduate / Post-Graduate (as per post)",
    "vacancies": "2,693 Posts",
    "salary": "Pay Level 1–8 (₹18,000 – ₹1,51,100)",
    "lastDate": "2026-07-03",
    "applyLink": "https://www.aiimsexams.ac.in/advertisement/6a2cdd89be81945a8330d450",
    "pdfLink": "https://files.govtjobsalert.in/2026/06/AIIMS-CRE-5th-Group-B-C-Recruitment-2026-Notification.pdf",
    "metaTitle": "AIIMS CRE-5 2026: 2693 Group B & C Posts, Apply by 3 July",
    "metaDescription": (
        "AIIMS CRE-5 Recruitment 2026: Apply online for 2,693 Group B & C posts "
        "(Nursing Officer, Pharmacist, Technician, Clerk). Last date: 03 July 2026. "
        "Salary up to ₹1,51,100."
    ),
    "importantDates": (
        "Application Start: 13 June 2026 | Last Date to Apply: 03 July 2026 (5:00 PM) | "
        "NOC Submission: 08 July 2026 | Application Status: 11 July 2026 | "
        "Tentative CBT Exam Date: 25–27 July 2026"
    ),
    "isGovernment": True,
    "sourceUrl": SOURCE_URL,
    "sourceWebsite": "govtjobsalert.in",
}

# ── Step 1 : Authenticate ────────────────────────────────────────────────

def get_auth_token():
    global API_TOKEN
    try:
        r = requests.post(ADMIN_URL, json={"username": "admin", "password": "admin123"}, timeout=10)
        if r.status_code == 200:
            API_TOKEN = r.json().get("token", API_TOKEN)
            print("🔑 Authenticated successfully.")
    except Exception as e:
        print(f"⚠️  Could not refresh token ({e}). Using stored token.")
    return API_TOKEN


# ── Step 2 : Scrape full article content from govtjobsalert.in ───────────

def scrape_aiims_content():
    print(f"\n📥 Fetching content from: {SOURCE_URL}")
    try:
        r = requests.get(SOURCE_URL, headers=HEADERS_SCRAPE, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to fetch source page: {e}")
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    entry = soup.find(class_="entry-content")
    if not entry:
        print("❌ Could not locate .entry-content on the source page.")
        return None

    # Remove clutter: ads, share boxes, scripts, styles, social CTAs
    for cls in [
        "code-block-default", "code-block-center", "gja-share-box",
        "gja-news-box", "gja-divider", "gja-btns", "gja-label",
        "adsbygoogle", "gja-grid-ad", "gja-mid-cta"
    ]:
        for tag in entry.find_all(class_=cls):
            tag.decompose()
    for tag in entry.find_all(["script", "style", "ins"]):
        tag.decompose()

    # Rewrite competitor links to official ones
    official_apply = AIIMS_DATA["applyLink"]
    official_pdf   = AIIMS_DATA["pdfLink"]
    official_site  = "https://www.aiimsexams.ac.in/"

    for a in entry.find_all("a", href=True):
        href = a["href"]
        if "govtjobsalert.in" in href:
            # Replace competitor internal links with official links based on context
            text = a.get_text(strip=True).lower()
            if "pdf" in text or "notification" in text:
                a["href"] = official_pdf
            elif "apply" in text:
                a["href"] = official_apply
            else:
                a["href"] = official_site
        elif href.endswith(".pdf") and "govtjobsalert" in href:
            a["href"] = official_pdf

    html_content = str(entry)
    print(f"✅ Scraped {len(html_content):,} characters of article content.")
    return html_content


# ── Step 3 : Find the job on nextjobpost.in backend ─────────────────────

def find_job(token):
    """Search backend for the AIIMS CRE-5 post and return its _id."""
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Try fetching by keyword
    keywords = ["aiims", "cre-5", "CRE 5", "2693"]
    for kw in keywords:
        try:
            r = requests.get(
                f"{API_URL}?search={kw}&limit=50&status=all",
                headers=auth_headers, timeout=15
            )
            if r.status_code == 200:
                jobs = r.json().get("data", [])
                for job in jobs:
                    title = job.get("title", "").lower()
                    slug  = job.get("slug", "").lower()
                    if "aiims" in title and ("cre" in title or "cre" in slug):
                        print(f"✅ Found job: '{job['title']}' (ID: {job['_id']})")
                        return job
        except Exception as e:
            print(f"⚠️  Search failed for '{kw}': {e}")

    # Broader fallback
    try:
        r = requests.get(f"{API_URL}?limit=200&status=all", headers=auth_headers, timeout=20)
        if r.status_code == 200:
            jobs = r.json().get("data", [])
            for job in jobs:
                title = job.get("title", "").lower()
                slug  = job.get("slug", "").lower()
                source = job.get("sourceUrl", "").lower()
                if "aiims" in title and "cre" in (title + slug + source):
                    print(f"✅ Found job via full list: '{job['title']}' (ID: {job['_id']})")
                    return job
    except Exception as e:
        print(f"⚠️  Full list fetch failed: {e}")

    print("❌ Could not find the AIIMS CRE-5 job in the backend.")
    return None


# ── Step 4 : Build & send the update payload ────────────────────────────

def build_faq_html():
    faqs = [
        {
            "q": "What is AIIMS CRE-5 2026?",
            "a": (
                "AIIMS CRE-5 (5th Common Recruitment Examination) is a centralised exam "
                "conducted by AIIMS New Delhi to fill 2,693 Group B and Group C non-faculty "
                "posts across 32 participating AIIMS and central health institutes."
            ),
        },
        {
            "q": "How many vacancies are there in AIIMS CRE-5 2026?",
            "a": "There are 2,693 vacancies spread across 59 post groups.",
        },
        {
            "q": "What is the last date to apply for AIIMS CRE-5 2026?",
            "a": "The last date to apply online is 03 July 2026 (up to 5:00 PM).",
        },
        {
            "q": "What is the application fee for AIIMS CRE-5?",
            "a": (
                "General/OBC: ₹3,000; SC/ST/EWS: ₹2,400; PwBD: Exempted (no fee). "
                "Fee is paid online only and is non-refundable, except for SC/ST candidates who appear in the exam."
            ),
        },
        {
            "q": "What is the salary for AIIMS CRE-5 posts?",
            "a": (
                "Salary follows the 7th Pay Commission Pay Matrix, from Pay Level 1 (₹18,000) "
                "to Pay Level 8 (₹47,600–₹1,51,100 basic). In-hand salary ranges from ~₹22,000 "
                "to over ₹1,30,000 per month including DA, HRA and Transport Allowance."
            ),
        },
        {
            "q": "What is the selection process for AIIMS CRE-5?",
            "a": (
                "Selection is in 3 stages: (1) Computer-Based Test (CBT) — 90 min, 100 MCQs, "
                "400 marks, negative marking of 1/4; (2) Skill/Trade/Physical Test (qualifying); "
                "(3) Document Verification & Medical Examination."
            ),
        },
        {
            "q": "Where can I apply for AIIMS CRE-5 2026?",
            "a": (
                "Apply online at the official AIIMS exam portal: "
                "https://www.aiimsexams.ac.in/advertisement/6a2cdd89be81945a8330d450"
            ),
        },
    ]

    html = (
        '<div class="gja-faq-section" style="border-top:2px solid #e2e8f0;padding-top:2rem;margin-top:2rem;">'
        '<h2 style="font-size:1.5rem;font-weight:bold;color:#1e3a8a;margin-bottom:1.5rem;">'
        "📋 Frequently Asked Questions (FAQs)"
        "</h2>"
    )
    for faq in faqs:
        html += (
            f'<div class="gja-faq-item" style="margin-bottom:1.25rem;padding:1rem;'
            f'background-color:#f8fafc;border-left:4px solid #2563eb;border-radius:0 8px 8px 0;">'
            f'<h4 style="margin:0 0 0.5rem 0;font-weight:bold;color:#1e293b;font-size:1.05rem;">❓ {faq["q"]}</h4>'
            f'<p style="margin:0;color:#475569;font-size:0.95rem;line-height:1.6;">{faq["a"]}</p>'
            f"</div>"
        )
    html += "</div>"
    return html


def update_job(job_id, article_html, token):
    faq_html = build_faq_html()
    full_description = article_html + faq_html

    payload = {
        **AIIMS_DATA,
        "jobDescription": full_description,
        "description": (
            "AIIMS CRE-5 Recruitment 2026 has been released for 2,693 Group B and Group C posts "
            "including Nursing Officer, Pharmacist, Lab Technician, Clerk and many more roles across "
            "32 AIIMS and central health institutes. Apply online by 03 July 2026. "
            "Salary up to ₹1,51,100 per month."
        ),
        "shortSummary": (
            "AIIMS CRE-5 2026: 2,693 Group B & C vacancies (Nursing Officer, Pharmacist, Technician, "
            "Clerk, JE). Apply by 03 July 2026. Salary: Pay Level 1–8 (up to ₹1,51,100)."
        ),
    }

    auth_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    print(f"\n🚀 Sending update to job ID: {job_id} …")
    try:
        r = requests.put(f"{API_URL}/{job_id}", json=payload, headers=auth_headers, timeout=30)
        if r.status_code == 200:
            print("✅ Job updated successfully!")
            print(f"   Title      : {AIIMS_DATA['title']}")
            print(f"   Vacancies  : {AIIMS_DATA['vacancies']}")
            print(f"   Salary     : {AIIMS_DATA['salary']}")
            print(f"   Last Date  : {AIIMS_DATA['lastDate']}")
            print(f"   Apply Link : {AIIMS_DATA['applyLink']}")
            print(f"   PDF Link   : {AIIMS_DATA['pdfLink']}")
            print(f"   Description: {len(full_description):,} chars")
            return True
        else:
            print(f"❌ Update failed — HTTP {r.status_code}: {r.text[:500]}")
            return False
    except Exception as e:
        print(f"❌ Exception during update: {e}")
        return False


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("🏥  AIIMS CRE-5 Post Fix — NextJobPost.in")
    print("=" * 55)

    token = get_auth_token()

    # 1. Scrape
    article_html = scrape_aiims_content()
    if not article_html:
        print("\n❌ Aborting: could not scrape article content.")
        sys.exit(1)

    # 2. Find job
    job = find_job(token)
    if not job:
        print("\n❌ Aborting: job not found in backend.")
        sys.exit(1)

    job_id = job.get("_id") or job.get("id")
    print(f"\nCurrent job description length: {len(job.get('jobDescription',''))} chars")
    print(f"Current salary   : {job.get('salary','(empty)')}")
    print(f"Current vacancies: {job.get('vacancies','(empty)')}")
    print(f"Current eligibility: {job.get('eligibility','(empty)')}")
    print(f"Current lastDate : {job.get('lastDate','(empty)')}")
    print(f"Current applyLink: {job.get('applyLink','(empty)')}")

    # 3. Update
    success = update_job(job_id, article_html, token)
    if success:
        print(f"\n🎉 Done! Visit https://nextjobpost.in/aiims-cre-5-group-b-and-c-recruitment-2026 to verify.")
    else:
        print("\n❌ Fix failed. Check the error output above.")


if __name__ == "__main__":
    main()
