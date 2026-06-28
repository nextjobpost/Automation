"""
bulk_fix_jobs.py
================
Bulk-fixes ALL thin / empty job description posts on nextjobpost.in.

For govt jobs (sourced from govtjobsalert.in):
  - Scrapes the full article HTML from the source URL
  - Calls Gemini AI to extract metadata (salary, eligibility, vacancies, dates, FAQs)
  - Updates the post via the NextJobPost backend API

For IT/private jobs (no source URL):
  - Skips (can't auto-fix without a source)

Run: python bulk_fix_jobs.py
     python bulk_fix_jobs.py --dry-run       (preview only, no writes)
     python bulk_fix_jobs.py --limit 10      (process first N thin jobs)
"""

import os, re, sys, json, time, hashlib, argparse, requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except: pass

load_dotenv(override=True)

# ── Config ───────────────────────────────────────────────────────────────
API_URL   = os.getenv("API_URL",   "https://nextjobpost-backend.onrender.com/api/jobs")
ADMIN_URL = os.getenv("ADMIN_URL", "https://nextjobpost-backend.onrender.com/api/admin/login")
API_TOKEN = os.getenv("API_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9"
    ".QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"
)
API_KEY   = os.getenv("API_KEY")   # Gemini

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# Minimum chars to consider a job description "full"
THIN_THRESHOLD  = 1000
DELAY_BETWEEN   = 3   # seconds between requests to avoid rate-limits

# ── Gemini setup ─────────────────────────────────────────────────────────
client_gemini = None
if API_KEY:
    try:
        from google import genai
        from google.genai import types as gtypes
        client_gemini = None  # Disabled Gemini Integration
        print("🤖 Gemini AI ready.")
    except Exception as e:
        print(f"⚠️  Gemini init failed: {e}. Will use basic parser.")

# ── Auth ─────────────────────────────────────────────────────────────────
def get_token():
    global API_TOKEN
    try:
        r = requests.post(ADMIN_URL,
                          json={"username": "admin", "password": "admin123"},
                          timeout=10)
        if r.status_code == 200:
            API_TOKEN = r.json().get("token", API_TOKEN)
            print("🔑 Authenticated.")
    except Exception as e:
        print(f"⚠️  Auth failed ({e}), using stored token.")
    return API_TOKEN

# ── Fetch all jobs from backend ──────────────────────────────────────────
def fetch_all_jobs(token):
    headers = {"Authorization": f"Bearer {token}"}
    all_jobs = []
    page, limit = 1, 150
    while True:
        try:
            r = requests.get(
                f"{API_URL}?limit={limit}&page={page}&status=all",
                headers=headers, timeout=20
            )
            if r.status_code != 200:
                print(f"⚠️  Fetch page {page} failed: {r.status_code}")
                break
            data  = r.json().get("data", [])
            all_jobs.extend(data)
            total = r.json().get("total", 0)
            if len(all_jobs) >= total or len(data) == 0:
                break
            page += 1
        except Exception as e:
            print(f"⚠️  Error fetching jobs: {e}")
            break
    return all_jobs

# ── Identify thin jobs ───────────────────────────────────────────────────
def is_thin(job):
    desc = job.get("jobDescription", "") or ""
    has_table = "<table" in desc.lower()
    return not desc or len(desc) < THIN_THRESHOLD or not has_table

# ── Scrape article from govtjobsalert.in ────────────────────────────────
def scrape_source(url):
    try:
        r = requests.get(url, headers=SCRAPE_HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"   ❌ Scrape failed: {e}")
        return None, None

    soup = BeautifulSoup(r.text, "html.parser")
    entry = soup.find(class_="entry-content")
    if not entry:
        entry = soup.find("article") or soup.find(id="content")
    if not entry:
        print("   ❌ No .entry-content found.")
        return None, None

    # Remove clutter
    for cls in [
        "code-block-default", "code-block-center", "gja-share-box",
        "gja-news-box", "gja-divider", "gja-btns", "gja-label",
        "adsbygoogle", "gja-grid-ad", "gja-mid-cta"
    ]:
        for tag in entry.find_all(class_=cls):
            tag.decompose()
    for tag in entry.find_all(["script", "style", "ins"]):
        tag.decompose()

    # Extract plain text for AI
    text = entry.get_text(separator="\n")
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    # Rewrite competitor-internal links
    for a in entry.find_all("a", href=True):
        href = a["href"]
        if "govtjobsalert.in" in href:
            # remove the link, keep text
            a.unwrap()

    html = str(entry)
    return html, text

