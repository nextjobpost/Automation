import os
import re
import json
import sys
import requests
import hashlib
import time
import logging
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from slugify import slugify
from dotenv import load_dotenv
import database

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

# =========================
# LOGGING SETUP
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Load Environment
load_dotenv(override=True)

def validate_config():
    api_key = os.getenv("API_KEY")
    if not api_key or api_key == "your_google_gemini_api_key":
        logging.warning("API_KEY (Gemini) not found or is placeholder. Running in BASIC extraction mode (no AI).")
        api_key = None
    
    is_prod = os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER") or os.getenv("PORT") is not None
    
    api_url = os.getenv("API_URL")
    if not api_url:
        api_url = "https://nextjobpost-backend.onrender.com/api/jobs" if is_prod else "http://localhost:4000/api/jobs"
        
    admin_url = os.getenv("ADMIN_URL")
    if not admin_url:
        admin_url = "https://nextjobpost-backend.onrender.com/api/admin/login" if is_prod else "http://localhost:4000/api/admin/login"
        
    api_token = os.getenv("API_TOKEN")
    old_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4ifQ.ts-o1us7bsOOJunK2dL4HNmz1ONh3tywCLj0D079k4M"
    new_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"
    if not api_token or api_token == old_token:
        api_token = new_token
        
    govt_base = os.getenv("GOVT_SCRAPER_BASE_URL", "https://govtjobsalert.in")
    
    return api_key, api_token, api_url, admin_url, govt_base

API_KEY, API_TOKEN, API_URL, ADMIN_URL, GOVT_SCRAPER_BASE_URL = validate_config()

from urllib.parse import urlparse, urljoin
parsed_base = urlparse(GOVT_SCRAPER_BASE_URL)
GOVT_SCRAPER_DOMAIN = parsed_base.netloc or "govtjobsalert.in"

CACHE_FILE = "scraped_urls.json"

# Initialize Gemini
client_gemini = None
if API_KEY:
    try:
        client_gemini = genai.Client(api_key=API_KEY)
    except Exception as e:
        logging.warning(f"Failed to initialize Gemini client: {e}. Running in BASIC extraction mode.")

def load_cache():
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            pass
    return cache

