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
import xml.etree.ElementTree as ET

# Force UTF-8 encoding for stdout/stderr on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass

# ─── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# ─── Import shared helpers from govt scraper ───────────────────────────────
try:
    from scrape_govt_jobs import (
        API_TOKEN,
        API_URL,
        ADMIN_URL,
        format_faq_html,
        fetch_recent_jobs,
        find_existing_job,
        get_auth_token,
    )
except ImportError as e:
    logging.error(f"Failed to import helpers from scrape_govt_jobs.py: {e}")
    sys.exit(1)

import database
from dotenv import load_dotenv
load_dotenv()

# ─── HTTP Headers ──────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ═══════════════════════════════════════════════════════════════════════════
#  AI ENRICHMENT — Private Job Specific
# ═══════════════════════════════════════════════════════════════════════════

def enrich_private_job_basic(html_content, title):
    """Regex/BS4 fallback enrichment for private jobs when AI is unavailable."""
    soup = BeautifulSoup(html_content, "html.parser")
    text = re.sub(r'\s+', ' ', soup.get_text(separator=" ")).strip()

    # Company: try to extract from title delimiters
    company = "Top Company"
    for sep in [" at ", " @ ", " - ", " | "]:
        if sep.lower() in title.lower():
            parts = title.split(sep)
            candidate = parts[-1].strip()
            if 3 < len(candidate) < 60:
                company = candidate
                break

    # Location
    location = "Pan India"
    loc_m = re.search(
        r'\b(bangalore|bengaluru|mumbai|delhi|chennai|hyderabad|pune|kolkata|'
        r'noida|gurugram|gurgaon|ahmedabad|remote|work from home)\b',
        text, re.IGNORECASE
    )
    if loc_m:
        location = loc_m.group(0).title()

    # Experience
    experience = "Fresher / 0-2 Years"
    exp_m = re.search(r'(\d+)\s*[-–to]+\s*(\d+)\s*years?\s*(of\s*)?(experience|exp)?', text, re.IGNORECASE)
    if exp_m:
        experience = f"{exp_m.group(1)}-{exp_m.group(2)} Years"

    # Salary — skip if looks like a fee
    salary = "Best in Industry"
    sal_m = re.search(
        r'(?:salary|ctc|package|stipend|compensation)[^0-9\n]{0,30}'
        r'(?:rs\.?|inr|₹)?\s*([\d,.]+)\s*(?:lpa|lakh|k/month|per month|/-)?',
        text, re.IGNORECASE
    )
    if sal_m:
        salary = f"{sal_m.group(1).strip()} LPA"

    # Education
    education = "Any Graduate"
    for pat in [r'\bB\.?Tech\b', r'\bBE\b', r'\bMBA\b', r'\bBCA\b', r'\bMCA\b',
                r'\bB\.?Sc\b', r'\bM\.?Tech\b', r'\bAny Graduate\b']:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            education = m.group(0)
            break

    return {
        "company":         company,
        "location":        location,
        "experience":      experience,
        "salary":          salary,
        "education":       education,
        "batch":           "",
        "jobType":         "Full-Time",
        "skills":          [],
        "responsibilities":[],
        "requirements":    [],
        "lastDate":        "",
        "summary":         title,
        "seoTitle":        title[:60],
        "seoDescription":  f"Apply for {title}. Great opportunity at {company} for freshers and experienced candidates.",
        "faqs":            [],
    }


# ═══════════════════════════════════════════════════════════════════════════
#  HTML CLEANER — Private job detail pages
# ═══════════════════════════════════════════════════════════════════════════