# ── Gemini enrichment ────────────────────────────────────────────────────
MONTHS_MAP = {
    "jan":1,"january":1,"feb":2,"february":2,"mar":3,"march":3,
    "apr":4,"april":4,"may":5,"jun":6,"june":6,"jul":7,"july":7,
    "aug":8,"august":8,"sep":9,"september":9,"oct":10,"october":10,
    "nov":11,"november":11,"dec":12,"december":12
}

def basic_extract(text, title):
    """Regex-based fallback extractor."""
    org = title.split()[0] if title else "Govt Department"

    # Vacancies
    vac = "Various Vacancies"
    m = re.search(r'\b(\d[\d,]*)\s*(?:posts?|vacancies|seats?|slots?)\b', text, re.I)
    if m: vac = f"{m.group(1)} Posts"

    # Salary
    sal = "As per notification"
    m = re.search(r'(?:₹|rs\.?|inr)\s*(\d[\d,\.]+)', text, re.I)
    if m: sal = f"₹{m.group(1)}"
    else:
        m2 = re.search(r'pay\s*(?:level|matrix|band)\s*[-–]?\s*(\d+)', text, re.I)
        if m2: sal = f"Pay Level {m2.group(1)}"

    # Last date
    ld = ""
    MONTHS_P = r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
    m3 = re.search(
        r'(?:last\s*date|closing|deadline)[^0-9\n]{0,50}\b(\d{1,2})\s+(' + MONTHS_P + r')\s+(\d{4})\b',
        text, re.I
    )
    if m3:
        d, mn, y = m3.groups()
        mo = MONTHS_MAP.get(mn.lower()[:3], 1)
        try: ld = f"{int(y):04d}-{mo:02d}-{int(d):02d}"
        except: pass

    # Eligibility
    elig = "As per notification"
    kws = re.findall(r'\b(?:10th|12th|b\.?e\.?|b\.?tech|m\.?tech|diploma|graduate|iti|mbbs|b\.?sc|m\.?sc|postgraduate|post\s*graduate|any\s*degree)\b', text, re.I)
    if kws: elig = ", ".join(sorted(set(k.upper() for k in kws)))

    summary = text[:250].replace("\n", " ") + "..."
    return {
        "organization": org,
        "eligibility": elig,
        "vacancies": vac,
        "salary": sal,
        "lastDate": ld,
        "summary": summary,
        "seoTitle": title[:60],
        "seoDescription": summary[:155],
        "officialPdfLink": "",
        "faqs": []
    }

def ai_extract(text, title):
    if not client_gemini:
        return None
    prompt = f"""
Analyze the following government recruitment notification for "{title}".
Return ONLY a valid JSON object (no markdown, no backticks):
{{
  "organization": "Name of the government body",
  "eligibility": "Required qualification summary",
  "vacancies": "Total vacancies e.g. 500 Posts",
  "lastDate": "YYYY-MM-DD or empty string",
  "salary": "Salary or pay level info",
  "summary": "2-3 sentence summary",
  "seoTitle": "SEO title max 60 chars",
  "seoDescription": "SEO description max 155 chars",
  "officialPdfLink": "direct .pdf URL from official org website or empty string",
  "faqs": [
    {{"q": "Question", "a": "Answer"}}
  ]
}}

Article Text:
{text[:6000]}
"""
    models = ["gemini-2.5-flash-lite-preview-06-17", "gemini-2.5-flash", "gemini-2.0-flash"]
    for model in models:
        try:
            resp = client_gemini.models.generate_content(
                model=model, contents=prompt,
                config=gtypes.GenerateContentConfig(response_mime_type="application/json")
            )
            txt = resp.text.strip()
            if txt.startswith("```"): txt = txt.split("```")[1]
            if txt.startswith("json"): txt = txt[4:]
            return json.loads(txt.strip())
        except Exception as e:
            if "429" in str(e) or "EXHAUSTED" in str(e):
                print(f"   ⚠️  Model {model} rate-limited, trying next…")
                time.sleep(3)
            else:
                print(f"   ⚠️  Gemini error ({model}): {e}")
    return None