def get_auth_token():
    """Dynamically logs in to get a valid Bearer token."""
    global API_TOKEN
    
    # Try using existing token first to verify it works
    test_headers = {"Authorization": f"Bearer {API_TOKEN}"}
    try:
        # Check health or any dummy auth endpoint (or just proceed and login if needed)
        # We'll just call login directly to ensure we have a valid, non-expired token
        payload = {"username": "admin", "password": "admin123"}
        response = requests.post(ADMIN_URL, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            API_TOKEN = data.get("token")
            print("🔑 Successfully authenticated as admin dynamically.")
            return API_TOKEN
    except Exception as e:
        print(f"⚠️ Dynamic login failed: {e}. Falling back to API_TOKEN in environment.")
    
    return API_TOKEN

def clean_detail_html(html_content):
    """Parses detail page HTML, extracts .entry-content, and strips out ads/widgets/competitor links."""
    if not html_content:
        return ""
        
    # Strip HTML-encoded SVG blocks and normal SVG tags
    html_content = re.sub(r'<svg\b[^>]*>.*?</svg>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'&lt;svg\b.*?&lt;/svg&gt;', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    
    soup = BeautifulSoup(html_content, "html.parser")

    entry_content = soup.find(class_="entry-content")
    if not entry_content:
        # Some sites place main content inside div#content or div#primary
        entry_content = soup.find(id="content") or soup.find(id="primary")
    if not entry_content:
        # Fallback to the soup itself (document fragment)
        entry_content = soup


    # 1. Remove script, style, and AdSense ins tags
    for tag in entry_content.find_all(["script", "style", "ins"]):
        tag.decompose()

    # 2. Decompose elements by class names or tag attributes
    for tag in list(entry_content.find_all(True)):
        if not tag.parent:
            continue
            
        classes = tag.get("class", [])
        if isinstance(classes, list):
            class_str = " ".join(classes).lower()
        else:
            class_str = str(classes).lower()
            
        # Decompose class prefixes for competitors (e.g. gja- for GovtJobsAlert, fja- for FreeJobAlert)
        if any(x in class_str for x in ["gja-", "fja-", "code-block", "adsbygoogle", "share-box", "social-share"]):
            tag.decompose()
            continue
            
        # Decompose social media links
        if tag.name == "a":
            href = tag.get("href", "").lower()
            if any(domain in href for domain in ["whatsapp.com", "t.me", "telegram.me", "instagram.com", "youtube.com", "facebook.com", "twitter.com"]):
                if "nextjobpost" not in href:
                    tag.decompose()
                    continue
                    
        # Decompose specific texts containing competitor follow/join phrases
        text = tag.get_text(strip=True).upper()
        if any(phrase in text for phrase in ["JOIN WHATSAPP", "JOIN TELEGRAM", "JOIN INSTAGRAM", "JOIN YOUTUBE", "FOLLOW US ON", "JOIN US ON", "FOLLOW US", "JOIN US"]):
            if tag.name in ["li", "p", "strong", "span", "a", "h2", "h3", "h4", "div", "b", "i", "em"]:
                # Skip decomposing large outer containers
                if tag.name == "div" and len(text) > 150:
                    continue
                tag.decompose()
                continue


    # Get clean HTML string
    return str(entry_content)


def extract_govt_links(html_content):
    """
    Extracts the official website link, direct apply online link, and official notice PDF link 
    from the entry HTML using BeautifulSoup.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    
    official_website = ""
    apply_link = ""
    pdf_link = ""
    
    for a in soup.find_all("a"):
        text = a.get_text(strip=True).lower()
        href = a.get("href", "").strip()
        if not href:
            continue
            
        # Ignore sharing/social media links and competitor website links
        if any(social in href for social in ["whatsapp.com", "t.me", "telegram.me", "facebook.com", "twitter.com", "api.whatsapp", "govtjobsalert.in"]):
            continue
            
        # 1. Identify PDF link
        if href.endswith(".pdf") or "pdf" in text or "notice" in text:
            if not pdf_link:
                pdf_link = href
                
        # 2. Identify Official Website link
        if "official website" in text:
            official_website = href
            
        # 3. Identify Direct Apply Link
        if any(apply_term in text for apply_term in ["apply online", "online apply", "apply link", "registration", "click here to apply"]):
            if not apply_link:
                apply_link = href
                
    # Fallbacks:
    if not apply_link:
        for a in soup.find_all("a"):
            text = a.get_text(strip=True).lower()
            href = a.get("href", "").strip()
            if not href or any(social in href for social in ["whatsapp.com", "t.me", "telegram.me"]):
                continue
            if any(term in text for term in ["download", "apply", "marks", "response", "sheet"]):
                apply_link = href
                break
                
    if not apply_link:
        apply_link = official_website or pdf_link
        
    return {
        "officialWebsite": official_website,
        "applyLink": apply_link,
        "pdfLink": pdf_link
    }

def guess_org_from_title(title):
    if not title:
        return "Govt Department"
    # Basic guess logic: split by delimiters
    title_clean = re.sub(r"[^a-zA-Z0-9\s|:\-–]", " ", title)
    # Match common gov organizations
    orgs = ["UPSC", "SSC", "DRDO", "Railway", "ISRO", "BARC", "HAL", "IOCL", "ONGC", "NTPC", "BHEL", "RBI", "SBI", "IBPS"]
    for org in orgs:
        if re.search(r'\b' + re.escape(org) + r'\b', title_clean, re.IGNORECASE):
            return org
    # Check delimiters
    for delim in ["|", "-", ":", "–"]:
        if delim in title:
            parts = title.split(delim)
            for part in parts:
                cleaned = part.strip()
                if cleaned and len(cleaned.split()) <= 3 and len(cleaned) < 25:
                    if cleaned.lower() not in ["recruitment", "jobs", "hiring", "apply", "admit card", "result", "answer key", "vacancy", "vacancies"]:
                        return cleaned
    # Fallback to first word
    words = title.split()
    if words and len(words[0]) >= 2:
        return words[0]
    return "Govt Department"

def enrich_content_basic(html_content, title):
    """Fallback parser if Gemini fails or is not setup, using regex and BeautifulSoup"""
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text(separator=" ")
    text_clean = re.sub(r'\s+', ' ', text).strip()

    # 1. Organization
    org = guess_org_from_title(title)

    # 2. Eligibility
    eligibility = "As per notification"
    eligibility_keywords = [
        r"\b(?:10th|12th|ssc|hsc)\b",
        r"\b(?:b\.\s*e\.|b\.?tech)\b",
        r"\b(?:m\.?e\.?|m\.?tech)\b",
        r"\b(?:diploma)\b",
        r"\b(?:degree|graduate|graduation)\b",
        r"\b(?:post\s*graduate|post\s*graduation|master)\b",
        r"\b(?:m\.?sc\.?|b\.?sc\.?|m\.?c\.?a\.?|b\.?c\.?a\.?)\b",
        r"\b(?:iti)\b",
        r"\b(?:ph\.?d)\b",
        r"\b(?:mbbs)\b"
    ]
    matches = []
    for pattern in eligibility_keywords:
        match = re.search(pattern, text_clean, re.IGNORECASE)
        if match:
            matches.append(match.group(0).upper())
    if matches:
        eligibility = ", ".join(list(set(matches)))

    # 3. Vacancies
    vacancies = "Various Vacancies"
    
    # Priority 1: Explicit labels like "Total Vacancies: X"
    vac_match1 = re.search(r'(?:no\s*of\s*(?:posts|vacancies)|total\s*(?:posts|vacancies)|vacancies|vacancy)\s*[:\-]\s*(\d[\d,]*)\b', text_clean, re.IGNORECASE)
    if vac_match1:
        vacancies = f"{vac_match1.group(1)} Posts"
    else:
        # Priority 2: Numbers followed by posts/vacancies (allowing commas)
        for m in re.finditer(r'\b(\d[\d,]*)\s*(?:posts|vacancies|slots|positions|seats)\b', text_clean, re.IGNORECASE):
            num_str = m.group(1).replace(',', '')
            if num_str.isdigit() and 2020 <= int(num_str) <= 2030:
                continue
            vacancies = f"{m.group(1)} Posts"
            break

    # 4. Last Date
    last_date = ""
    months_pattern = r'(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)'
    
    # Heuristic: search for date near keywords "last date", "deadline", "closing", "submission" first
    date_pattern_ld1 = r'(?:last\s*date|deadline|closing|submission|end\s*date)[^0-9\n]{0,50}\b(\d{1,2})[-/\s]+(' + months_pattern + r'|\d{1,2})[-/\s]+(\d{4})\b'
    match_ld1 = re.search(date_pattern_ld1, text_clean, re.IGNORECASE)
    if match_ld1:
        d, m_name, y = match_ld1.groups()
        if m_name.isdigit():
            m_num = int(m_name)
        else:
            months_map = {
                "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
                "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
                "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
                "nov": 11, "november": 11, "dec": 12, "december": 12
            }
            m_num = months_map.get(m_name.lower()[:3]) or 1
        try: last_date = f"{int(y):04d}-{m_num:02d}-{int(d):02d}"
        except: pass
            
    if not last_date:
        # Check for YYYY-MM-DD pattern near keywords
        date_pattern_ld2 = r'(?:last\s*date|deadline|closing|submission|end\s*date)[^0-9\n]{0,50}\b(\d{4})[-/\s]+(' + months_pattern + r'|\d{1,2})[-/\s]+(\d{1,2})\b'
        match_ld2 = re.search(date_pattern_ld2, text_clean, re.IGNORECASE)
        if match_ld2:
            y, m_name, d = match_ld2.groups()
            if m_name.isdigit():
                m_num = int(m_name)
            else:
                months_map = {
                    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
                    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
                    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
                    "nov": 11, "november": 11, "dec": 12, "december": 12
                }
                m_num = months_map.get(m_name.lower()[:3]) or 1
            try: last_date = f"{int(y):04d}-{m_num:02d}-{int(d):02d}"
            except: pass

    if not last_date:
        # Fallback to general date regex (last date in the text usually)
        date_matches_m = re.findall(r'\b(\d{1,2})\s+(' + months_pattern + r')\s+(\d{4})\b', text_clean, re.IGNORECASE)
        if date_matches_m:
            d, m_name, y = date_matches_m[-1]
            months_map = {
                "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
                "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
                "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
                "nov": 11, "november": 11, "dec": 12, "december": 12
            }
            m_num = months_map.get(m_name.lower()[:3]) or 1
            try: last_date = f"{int(y):04d}-{m_num:02d}-{int(d):02d}"
            except: pass
                
    if not last_date:
        date_matches = re.findall(r'\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b', text_clean)
        if date_matches:
            d, m, y = date_matches[-1]
            try: last_date = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
            except: pass
                
    if not last_date:
        date_matches_y = re.findall(r'\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b', text_clean)
        if date_matches_y:
            y, m, d = date_matches_y[-1]
            try: last_date = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
            except: pass

    # 5. Salary — covers Pay Matrix, Grade Pay, Level, CPC scales & standard formats
    salary = "As per notification"
    # Match: ₹1,23,456, Rs. 50000, INR 40000 (prefixed with word boundaries to avoid matching word suffixes like 'covers' or 'years')
    m = re.search(r'(?:₹|\brs\.?|\binr)\s*(\d[\d,\.]+)\s*(?:per\s*month|pm|pa|p\.a\.?)\b', text_clean, re.IGNORECASE)
    if m:
        salary = f"Rs. {m.group(1).strip()}"
    else:
        # Match: Pay Matrix Level 6, Level-10, CPC Level 8
        m2 = re.search(r'(?:pay\s*matrix|pay\s*band|cpc)?\s*level\s*[-–]?\s*(\d+)', text_clean, re.IGNORECASE)
        if m2:
            salary = f"Pay Matrix Level {m2.group(1)}"
        else:
            # Match: Grade Pay ₹4200 or Grade Pay 4800
            m3 = re.search(r'grade\s*pay\s*(?:₹|rs\.?)?\s*(\d[\d,]*)', text_clean, re.IGNORECASE)
            if m3:
                salary = f"Grade Pay Rs. {m3.group(1)}"
            else:
                # Match: Pay Scale 15600-39100 or 9300-34800
                m4 = re.search(r'pay\s*(?:scale|band)[:\s]*([\d,]+-[\d,]+)', text_clean, re.IGNORECASE)
                if m4:
                    salary = f"Rs. {m4.group(1)}"
                else:
                    # Match: salary/stipend/pay near digits (generic fallback)
                    for m5 in re.finditer(r'\b(?:salary|stipend|remuneration|pay\s*scale|pay\s*matrix)\b[^0-9\n]{0,40}\b(\d{4,6}|\d{1,3},\d{3})\b', text_clean, re.IGNORECASE):
                        num_str = m5.group(1).replace(',', '')
                        if num_str.isdigit() and 2020 <= int(num_str) <= 2030:
                            continue
                        salary = f"Rs. {m5.group(1).strip()}"
                        break

    # 6. Summary
    summary = text_clean[:180] + "..." if len(text_clean) > 180 else text_clean

    return {
        "organization": org,
        "postName": title,
        "eligibility": eligibility,
        "vacancies": vacancies,
        "lastDate": last_date,
        "salary": salary,
        "summary": summary,
        "seoTitle": title[:60],
        "seoDescription": summary[:155],
        "faqs": []
    }

def enrich_content_with_ai(html_content, title):
    """Sends html/text content to Gemini 2.5 Flash to extract metadata, summary, and FAQs."""
    if not client_gemini:
        return None
    # Strip HTML tags to make the prompt smaller and save tokens
    soup = BeautifulSoup(html_content, "html.parser")
    text_content = soup.get_text(separator="\n")
    # Clean whitespace
    text_content = re.sub(r'\n+', '\n', text_content).strip()

    prompt = f"""
    Analyze the following government notification detail page for "{title}".
    Extract key information and return ONLY a valid JSON object. Do not include any markdown format blocks or `json` text backticks.
    
    The JSON structure MUST match this exact schema:
    {{
      "organization": "Name of the government body (e.g. UPSC, SSC, DRDO, Railway, State PSC, etc.)",
      "postName": "Refined short post/exam name",
      "eligibility": "Required eligibility criteria/qualification (e.g., 10th Pass, B.Tech in CSE, Any Graduate, etc.)",
      "vacancies": "Number of vacancies or posts available (e.g., 500 Posts, 12 Vacancies, etc. - leave empty string if not found)",
      "lastDate": "Application deadline or objection closing date in YYYY-MM-DD format (leave as empty string if not found)",
      "salary": "Salary or pay scale info if present (else 'As per notification')",
      "summary": "A clean 2-3 sentence summary of the post, status, or announcement",
      "seoTitle": "Optimized search engine title (60 chars max)",
      "seoDescription": "Compelling search engine description (155 chars max)",
      "officialPdfLink": "Direct URL to the official notification PDF file hosted on the organization's official website (e.g. ending in .pdf, like https://www.upsc.gov.in/notification.pdf) - search the web if needed, else leave empty string",
      "faqs": [
        {{
          "q": "Question related to application, eligibility, or exam date",
          "a": "Clear answer based on the notification"
        }}
      ]
    }}
    
    Article Text:
    {text_content[:6000]}
    """
    
    candidate_models = [
        "gemini-2.5-flash-lite-preview-06-17",
        "gemini-2.5-flash",
        "gemini-2.0-flash"
    ]
    
    last_error = None
    for model in candidate_models:
        try:
            print(f"🤖 Enriching with Gemini model: {model}...")
            # Try with search grounding first
            try:
                response = client_gemini.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        tools=[types.Tool(google_search=types.GoogleSearch())]
                    ),
                )
            except Exception as se:
                print(f"⚠️ Search grounding failed on {model} ({se}). Retrying without search...")
                response = client_gemini.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    ),
                )
            clean_json = response.text.strip()
            # Robust JSON extraction using regex
            json_match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if json_match:
                clean_json = json_match.group(0)
                
            return json.loads(clean_json)
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                print(f"⚠️ Model {model} resource exhausted. Waiting 2s before trying next model...")
                time.sleep(2)
                last_error = e
                continue
            else:
                print(f"⚠️ Gemini processing failed with model {model}: {e}")
                last_error = e
                
    print(f"❌ All Gemini candidate models failed. Last error: {last_error}")
    return None

def format_faq_html(faqs):
    """Formats a list of FAQ dictionary items into beautiful HTML block."""
    if not faqs:
        return ""
    faq_html = '<div class="gja-faq-section mt-5" style="border-top: 2px solid #e2e8f0; padding-top: 2rem;">'
    faq_html += '<h2 style="font-size: 1.5rem; font-weight: bold; color: #1e3a8a; margin-bottom: 1.5rem;">📋 Frequently Asked Questions (FAQs)</h2>'
    for faq in faqs:
        q = faq.get("q", "").strip()
        a = faq.get("a", "").strip()
        if q and a:
            faq_html += f"""
            <div class="gja-faq-item" style="margin-bottom: 1.25rem; padding: 1rem; background-color: #f8fafc; border-left: 4px solid #2563eb; border-radius: 0 8px 8px 0;">
                <h4 style="margin: 0 0 0.5rem 0; font-weight: bold; color: #1e293b; font-size: 1.05rem;">❓ {q}</h4>
                <p style="margin: 0; color: #475569; font-size: 0.95rem; line-height: 1.6;">{a}</p>
            </div>
            """
    faq_html += '</div>'
    return faq_html

def sanitize_description_links(html_content, official_pdf_url, official_apply_url, official_website_url):
    """
    Parses the scraped HTML content, finds any competitor-hosted PDF/file links, 
    and rewrites them to the official PDF URL or the official notification/apply pages on the organization's site.
    """
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    for a in soup.find_all("a"):
        href = a.get("href", "").strip()
        if not href:
            continue
        
        # If it is a competitor domain link or ends with .pdf
        if "govtjobsalert.in" in href or href.endswith(".pdf"):
            target_url = official_pdf_url or official_apply_url or official_website_url
            if target_url:
                a["href"] = target_url
                # Clean anchor text if it specifically says PDF but we fall back to a page
                if not official_pdf_url:
                    text = a.get_text().lower()
                    if "pdf" in text:
                        a.string = "Official Notification Page"
            else:
                a.unwrap() # Remove the link tag entirely but keep the text if no official fallback is available
                
    return str(soup)

def fetch_recent_jobs():
    """Fetches all recent jobs from the website backend to build a local map for smart duplication checks."""
    global API_URL, API_TOKEN
    headers = {}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    try:
        r = requests.get(f"{API_URL}?limit=150&status=all", headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        print(f"⚠️ Failed to fetch recent jobs from backend ({API_URL}): {e}")
        # Fallback to production API if localhost failed
        if "localhost" in API_URL:
            prod_url = "https://nextjobpost-backend.onrender.com/api/jobs"
            print(f"🔄 Attempting fallback to production API: {prod_url}")
            try:
                r = requests.get(f"{prod_url}?limit=150&status=all", headers=headers, timeout=15)
                if r.status_code == 200:
                    API_URL = prod_url
                    print("✅ Successfully connected to production backend.")
                    return r.json().get("data", [])
            except Exception as ex:
                print(f"❌ Fallback to production API failed: {ex}")
    return []

def find_existing_job(url, title, company, recent_jobs):
    """Fuzzy and URL matching to find an existing job in the preloaded list."""
    if not recent_jobs:
        return None
    url_clean = url.strip().lower().rstrip('/')
    title_clean = title.strip().lower()
    comp_clean = company.strip().lower()
    
    # 1. Match by sourceUrl or applyLink
    for job in recent_jobs:
        job_source = str(job.get("sourceUrl", "")).strip().lower().rstrip('/')
        job_apply = str(job.get("applyLink", "")).strip().lower().rstrip('/')
        if (job_source == url_clean) or (job_apply == url_clean and "govtjobsalert.in" in job_apply):
            return job
            
    # 2. Match by slug similarity (slugify comparison)
    slug_url = slugify(title)
    slug_url_alt1 = slugify(title.replace("&", "and"))
    slug_url_alt2 = slugify(title.replace("&", ""))
    
    for job in recent_jobs:
        job_slug = str(job.get("slug", "")).strip().lower()
        if job_slug in [slug_url, slug_url_alt1, slug_url_alt2]:
            return job
            
    # 3. Match by Title + Company fuzzy check (slugify of title + company matches)
    for job in recent_jobs:
        job_title = str(job.get("title", "")).strip().lower()
        job_company = str(job.get("company", "")).strip().lower()
        if comp_clean == job_company:
            t1 = re.sub(r'\b(apply\s+online|recruitment|posts|vacancies|salary|up\s+to|last\s+date|july|june|2026|2025)\b', '', title_clean)
            t2 = re.sub(r'\b(apply\s+online|recruitment|posts|vacancies|salary|up\s+to|last\s+date|july|june|2026|2025)\b', '', job_title)
            s1 = slugify(t1).replace('-', '')
            s2 = slugify(t2).replace('-', '')
            if s1 == s2 or s1 in s2 or s2 in s1:
                return job
                
    return None

def scrape_category(category_path, post_type_default, recent_jobs):
    """Scrapes a specific category listing page, processes new items, and uploads to NextJobPost."""
    url = f"{GOVT_SCRAPER_BASE_URL.rstrip('/')}/{category_path.lstrip('/')}"
    print(f"\n🔍 Scraping Category: {url} ...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"❌ Failed to load category page: {url} (Status: {response.status_code})")
            return
    except Exception as e:
        print(f"❌ Error fetching category page: {e}")
        return

    soup = BeautifulSoup(response.content, "html.parser")
    cards = soup.find_all("a", class_="gja-grid-card")
    print(f"Found {len(cards)} listings on listing page.")
    
    get_auth_token()
    
    new_items_posted = 0
    
    for card in cards:
        href = card.get("href")
        if not href:
            continue
            
        # Clean URL
        href = href.strip()
        job_hash = hashlib.md5(href.encode()).hexdigest()
        
        if database.is_job_seen(job_hash):
            continue
            
        title_elem = card.find(class_="gja-card-title")
        raw_title = title_elem.text.strip() if title_elem else "Notification Details"
        
        # Determine Post Type badge
        badge_elem = card.find(class_="gja-badge")
        post_type = badge_elem.text.strip() if badge_elem else post_type_default
        
        print(f"\n🚀 New Listing Found: {raw_title}")
        print(f"🔗 Detail URL: {href}")
        
        # 1. Fetch detail page
        try:
            detail_resp = requests.get(href, headers=headers, timeout=15)
            if detail_resp.status_code != 200:
                print(f"⚠️ Failed to fetch detail page: {href} (Status: {detail_resp.status_code})")
                continue
        except Exception as e:
            print(f"⚠️ Error fetching detail page: {e}")
            continue
            
        # 2. Clean HTML content
        detail_html = clean_detail_html(detail_resp.text)
        if not detail_html:
            print("⚠️ Entry content empty or not found. Skipping.")
            continue
            
        # 3. Call Gemini to enrich, fallback to basic Regex/BeautifulSoup parser if it fails
        ai_data = enrich_content_with_ai(detail_html, raw_title)
        if not ai_data:
            print("⚠️ AI Enrichment failed. Falling back to basic regex/BeautifulSoup parser...")
            ai_data = enrich_content_basic(detail_html, raw_title)
            
        # 4. Construct final structured content
        org = ai_data.get("organization", "Govt Department")
        post_name = ai_data.get("postName", raw_title)
        eligibility = ai_data.get("eligibility", "As per notification")
        vacancies = ai_data.get("vacancies", "Various Vacancies")
        salary = ai_data.get("salary", "Best in Industry")
        last_date = ai_data.get("lastDate", None)
        
        # Check if the extracted last date is in the past (expired)
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
                
                if not parsed_date:
                    match = re.search(r'(\d{4})[-/](\d{2})[-/](\d{2})', last_date_str)
                    if match:
                        try:
                            y, m, d = map(int, match.groups())
                            parsed_date = date(y, m, d)
                        except ValueError:
                            pass
                
                if parsed_date and parsed_date < date.today():
                    print(f"⚠️ Skipping expired job: '{raw_title}'. Last date '{last_date_str}' is in the past (today is {date.today()}).")
                    database.mark_job_seen(job_hash)
                    continue

        summary = ai_data.get("summary", raw_title)
        seo_title = ai_data.get("seoTitle", raw_title)
        seo_desc = ai_data.get("seoDescription", raw_title)
        faqs = ai_data.get("faqs", [])
        
        # Extract official links from detail HTML
        govt_links = extract_govt_links(detail_html)
        extracted_apply_link = govt_links["applyLink"]
        if not extracted_apply_link or "govtjobsalert.in" in extracted_apply_link:
            extracted_apply_link = govt_links["officialWebsite"] or ""
            # If still invalid/empty, set to empty
            if "govtjobsalert.in" in extracted_apply_link:
                extracted_apply_link = ""
                
        # Resolve PDF Link using Gemini search grounding or fallbacks
        official_pdf_ai = ai_data.get("officialPdfLink", "").strip() if isinstance(ai_data, dict) else ""
        extracted_pdf_link = ""
        if official_pdf_ai and official_pdf_ai.startswith("http") and (official_pdf_ai.endswith(".pdf") or "pdf" in official_pdf_ai.lower()):
            extracted_pdf_link = official_pdf_ai
            print(f"   ✔ Found official PDF link via Gemini: {extracted_pdf_link}")
            
        if not extracted_pdf_link:
            extracted_pdf_link = govt_links["pdfLink"]
            if extracted_pdf_link and ("govtjobsalert.in" in extracted_pdf_link or "nextjobpost.in" in extracted_pdf_link):
                extracted_pdf_link = ""

        # Sanitize HTML body of competitor file links and replace with the official direct PDF or apply page
        sanitized_detail_html = sanitize_description_links(
            detail_html,
            official_pdf_url=extracted_pdf_link,
            official_apply_url=extracted_apply_link,
            official_website_url=govt_links.get("officialWebsite")
        )
        
        # Append FAQs at the end of the jobDescription HTML
        faq_html = format_faq_html(faqs)
        full_description_html = sanitized_detail_html + faq_html
        
        # 5. Always queue the job for bot1.py (Telegram + LinkedIn + image)
        slug_base = slugify(raw_title)
        url_hash = hashlib.md5(href.encode()).hexdigest()[:5]
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
            "postType": post_type,
            "sourceWebsite": GOVT_SCRAPER_DOMAIN,
            "sourceUrl": href,
            "importantDates": "As per official notification",
            "pdfLink": extracted_pdf_link,
            "isActive": True,
            "whatsapp": "https://chat.whatsapp.com/LVpuUJluTpUEdIc4daAemQ",
            "telegram": "https://t.me/nextjobpost"
        }

        # Load, append and save to SQLite queue
        job_hash = hashlib.md5(href.encode()).hexdigest()
        
        # Semantic Deduplication & Thin Content Check
        title_str = str(queue_job.get('title', '')).lower().strip()
        comp_str = str(queue_job.get('company', '')).lower().strip()
        semantic_hash = hashlib.md5(f"{title_str}::{comp_str}".encode()).hexdigest()
        
        existing_job = find_existing_job(href, raw_title, org, recent_jobs)
        
        if existing_job:
            job_desc = existing_job.get("jobDescription", "") or ""
            desc_main_part = job_desc.split('<div class="enriched-job-content')[0]
            # Treat as thin if: empty, less than 2000 chars, or missing a proper table
            is_thin = (
                not job_desc
                or len(desc_main_part) < 2000
                or "<table" not in job_desc.lower()
            )
            
            if is_thin:
                print(f"🔄 Thin description detected for live job '{raw_title}'. Enriching live post...")
                job_id = existing_job.get("_id") or existing_job.get("id")
                
                # Construct update payload — refresh all key fields
                update_payload = {
                    "jobDescription":  full_description_html,
                    "description":     summary,
                    "shortSummary":    summary,
                    "pdfLink":         extracted_pdf_link,
                    "applyLink":       extracted_apply_link or existing_job.get("applyLink"),
                    "sourceWebsite":   GOVT_SCRAPER_DOMAIN,
                    "sourceUrl":       href,
                    "importantDates":  "As per official notification",
                    "eligibility":     eligibility,
                    "vacancies":       vacancies,
                    "salary":          salary,
                    "lastDate":        last_date if last_date else existing_job.get("lastDate"),
                    "metaTitle":       seo_title,
                    "metaDescription": seo_desc
                }
                
                headers = {"Content-Type": "application/json"}
                if API_TOKEN:
                    headers["Authorization"] = f"Bearer {API_TOKEN}"
                    
                try:
                    up_r = requests.put(f"{API_URL}/{job_id}", json=update_payload, headers=headers, timeout=15)
                    if up_r.status_code == 200:
                        print(f"✅ Successfully enriched duplicate job: '{raw_title}' (ID: {job_id})")
                        database.mark_job_seen(job_hash)
                        database.mark_job_seen(semantic_hash)
                        continue
                    else:
                        print(f"⚠️ Failed to update duplicate job. API returned status {up_r.status_code}: {up_r.text}")
                except Exception as e:
                    print(f"⚠️ Error updating duplicate job: {e}")
            else:
                print(f"⚠️ Job '{raw_title}' already exists with rich content. Skipping.")
                database.mark_job_seen(job_hash)
                database.mark_job_seen(semantic_hash)
                continue
        else:
            # Fallback to local DB check if job is not live on backend
            if database.is_job_seen(semantic_hash):
                print(f"⚠️ Semantic duplicate detected in local DB, skipping: {raw_title}")
                database.mark_job_seen(job_hash)
                continue
        
        try:
            if database.add_job_to_queue(queue_job, job_hash, image_path="", is_government=True):
                print(f"📥 Queued govt job for Telegram + LinkedIn posting: {raw_title}")
                print(f"   └ Apply Link : {extracted_apply_link}")
                print(f"   └ PDF Link   : {extracted_pdf_link}")
                database.mark_job_seen(job_hash)
                database.mark_job_seen(semantic_hash)
                new_items_posted += 1
            else:
                print(f"⚠️ Failed to queue or already in queue: {raw_title}")
        except Exception as e:
            print(f"❌ Failed to write to SQLite: {e}")
            
    print(f"Finished category scraping. Posted {new_items_posted} new drafts.")

# scrape_sarkari_result() removed — Sarkari Result source has been disabled.
# Only govtjobsalert.in is used as the approved government jobs scraping source.



def main():
    print("========================================")
    print("🏛️ NextJobPost Government Jobs Scraper 🏛️")
    print("========================================")

    # Approved scraper source: govtjobsalert.in only.
    # Sarkari Result (sarkariresult.com) has been removed as an approved source.
    govt_base = os.getenv("GOVT_SCRAPER_BASE_URL", "https://govtjobsalert.in")

    categories = [
        ("/govt-jobs/", "Government Job"),
        ("/admit-cards/", "Admit Card"),
        ("/results/", "Result"),
        ("/answer-keys/", "Answer Key")
    ]

    cache = load_cache()
    get_auth_token()

    # Preload recent jobs from Node.js backend for smart duplicate checking
    print("📥 Preloading recent jobs from live website backend...")
    recent_jobs = fetch_recent_jobs()
    print(f"   ✔ Preloaded {len(recent_jobs)} jobs.")

    print(f"\n========================================\n🌐 Processing Source: Govt Jobs Alert ({govt_base})\n========================================")

    for category_path, post_type in categories:
        scrape_category(category_path, post_type, recent_jobs)

    print("\n✅ All scraper sources successfully processed.")


if __name__ == "__main__":
    main()