def clean_private_job_html(html_content):
    """Strips ads, nav, footers, and noise from a private job detail page."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")

    for tag in soup(["script", "style", "noscript", "iframe", "ins", "aside",
                     "header", "footer", "nav"]):
        tag.decompose()

    for tag in list(soup.find_all(True)):
        if not tag.parent:
            continue
        class_str = " ".join(tag.get("class", [])).lower()
        id_str    = (tag.get("id") or "").lower()
        if any(kw in class_str or kw in id_str for kw in [
            "advertisement", "adsbygoogle", "social-share", "share-box",
            "related-jobs", "newsletter", "popup", "cookie", "sidebar", "banner",
            "follow-us", "subscribe"
        ]):
            tag.decompose()
            continue
        if tag.name == "a":
            href = tag.get("href", "").lower()
            if any(d in href for d in ["whatsapp.com", "t.me", "telegram", "instagram.com",
                                        "facebook.com", "twitter.com", "youtube.com"]):
                tag.decompose()

    linkedin_desc = soup.find(class_=re.compile(r'show-more-less-html__markup|description__text'))
    if linkedin_desc:
        main = linkedin_desc
    else:
        main = (
            soup.find("div", {"class": re.compile(r'\bdescription\b|job.?detail|job.?desc|job.?content|main.?content|job.?info', re.I)})
            or soup.find("article")
            or soup.find("main")
            or soup.find("div", {"id": re.compile(r'content|main|job', re.I)})
            or soup.body
            or soup
        )

    # Beautify headings (e.g. <p><strong>Heading</strong></p> to <h3>Heading</h3>)
    for p in list(main.find_all("p")):
        if not p.contents:
            continue
        first_child = p.contents[0]
        if first_child.name in ["strong", "b"]:
            strong_text = first_child.get_text().strip()
            if strong_text and len(strong_text) < 70:
                # We create a new h3 element
                h3 = soup.new_tag("h3")
                h3.string = strong_text
                p.insert_before(h3)
                first_child.extract()
                
                # Remove leading <br> elements from the paragraph content
                while p.contents and (p.contents[0].name == "br" or (isinstance(p.contents[0], str) and not p.contents[0].strip())):
                    p.contents[0].extract()

    return str(main)


# ═══════════════════════════════════════════════════════════════════════════
#  LISTING EXTRACTORS — one per website
# ═══════════════════════════════════════════════════════════════════════════


def extract_linkedin_jobs_public(limit=25):
    """Fetches job listings from LinkedIn's public guest search API using multiple search keywords."""
    listings = []
    seen = set()
    
    keywords_list = [
        "Software Developer",
        "Software Engineer",
        "Frontend Developer",
        "Backend Developer",
        "Full Stack Developer",
        "Python Developer",
        "Java Developer",
        "IT Internship",
        "Web Developer",
        "React Developer",
        "Data Analyst",
        "DevOps Engineer",
        "Software Intern",
        "Machine Learning Engineer",
        "Cloud Engineer"
    ]
    
    for kw in keywords_list:
        if len(listings) >= limit:
            break
            
        kw_encoded = requests.utils.quote(kw)
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={kw_encoded}&location=India&start=0"
        
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                logging.warning(f"LinkedIn Guest API Error {resp.status_code} for query: {kw}")
                continue
            
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all("li")
            
            for card in cards:
                title_el = card.find("h3", class_="base-search-card__title")
                link_el = card.find("a", class_="base-card__full-link")
                company_el = card.find("h4", class_="base-search-card__subtitle")
                
                if title_el and link_el:
                    title = title_el.get_text(strip=True)
                    link = link_el.get("href").split("?")[0]
                    company = company_el.get_text(strip=True) if company_el else "Top Company"
                    
                    if link not in seen:
                        seen.add(link)
                        listings.append((title, link, None, company))
                        if len(listings) >= limit:
                            break
            # Add a brief delay between queries to respect rate limits
            time.sleep(1.0)
        except Exception as e:
            logging.warning(f"LinkedIn public API fetch error for query '{kw}': {e}")
            
    return listings