# ── Build FAQ HTML block ─────────────────────────────────────────────────
def faq_html(faqs):
    if not faqs: return ""
    out = (
        '<div class="gja-faq-section" style="border-top:2px solid #e2e8f0;padding-top:2rem;margin-top:2rem;">'
        '<h2 style="font-size:1.4rem;font-weight:bold;color:#1e3a8a;margin-bottom:1.2rem;">'
        "📋 Frequently Asked Questions</h2>"
    )
    for faq in faqs:
        q = faq.get("q","").strip()
        a = faq.get("a","").strip()
        if q and a:
            out += (
                f'<div style="margin-bottom:1rem;padding:.9rem 1rem;background:#f8fafc;'
                f'border-left:4px solid #2563eb;border-radius:0 8px 8px 0;">'
                f'<h4 style="margin:0 0 .4rem;font-weight:700;color:#1e293b;">❓ {q}</h4>'
                f'<p style="margin:0;color:#475569;font-size:.93rem;line-height:1.6;">{a}</p>'
                f"</div>"
            )
    out += "</div>"
    return out

# ── Extract official links from HTML ─────────────────────────────────────
def extract_links(html):
    soup = BeautifulSoup(html, "html.parser")
    apply_link = pdf_link = official_site = ""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True).lower()
        if "govtjobsalert.in" in href or not href.startswith("http"):
            continue
        if href.endswith(".pdf") or "notification" in text:
            if not pdf_link: pdf_link = href
        if "apply online" in text or "apply now" in text or "registration" in text:
            if not apply_link: apply_link = href
        if "official website" in text:
            official_site = href
    return apply_link, pdf_link, official_site

# ── Update job via API ────────────────────────────────────────────────────
def update_job(job_id, payload, token, dry_run=False):
    if dry_run:
        print(f"   [DRY-RUN] Would update job {job_id}")
        print(f"   Payload keys: {list(payload.keys())}")
        return True
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        r = requests.put(f"{API_URL}/{job_id}", json=payload, headers=headers, timeout=30)
        if r.status_code == 200:
            return True
        else:
            print(f"   ❌ API error {r.status_code}: {r.text[:300]}")
            return False
    except Exception as e:
        print(f"   ❌ Request error: {e}")
        return False

