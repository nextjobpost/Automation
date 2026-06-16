import os
import re
import json
import sys
import requests
import hashlib
import time
import logging
from bs4 import BeautifulSoup
from datetime import datetime, date
from urllib.parse import urlparse, urljoin
from slugify import slugify

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

# User-Agent header for HTTP requests
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Import core config, database, and helpers from scrape_govt_jobs.py
try:
    from scrape_govt_jobs import (
        API_KEY,
        API_TOKEN,
        API_URL,
        ADMIN_URL,
        client_gemini,
        clean_detail_html,
        enrich_content_with_ai,
        enrich_content_basic,
        extract_govt_links,
        format_faq_html,
        sanitize_description_links,
        fetch_recent_jobs,
        find_existing_job,
        get_auth_token
    )
except ImportError as e:
    print(f"❌ Failed to import helpers from scrape_govt_jobs.py: {e}")
    sys.exit(1)

import database

# Setup Logging for this script
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- INDIVIDUAL LISTING EXTRACTORS ---

def extract_sarkariresult_listings(soup, base_url):
    """Extracts job detail links from SarkariResult.com Latest Jobs page."""
    listings = []
    # All links on SarkariResult latest jobs page
    for a in soup.find_all("a"):
        href = a.get("href", "")
        title = a.text.strip()
        if not href or len(title) < 8:
            continue
            
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        
        # We target specific paths representing job pages (e.g. year paths, specific departments)
        # Exclude navigation and non-job categories
        path = parsed.path.lower()
        if "sarkariresult.com" in parsed.netloc:
            # Check if it has a subfolder structure (e.g., /2026/, /ssc/, /bank/, /railway/)
            # and is not a main directory listing or helper page
            is_valid_post = (
                re.search(r'^/(?:202\d|ssc|upsssc|bank|railway|rpsc|hssc|delhi|upsc|navy|airforce|cisf|bsf|police|army|court)/', path)
                and not any(x in path for x in ["latestjob", "result", "admitcard", "syllabus", "answerkey", "admission", "contactus", "about-us"])
            )
            if is_valid_post:
                listings.append((title, full_url))
    return listings

def extract_freejobalert_listings(soup, base_url):
    """Extracts job detail links from FreeJobAlert.com homepage/latest posts."""
    listings = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        title = a.text.strip()
        if not href or len(title) < 8:
            continue
            
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        
        # We target links matching article format /articles/[job-title]-[id]
        if "freejobalert.com" in parsed.netloc:
            if "/articles/" in parsed.path and re.search(r'-\d+/?$', parsed.path):
                # Clean up title by removing trailing badge texts like "Online Form 2026"
                listings.append((title, full_url))
    return listings

def extract_sarkariexam_listings(soup, base_url):
    """Extracts job detail links from SarkariExam.com homepage."""
    listings = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        title = a.text.strip()
        if not href or len(title) < 8:
            continue
            
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        
        # Target post subpages while avoiding categories and tools
        if "sarkariexam.com" in parsed.netloc:
            path = parsed.path.lower()
            # Must not be a category, tag, search, page number, contact, etc.
            # And path should contain multiple characters (not empty or just /)
            is_valid = (
                len(path.split("/")) > 2
                and not any(x in path for x in ["/category/", "/tag/", "/contact", "/about", "/disclaimer", "/privacy-policy", "/search", "/page/"])
                and not any(domain in full_url for domain in ["sarkariresulttools.net", "youtube.com", "instagram.com"])
            )
            if is_valid:
                listings.append((title, full_url))
    return listings

def extract_indgovtjobs_listings(soup, base_url):
    """Extracts job detail links from IndGovtJobs.in homepage."""
    listings = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        title = a.text.strip()
        if not href or len(title) < 8:
            continue
            
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        
        # WordPress blog posts use /YYYY/MM/title.html format
        if "indgovtjobs.in" in parsed.netloc:
            if re.search(r'/\d{4}/\d{2}/', parsed.path) and parsed.path.endswith(".html"):
                # Avoid static pages
                if not any(x in parsed.path.lower() for x in ["no-exam-government-jobs.html", "employment-news.html", "last-date-government-jobs.html"]):
                    listings.append((title, full_url))
    return listings

def extract_recruitmentguru_listings(soup, base_url):
    """Extracts job detail links from Recruitment.guru homepage."""
    listings = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        title = a.text.strip()
        if not href or len(title) < 8:
            continue
            
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        
        if "recruitment.guru" in parsed.netloc:
            path = parsed.path.lower()
            # Matches post formats ending in a post ID (e.g. /post-name/12345 or /job/post-name/12345)
            if re.search(r'/\d+/?$', path):
                if not any(x in path for x in ["/category/", "/tag/", "/contact", "/about"]):
                    listings.append((title, full_url))
    return listings