def extract_adzuna_jobs(limit=30):
    """Fetches job listings from Adzuna API (Free Tier)."""
    listings = []
    seen = set()
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")

    if not app_id or not app_key:
        logging.warning("Missing ADZUNA_APP_ID or ADZUNA_APP_KEY in environment. Skipping Adzuna.")
        return listings

    # Country code 'in' for India, category 'it-jobs' or search 'software'
    url = f"https://api.adzuna.com/v1/api/jobs/in/search/1?app_id={app_id}&app_key={app_key}&results_per_page={limit}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            logging.warning(f"Adzuna API Error {resp.status_code}: {resp.text}")
            return listings

        data = resp.json()
        results = data.get("results", [])

        for job in results:
            title = job.get("title", "")
            # Adzuna provides a direct redirect link
            link = job.get("redirect_url", "")
            desc = job.get("description", "")
            company_obj = job.get("company", {})
            company_name = company_obj.get("display_name", "Top Company")
            
            # Clean HTML tags from title if any
            title = BeautifulSoup(title, "html.parser").get_text(strip=True)

            if title and link and link not in seen:
                seen.add(link)
                listings.append((title, link, desc, company_name))
                if len(listings) >= limit:
                    return listings
    except Exception as e:
        logging.warning(f"Adzuna official API fetch error: {e}")

    return listings