# ── Process one job ───────────────────────────────────────────────────────
def process_job(job, token, dry_run=False):
    title      = job.get("title", "Unknown")
    job_id     = job.get("_id") or job.get("id")
    source_url = job.get("sourceUrl", "")
    slug       = job.get("slug", "")

    if not source_url or "govtjobsalert.in" not in source_url:
        print(f"   ⏭️  Skipping (no govtjobsalert.in source): {title[:55]}")
        return False

    print(f"\n{'='*65}")
    print(f"🔧 Fixing: {title[:60]}")
    print(f"   Source: {source_url}")

    # 1. Scrape
    html, text = scrape_source(source_url)
    if not html:
        return False

    # 2. Extract links from scraped HTML
    apply_link, pdf_link, official_site = extract_links(html)

    # Use existing apply link if scraper found none
    if not apply_link:
        apply_link = job.get("applyLink", "") or official_site

    # 3. AI enrichment
    ai_data = ai_extract(text, title) if text else None
    if not ai_data:
        print("   ⚠️  AI failed, using basic parser.")
        ai_data = basic_extract(text or "", title)

    # 4. Resolve PDF link from AI
    ai_pdf = (ai_data.get("officialPdfLink") or "").strip()
    if ai_pdf and ai_pdf.startswith("http"):
        pdf_link = ai_pdf

    # 5. Build full description
    full_html = html + faq_html(ai_data.get("faqs", []))

    # 6. Build update payload
    last_date = ai_data.get("lastDate") or job.get("lastDate") or None
    payload = {
        "jobDescription": full_html,
        "description":    ai_data.get("summary", ""),
        "shortSummary":   ai_data.get("summary", "")[:300],
        "eligibility":    ai_data.get("eligibility") or job.get("eligibility") or "As per notification",
        "vacancies":      ai_data.get("vacancies") or job.get("vacancies") or "Various Vacancies",
        "salary":         ai_data.get("salary") or job.get("salary") or "As per notification",
        "metaTitle":      ai_data.get("seoTitle") or title[:60],
        "metaDescription":ai_data.get("seoDescription") or ai_data.get("summary","")[:155],
        "sourceUrl":      source_url,
        "sourceWebsite":  "govtjobsalert.in",
        "pdfLink":        pdf_link,
    }
    if apply_link:
        payload["applyLink"] = apply_link
    if last_date:
        payload["lastDate"] = last_date

    # 7. Update
    ok = update_job(job_id, payload, token, dry_run)
    if ok:
        print(f"   ✅ Updated! desc={len(full_html):,} chars | vac={payload['vacancies']} | sal={payload['salary']}")
        print(f"      apply={apply_link[:60]}")
        print(f"      pdf  ={pdf_link[:60]}")
    return ok

# ── Main ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Bulk-fix thin job posts on NextJobPost")
    parser.add_argument("--dry-run",  action="store_true", help="Preview only, no API writes")
    parser.add_argument("--limit",    type=int, default=0,  help="Max number of jobs to fix (0=all)")
    parser.add_argument("--source",   type=str, default="", help="Only fix jobs from this source URL substring")
    args = parser.parse_args()

    print("=" * 65)
    print("🏗️  NextJobPost — Bulk Job Description Fixer")
    print("=" * 65)
    if args.dry_run: print("🔍 DRY-RUN MODE — no changes will be saved\n")

    token = get_token()

    print("\n📥 Fetching all jobs from backend…")
    all_jobs = fetch_all_jobs(token)
    print(f"   Found {len(all_jobs)} total jobs.")

    # Filter thin jobs
    thin_jobs = [j for j in all_jobs if is_thin(j)]
    print(f"   Thin / empty descriptions: {len(thin_jobs)}")

    # Filter by source if specified
    if args.source:
        thin_jobs = [j for j in thin_jobs if args.source in (j.get("sourceUrl",""))]
        print(f"   After source filter: {len(thin_jobs)}")

    # Only govtjobsalert.in sourced ones can be auto-fixed
    fixable = [j for j in thin_jobs if "govtjobsalert.in" in (j.get("sourceUrl",""))]
    print(f"   Fixable (govtjobsalert.in source): {len(fixable)}")

    if args.limit > 0:
        fixable = fixable[:args.limit]
        print(f"   Limited to: {len(fixable)}")

    print(f"\n🚀 Starting fixes…")
    success = fail = skip = 0

    for i, job in enumerate(fixable, 1):
        print(f"\n[{i}/{len(fixable)}]", end="")
        ok = process_job(job, token, dry_run=args.dry_run)
        if ok:
            success += 1
        else:
            fail += 1

        if i < len(fixable):
            time.sleep(DELAY_BETWEEN)

    print(f"\n\n{'='*65}")
    print(f"✅ Done! Success: {success} | Failed: {fail} | Total fixed: {len(fixable)}")
    print(f"   Jobs with no govtjobsalert.in source (skipped): {len(thin_jobs) - len(fixable)}")
    print(f"   IT/private jobs need manual content entry.")

if __name__ == "__main__":
    main()