# --- MAIN SCRAPER LOOP ---

def scrape_site(site_name, site_url, extractor_func):
    """Generalized function to scrape job postings from a target site and queue them."""
    logging.info(f"\n========================================\n🌐 Scraping Site: {site_name} ({site_url})\n========================================")
    
    try:
        response = requests.get(site_url, headers=headers, timeout=15)
        if response.status_code != 200:
            logging.error(f"❌ Failed to load page: {site_url} (Status: {response.status_code})")
            return
    except Exception as e:
        logging.error(f"❌ Error fetching listing page: {e}")
        return

    soup = BeautifulSoup(response.content, "html.parser")
    listings = extractor_func(soup, site_url)
    
    # Remove duplicates within the extracted batch
    unique_listings = []
    seen_urls = set()
    for title, url in listings:
        if url not in seen_urls:
            seen_urls.add(url)
            unique_listings.append((title, url))
            
    logging.info(f"Found {len(unique_listings)} potential job listings.")
    
    recent_jobs = fetch_recent_jobs()
    new_jobs_queued = 0
    
    for title, detail_url in unique_listings:
        # Clean title & normalize formatting
        raw_title = title.replace("\u2013", "-").replace("\u2014", "-").strip()
        job_hash = hashlib.md5(detail_url.encode()).hexdigest()
        
        # Check local DB seen cache
        if database.is_job_seen(job_hash):
            continue
            
        logging.info(f"\n🚀 New Listing Found: {raw_title}")
        logging.info(f"🔗 Detail URL: {detail_url}")
        
        # 1. Fetch detail page HTML
        try:
            detail_resp = requests.get(detail_url, headers=headers, timeout=15)
            if detail_resp.status_code != 200:
                logging.warning(f"⚠️ Failed to fetch detail page: {detail_url} (Status: {detail_resp.status_code})")
                continue
        except Exception as e:
            logging.warning(f"⚠️ Error fetching detail page: {e}")
            continue
            
        # 2. Extract and clean the main content block
        detail_html = clean_detail_html(detail_resp.text)
        if not detail_html or len(detail_html) < 200:
            logging.warning("⚠️ Entry content too short or empty. Skipping.")
            continue
            
        # 3. Enrich page content using Gemini AI
        ai_data = enrich_content_with_ai(detail_html, raw_title)
        if not ai_data:
            logging.warning("⚠️ AI Enrichment failed. Falling back to basic regex parser...")
            ai_data = enrich_content_basic(detail_html, raw_title)
            
        org = ai_data.get("organization", "Government Department")
        post_name = ai_data.get("postName", raw_title)
        eligibility = ai_data.get("eligibility", "As per notification")
        vacancies = ai_data.get("vacancies", "Various Vacancies")
        salary = ai_data.get("salary", "Best in Industry")
        last_date = ai_data.get("lastDate", None)
        
        # Check last date expiration
        if last_date:
            last_date_str = str(last_date).strip()
            if last_date_str.lower() not in ["not mentioned", "not specified", "not disclosed", "confidential", ""]:
                parsed_date = None
                for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%S', '%d-%m-%Y', '%Y/%m/%d'):
                    try:
                        parsed_date = datetime.strptime(last_date_str, fmt).date()
                        break
                    except ValueError:
                        continue
                
                if parsed_date and parsed_date < date.today():
                    logging.info(f"⚠️ Skipping expired job: '{raw_title}'. Last date '{last_date_str}' is in the past (today is {date.today()}).")
                    database.mark_job_seen(job_hash)
                    continue

        summary = ai_data.get("summary", raw_title)
        seo_title = ai_data.get("seoTitle", raw_title)
        seo_desc = ai_data.get("seoDescription", raw_title)
        faqs = ai_data.get("faqs", [])
        
        # 4. Extract official links
        govt_links = extract_govt_links(detail_html)
        extracted_apply_link = govt_links["applyLink"]
        
        # Strip source domain leaks from the official links
        domain_name = urlparse(site_url).netloc
        if not extracted_apply_link or domain_name in extracted_apply_link:
            extracted_apply_link = govt_links["officialWebsite"] or ""
            if domain_name in extracted_apply_link:
                extracted_apply_link = ""
                
        official_pdf_ai = ai_data.get("officialPdfLink", "").strip() if isinstance(ai_data, dict) else ""
        extracted_pdf_link = ""
        if official_pdf_ai and official_pdf_ai.startswith("http") and (official_pdf_ai.endswith(".pdf") or "pdf" in official_pdf_ai.lower()):
            extracted_pdf_link = official_pdf_ai
            
        if not extracted_pdf_link:
            extracted_pdf_link = govt_links["pdfLink"]
            if extracted_pdf_link and (domain_name in extracted_pdf_link or "nextjobpost.in" in extracted_pdf_link):
                extracted_pdf_link = ""

        # Sanitize HTML body and replace competitor file links
        sanitized_detail_html = sanitize_description_links(
            detail_html,
            official_pdf_url=extracted_pdf_link,
            official_apply_url=extracted_apply_link,
            official_website_url=govt_links.get("officialWebsite")
        )
        
        # Append FAQs at the end of the HTML body
        faq_html = format_faq_html(faqs)
        full_description_html = sanitized_detail_html + faq_html
        
        # 5. Build final job payload
        slug_base = slugify(raw_title)
        url_hash = hashlib.md5(detail_url.encode()).hexdigest()[:5]
        slug = f"{slug_base}-{url_hash}"

        queue_job = {
            "title": raw_title,
            "slug": slug,
            "company": org,
            "location": "India",
            "type": "Full-Time",
            "experience": "As per notification",
            "eligibility": eligibility,
            "vacancies": vacancies,
            "salary": salary,
            "applyLink": extracted_apply_link,
            "education": eligibility,
            "batch": "",
            "lastDate": last_date if last_date else None,
            "jobDescription": full_description_html,
            "description": summary,
            "shortSummary": summary,
            "metaTitle": seo_title,
            "metaDescription": seo_desc,
            "isGovernment": True,
            "postType": "Government Job",
            "sourceWebsite": domain_name,
            "sourceUrl": detail_url,
            "importantDates": "As per official notification",
            "pdfLink": extracted_pdf_link,
            "isActive": True,
            "whatsapp": "https://chat.whatsapp.com/LVpuUJluTpUEdIc4daAemQ",
            "telegram": "https://t.me/nextjobpost"
        }

        # Semantic Deduplication against live website API
        title_str = str(queue_job.get('title', '')).lower().strip()
        comp_str = str(queue_job.get('company', '')).lower().strip()
        semantic_hash = hashlib.md5(f"{title_str}::{comp_str}".encode()).hexdigest()
        
        existing_job = find_existing_job(detail_url, raw_title, org, recent_jobs)
        if existing_job:
            # Job already posted on live website, skip and mark seen
            logging.info(f"⚠️ Job '{raw_title}' already exists on backend. Skipping.")
            database.mark_job_seen(job_hash)
            database.mark_job_seen(semantic_hash)
            continue
            
        # Semantic check in local DB
        if database.is_job_seen(semantic_hash):
            logging.info(f"⚠️ Semantic duplicate detected in local DB, skipping: {raw_title}")
            database.mark_job_seen(job_hash)
            continue

        # Add to SQLite queue database
        try:
            if database.add_job_to_queue(queue_job, job_hash, image_path="", is_government=True):
                logging.info(f"📥 Queued government job from {site_name}: {raw_title}")
                database.mark_job_seen(job_hash)
                database.mark_job_seen(semantic_hash)
                new_jobs_queued += 1
            else:
                logging.warning(f"⚠️ Failed to queue or already in queue: {raw_title}")
        except Exception as e:
            logging.error(f"❌ Failed to write to SQLite: {e}")

    logging.info(f"Finished scraping {site_name}. Queued {new_jobs_queued} new job listings.")

def main():
    logging.info("========================================")
    logging.info("🏛️ Scraper Extension for Additional Sites 🏛️")
    logging.info("========================================")
    
    # Re-authenticate API token just in case
    get_auth_token()
    
    # Scrape each site
    scrape_site("Sarkari Result", "https://www.sarkariresult.com/latestjob/", extract_sarkariresult_listings)
    scrape_site("FreeJobAlert", "https://www.freejobalert.com/", extract_freejobalert_listings)
    scrape_site("Sarkari Exam", "https://www.sarkariexam.com/", extract_sarkariexam_listings)
    scrape_site("IndGovtJobs", "https://www.indgovtjobs.in/", extract_indgovtjobs_listings)
    scrape_site("Recruitment Guru", "https://www.recruitment.guru/", extract_recruitmentguru_listings)
    
    logging.info("✅ All additional scraper sources successfully processed.")

if __name__ == "__main__":
    main()