def extract_weworkremotely_rss(limit=30):
    """Fetches job listings from WeWorkRemotely RSS feeds."""
    listings = []
    seen = set()
    rss_urls = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    ]
    for rss_url in rss_urls:
        try:
            resp = requests.get(rss_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                logging.warning(f"WeWorkRemotely RSS {resp.status_code}: {rss_url}")
                continue
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                t_el = item.find("title")
                l_el = item.find("link")
                if t_el is None or l_el is None:
                    continue
                title = (t_el.text or "").strip()
                link  = (l_el.text or "").strip()
                # WeWorkRemotely title format: "Company: Job Title - Location"
                # Clean it: extract just the job title part
                if ": " in title:
                    title = title.split(": ", 1)[1].strip()
                if not title or not link or link in seen or len(title) < 5:
                    continue
                seen.add(link)
                listings.append((title, link))
                if len(listings) >= limit:
                    return listings
        except Exception as e:
            logging.warning(f"WeWorkRemotely RSS error: {e}")
    return listings


def extract_freshersworld_listings(limit=30):
    """Extracts fresher job listings from Freshersworld.com."""
    listings = []
    seen = set()
    search_urls = [
        "https://www.freshersworld.com/jobs/jobsearch/it-software-jobs-for-freshers-0-3-years-experience",
        "https://www.freshersworld.com/jobs/jobsearch/engineering-jobs-for-freshers",
        "https://www.freshersworld.com/jobs/jobsearch/bca-mca-bsc-jobs-for-freshers",
    ]
    for url in search_urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                logging.warning(f"Freshersworld {resp.status_code}: {url}")
                continue
            soup = BeautifulSoup(resp.content, "html.parser")

            # "View & Apply" buttons link directly to job detail pages
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                full = ("https://www.freshersworld.com" + href) if href.startswith("/") else href

                # Match: freshersworld.com/jobs/<title-slug>-<5+ digit id>
                if re.search(r'freshersworld\.com/jobs/[a-z0-9\-]+-\d{5,}/?', full) and full not in seen:
                    # Find nearest heading for the real job title
                    parent = a.find_parent(["div", "li", "article", "section"])
                    title = ""
                    if parent:
                        h = parent.find(["h2", "h3", "h4", "strong", "b"])
                        title = h.get_text(strip=True) if h else ""
                    if not title or len(title) < 5:
                        # Derive title from URL slug
                        slug_part = re.search(r'/jobs/([a-z0-9\-]+)-\d{5,}', full)
                        title = slug_part.group(1).replace("-", " ").title() if slug_part else "Fresher Job"

                    seen.add(full)
                    listings.append((title, full))
                    if len(listings) >= limit:
                        return listings
        except Exception as e:
            logging.warning(f"Freshersworld fetch error: {e}")
    return listings


def extract_internshala_listings(limit=30):
    """Extracts job listings from Internshala.com — India's top fresher job portal."""
    listings = []
    seen = set()
    search_urls = [
        "https://internshala.com/jobs/fresher-jobs/",
        "https://internshala.com/jobs/computer-science-jobs/",
        "https://internshala.com/jobs/web-development-jobs/",
    ]
    for url in search_urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                logging.warning(f"Internshala {resp.status_code}: {url}")
                continue
            soup = BeautifulSoup(resp.content, "html.parser")

            # Internshala job links: /jobs/<slug>-<id> OR /job-detail/<id>
            for a in soup.find_all("a", href=True):
                href  = a.get("href", "").strip()
                title = a.get_text(strip=True)
                full  = urljoin("https://internshala.com", href)

                # Match patterns like /jobs/some-title-12345678 or /job-detail/12345
                is_job = (
                    re.search(r'internshala\.com/jobs/[a-z0-9\-]+-\d{5,}/?$', full, re.I)
                    or re.search(r'internshala\.com/job-detail/\d+', full, re.I)
                )
                if is_job and full not in seen and len(title) >= 5:
                    # Derive title from URL if anchor text is unhelpful
                    if title.lower() in ["view", "apply", "view & apply", ""]:
                        slug = re.search(r'/jobs/([a-z0-9\-]+)-\d+/?$', full, re.I)
                        title = slug.group(1).replace("-", " ").title() if slug else title
                    seen.add(full)
                    listings.append((title, full))
                    if len(listings) >= limit:
                        return listings
        except Exception as e:
            logging.warning(f"Internshala fetch error: {e}")
    return listings


def extract_workatastartup_listings(limit=25):
    """Extracts job listings from WorkAtAStartup.in (AngelList India ecosystem)."""
    listings = []
    seen = set()
    try:
        resp = requests.get(
            "https://www.workatastartup.com/jobs?role=engineering&stage=all&salary=0",
            headers=HEADERS, timeout=15
        )
        if resp.status_code != 200:
            logging.warning(f"WorkAtAStartup {resp.status_code}")
            return listings
        soup = BeautifulSoup(resp.content, "html.parser")
        for a in soup.find_all("a", href=True):
            href  = a.get("href", "").strip()
            title = a.get_text(strip=True)
            full  = urljoin("https://www.workatastartup.com", href)
            # Job pages: /jobs/<id>
            if re.search(r'workatastartup\.com/jobs/\d+', full) and full not in seen and len(title) >= 8:
                seen.add(full)
                listings.append((title, full))
                if len(listings) >= limit:
                    break
    except Exception as e:
        logging.warning(f"WorkAtAStartup fetch error: {e}")
    return listings


def build_beautiful_private_job_desc(raw_title, company, location, job_type, experience, salary, education, batch, last_date, skills, resp_list, req_list, summary, detail_html, faqs):
    # 1. Key Highlights Table
    batch_tr = f"<tr><td><strong>Eligible Batches</strong></td><td>{batch}</td></tr>" if batch else ""
    last_date_tr = f"<tr><td><strong>Last Date to Apply</strong></td><td>{last_date}</td></tr>" if last_date else ""
    
    table_html = f"""
    <figure class="wp-block-table">
      <table>
        <tbody>
          <tr>
            <td><strong>Hiring Company</strong></td>
            <td>{company}</td>
          </tr>
          <tr>
            <td><strong>Job Title</strong></td>
            <td>{raw_title}</td>
          </tr>
          <tr>
            <td><strong>Location</strong></td>
            <td>{location}</td>
          </tr>
          <tr>
            <td><strong>Employment Type</strong></td>
            <td>{job_type}</td>
          </tr>
          <tr>
            <td><strong>Experience Required</strong></td>
            <td>{experience}</td>
          </tr>
          <tr>
            <td><strong>Salary / CTC</strong></td>
            <td>{salary}</td>
          </tr>
          <tr>
            <td><strong>Education Qualification</strong></td>
            <td>{education}</td>
          </tr>
          {batch_tr}
          {last_date_tr}
        </tbody>
      </table>
    </figure>
    """

    # 2. Lists for Skills, Responsibilities, Requirements
    skills_html = ""
    if skills:
        skills_items = "".join(f"<li>{s}</li>" for s in skills if s)
        if skills_items:
            skills_html = f"<h3>Key Skills Required</h3><ul>{skills_items}</ul>"

    resp_html = ""
    if resp_list:
        resp_items = "".join(f"<li>{r}</li>" for r in resp_list if r)
        if resp_items:
            resp_html = f"<h3>Roles &amp; Responsibilities</h3><ul>{resp_items}</ul>"

    req_html = ""
    if req_list:
        req_items = "".join(f"<li>{rq}</li>" for rq in req_list if rq)
        if req_items:
            req_html = f"<h3>Job Requirements &amp; Eligibility</h3><ul>{req_items}</ul>"

    # 3. Standard Sections
    about_company = f"{company} is a leading global technology and services organization known for delivering innovative solutions and cultivating a growth-oriented workforce."
    why_join = "This role offers an exceptional opportunity to collaborate with industry professionals on impactful projects, accelerate your skill development, and build a rewarding long-term career."
    how_to_apply = f"To apply for this role, click on the application link below to navigate to the official {company} careers page, fill out the application form with your details, upload your resume, and submit."
    final_thoughts = "Make sure to apply as soon as possible before the application window closes. Share this opportunity with your friends who might be interested."

    # 4. FAQs
    faq_html = ""
    if faqs:
        faq_html = format_faq_html(faqs)

    # 5. Cleaned Original Description
    original_description_html = ""
    if detail_html and len(detail_html.strip()) > 50:
        original_description_html = f"""
        <h3>Original Job Details / Description</h3>
        <div class="original-description-box" style="border-left: 3px solid #ccc; padding-left: 15px; margin-top: 15px;">
            {detail_html}
        </div>
        """

    full_desc = f"""
    <div>
      <h2>Career Opportunity: {raw_title} at {company}</h2>
      <p>{summary}</p>
      
      <h3>Key Highlights &amp; Job Details</h3>
      {table_html}
      
      {skills_html}
      {resp_html}
      {req_html}
      
      <h3>About {company}</h3>
      <p>{about_company}</p>
      
      <h3>Why You Should Join</h3>
      <p>{why_join}</p>
      
      <h3>How to Apply</h3>
      <p>{how_to_apply}</p>
      
      <h3>Final Thoughts</h3>
      <p>{final_thoughts}</p>
      
      {original_description_html}
      {faq_html}
    </div>
    """
    return full_desc


# ═══════════════════════════════════════════════════════════════════════════
#  CORE PROCESSOR — enriches and queues a single private job
# ═══════════════════════════════════════════════════════════════════════════

def process_private_job(title, detail_url, site_name, recent_jobs, provided_html=None, provided_company=None):
    """Fetches, enriches, deduplicates and queues a single private job."""
    raw_title = title.replace("\u2013", "-").replace("\u2014", "-").strip()
    job_hash  = hashlib.md5(detail_url.encode()).hexdigest()

    if database.is_job_seen(job_hash):
        return False

    logging.info(f"  🚀 [{site_name}] {raw_title[:70]}")

    if provided_html is not None:
        detail_html = provided_html
        if len(detail_html.strip()) < 15:
            logging.warning("  ⚠️ Provided API content too short or empty. Skipping.")
            return False
    else:
        # Fetch detail page
        try:
            resp = requests.get(detail_url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                logging.warning(f"  ⚠️ HTTP {resp.status_code}: {detail_url}")
                return False
        except Exception as e:
            logging.warning(f"  ⚠️ Fetch error: {e}")
            return False

        # Clean HTML
        detail_html = clean_private_job_html(resp.text)
        if not detail_html or len(detail_html) < 150:
            logging.warning("  ⚠️ Page content too short. Skipping.")
            return False

    # Check for internship or remote explicitly
    title_lower = raw_title.lower()
    content_lower = detail_html.lower()
    
    is_internship = any(kw in title_lower or kw in content_lower for kw in ["intern", "internship"])
    is_remote = any(kw in title_lower or kw in content_lower for kw in ["remote", "work from home", "wfh"])
    
    if site_name != "Adzuna API" and not (is_internship or is_remote):
        logging.info(f"  ⏭️ Skipping: Not an internship or remote role ('{raw_title[:40]}...')")
        return False

    # Basic extraction
    ai_data = enrich_private_job_basic(detail_html, raw_title)

    if provided_company and len(provided_company) > 1:
        company = provided_company
    else:
        company = ai_data.get("company", "Top Company")
    location    = ai_data.get("location",          "Pan India")
    experience  = ai_data.get("experience",        "Fresher / 0-2 Years")
    salary      = ai_data.get("salary",            "Best in Industry")
    education   = ai_data.get("education",         "Any Graduate")
    batch       = ai_data.get("batch",             "")
    job_type    = ai_data.get("jobType",           "Full-Time")
    skills      = ai_data.get("skills",            [])
    resp_list   = ai_data.get("responsibilities",  [])
    req_list    = ai_data.get("requirements",      [])
    last_date   = ai_data.get("lastDate",          "")
    summary     = ai_data.get("summary",           raw_title)
    seo_title   = ai_data.get("seoTitle",          raw_title[:60])
    seo_desc    = ai_data.get("seoDescription",    "")
    faqs        = ai_data.get("faqs",              [])

    # Skip expired listings
    if last_date:
        for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d'):
            try:
                if datetime.strptime(last_date, fmt).date() < date.today():
                    logging.info(f"  ⚠️ Expired ({last_date}). Skipping.")
                    database.mark_job_seen(job_hash)
                    return False
                break
            except ValueError:
                continue

    # Build full description
    full_description_html = build_beautiful_private_job_desc(
        raw_title=raw_title,
        company=company,
        location=location,
        job_type=job_type,
        experience=experience,
        salary=salary,
        education=education,
        batch=batch,
        last_date=last_date,
        skills=skills,
        resp_list=resp_list,
        req_list=req_list,
        summary=summary,
        detail_html=detail_html,
        faqs=faqs
    )

    # Build slug
    slug_base = slugify(raw_title)
    url_hash  = hashlib.md5(detail_url.encode()).hexdigest()[:5]
    slug      = f"{slug_base}-{url_hash}"

    # Build private job payload
    queue_job = {
        "title":            raw_title,
        "slug":             slug,
        "company":          company,
        "location":         location,
        "type":             job_type,
        "experience":       experience,
        "salary":           salary,
        "education":        education,
        "batch":            batch,
        "skills":           skills if isinstance(skills, list) else [],
        "responsibilities": resp_list if isinstance(resp_list, list) else [],
        "requirements":     req_list if isinstance(req_list, list) else [],
        "applyLink":        detail_url,
        "lastDate":         last_date if last_date else None,
        "jobDescription":   full_description_html,
        "description":      summary,
        "shortSummary":     summary,
        "metaTitle":        seo_title,
        "metaDescription":  seo_desc,
        "isGovernment":     False,
        "postType":         "Private Job",
        "sourceWebsite":    urlparse(detail_url).netloc,
        "sourceUrl":        detail_url,
        "isActive":         True,
        "whatsapp":         "https://chat.whatsapp.com/LVpuUJluTpUEdIc4daAemQ",
        "telegram":         "https://t.me/nextjobpost",
    }

    # Deduplication
    semantic_hash = hashlib.md5(
        f"{raw_title.lower()}::{company.lower()}".encode()
    ).hexdigest()

    existing = find_existing_job(detail_url, raw_title, company, recent_jobs)
    if existing:
        logging.info(f"  ⚠️ Already on website: '{raw_title}'. Skipping.")
        database.mark_job_seen(job_hash)
        database.mark_job_seen(semantic_hash)
        return False

    if database.is_job_seen(semantic_hash):
        logging.info(f"  ⚠️ Semantic duplicate: '{raw_title}'. Skipping.")
        database.mark_job_seen(job_hash)
        return False

    # Queue
    try:
        if database.add_job_to_queue(queue_job, job_hash, image_path="", is_government=False):
            logging.info(f"  📥 Queued private job from {site_name}: {raw_title}")
            database.mark_job_seen(job_hash)
            database.mark_job_seen(semantic_hash)
            return True
        else:
            logging.warning(f"  ⚠️ Already in queue or failed to add: {raw_title}")
    except Exception as e:
        logging.error(f"  ❌ SQLite error: {e}")

    return False


# ═══════════════════════════════════════════════════════════════════════════
#  SITE RUNNERS
# ═══════════════════════════════════════════════════════════════════════════

def run_scraper(name, fetch_fn, recent_jobs, limit=25, delay=1.5, global_state=None):
    """Generic runner: fetches listings from fetch_fn and processes each one."""
    if global_state is None:
        global_state = {"total_queued": 0}
        
    logging.info(f"\n{'='*48}")
    logging.info(f"🌐 Scraping: {name}")
    logging.info(f"{'='*48}")
    listings = fetch_fn(limit)
    logging.info(f"Found {len(listings)} listings from {name}.")
    count = 0
    for item in listings:
        if name != "Adzuna API" and global_state["total_queued"] >= 100:
            logging.info("🎯 Global limit of 100 jobs reached. Stopping scraper.")
            break

        if len(item) == 4:
            title, url, desc, company_name = item
        elif len(item) == 3:
            title, url, desc = item
            company_name = None
        else:
            title, url = item
            desc = None
            company_name = None
            
        if process_private_job(title, url, name, recent_jobs, provided_html=desc, provided_company=company_name):
            count += 1
            global_state["total_queued"] += 1
        time.sleep(delay)
    logging.info(f"✅ {name}: Queued {count} new private jobs.")
    return count


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    logging.info("=" * 50)
    logging.info("💼 NextJobPost — Private Jobs Scraper v2 (Internships & Remote ONLY)")
    logging.info("   Sources: LinkedIn Official, Adzuna API, Internshala, WeWorkRemotely, Freshersworld, WorkAtAStartup")
    logging.info("=" * 50)

    get_auth_token()

    logging.info("\n📥 Preloading recent jobs from backend for deduplication...")
    recent_jobs = fetch_recent_jobs()
    logging.info(f"   ✔ Preloaded {len(recent_jobs)} live jobs.")

    global_state = {"total_queued": 0}

    if global_state["total_queued"] < 100:
        run_scraper("LinkedIn Official", extract_linkedin_jobs_public, recent_jobs, limit=100, delay=1.5, global_state=global_state)

    if global_state["total_queued"] < 100:
        run_scraper("Adzuna API", extract_adzuna_jobs, recent_jobs, limit=15, delay=1.5, global_state=global_state)

    if global_state["total_queued"] < 100:
        run_scraper("Internshala", extract_internshala_listings, recent_jobs, limit=15, delay=1.5, global_state=global_state)

    if global_state["total_queued"] < 100:
        run_scraper("WeWorkRemotely", extract_weworkremotely_rss, recent_jobs, limit=15, delay=1.5, global_state=global_state)

    if global_state["total_queued"] < 100:
        run_scraper("Freshersworld", extract_freshersworld_listings, recent_jobs, limit=10, delay=1.5, global_state=global_state)

    if global_state["total_queued"] < 100:
        run_scraper("WorkAtAStartup", extract_workatastartup_listings, recent_jobs, limit=10, delay=1.5, global_state=global_state)

    logging.info(f"\n✅ All private job sources processed. Total Queued: {global_state['total_queued']}/100")


if __name__ == "__main__":
    main()
