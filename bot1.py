import os
import re
import asyncio
import hashlib
import aiohttp
import sys
from datetime import datetime, date
from telethon import TelegramClient, events

from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from dotenv import load_dotenv
from slugify import slugify

# Force UTF-8 encoding for stdout and stderr to prevent UnicodeEncodeErrors on Windows
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


# =========================
# ENV
# =========================
load_dotenv(override=True)

API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
API_TOKEN = os.getenv("API_TOKEN")
API_KEY   = os.getenv("API_KEY")

# Fallback to the new valid token (containing role: admin) if the env variable is missing or matches the old invalid token
OLD_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4ifQ.ts-o1us7bsOOJunK2dL4HNmz1ONh3tywCLj0D079k4M"
NEW_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"
if not API_TOKEN or API_TOKEN == OLD_TOKEN:
    API_TOKEN = NEW_TOKEN


# LinkedIn Credentials (from get_linkedin_token.py)
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_URN   = os.getenv("LINKEDIN_PERSON_URN", "")  # e.g. urn:li:person:XXXXX

SOURCE_CHANNELS = [
    "me",
    # ── Off-Campus & Tech (Freshers) ──
    "CSEOfficialTelegram",
    "IT_Jobs_Career",
    "CSE_IT_BCA_MCA_Computer_Jobs",
    "placementkit",
    "placementdriveofficial",
    "fresher_offcampus_drives",
    "walkindrive",
    "freshershunt",
    "fresherearth",
]

TARGET_CHANNEL = "nextjobpost"

# Detect environment to set appropriate default API url
IS_PRODUCTION = os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER") or os.getenv("PORT") is not None
DEFAULT_API_URL = "https://nextjobpost-backend.onrender.com/api/jobs" if IS_PRODUCTION else "http://localhost:4000/api/jobs"

API_URL = os.getenv("API_URL", DEFAULT_API_URL)
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://nextjobpost.in")

# ── Queue Setup ──
QUEUE_FILE = "job_queue.json"
# Default 30 minutes (1800 seconds) between posts. Capped at 3600 (1 hour) to guarantee at least 24 posts a day.
POST_INTERVAL = min(int(os.getenv("POST_INTERVAL", 1800)), 3600)
PENDING_IMAGES_DIR = "pending_images"

if not os.path.exists(PENDING_IMAGES_DIR):
    os.makedirs(PENDING_IMAGES_DIR)

# ── Telegram Setup ──
SESSION_DATA = os.getenv("TELEGRAM_SESSION_STRING", "session")
# If it looks like a string session (long), use StringSession, otherwise use file name
session = StringSession(SESSION_DATA) if len(SESSION_DATA) > 25 else SESSION_DATA
client = TelegramClient(session, API_ID, API_HASH)

# =========================
# MEMORY CACHE (persistent)
# =========================
CACHE_FILE = "posted_cache.json"

# In-memory fallbacks for Railway (read-only filesystem)
_MEMORY_QUEUE = []   # Used when job_queue.json can't be written
_MEMORY_SEEN  = set()  # Used when posted_cache.json can't be written

def load_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set(_MEMORY_SEEN)

def save_cache(cache_set):
    global _MEMORY_SEEN
    _MEMORY_SEEN = set(cache_set)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(cache_set)[-500:], f)
    except Exception:
        pass  # Read-only filesystem (Railway) — use in-memory only

# ── Queue Functions ──
def load_queue():
    """Load from file if available, otherwise use in-memory queue."""
    try:
        if os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                disk_queue = json.load(f)
                # Sync in-memory queue to disk contents
                if disk_queue:
                    return disk_queue
    except Exception:
        pass
    return list(_MEMORY_QUEUE)  # Fallback to in-memory

def save_queue(queue):
    """Save to file if writable, always sync to in-memory queue."""
    global _MEMORY_QUEUE
    _MEMORY_QUEUE = list(queue)
    try:
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2)
    except Exception:
        pass  # Read-only filesystem (Railway) — in-memory already updated above

seen = load_cache()

def hash_text(t):
    return hashlib.md5(t.encode()).hexdigest()

# =========================
# FILTER
# =========================
JOB_WORDS = ["job", "hiring", "apply", "vacancy", "intern", "opening", "recruitment", "role", "drive"]
JOB_EMOJIS = ["🔔", "🚀", "📍", "💼", "🎓", "⏳", "👉"]

def normalize_text(text):
    if not text:
        return ""
    import unicodedata
    # Normalize unicode bold/italic mathematical alphanumeric chars to standard Latin
    return unicodedata.normalize('NFKD', str(text)).lower()

def normalize_text_keep_case(text):
    if not text:
        return ""
    import unicodedata
    # Normalize unicode bold/italic mathematical alphanumeric chars to standard Latin while keeping original case
    return unicodedata.normalize('NFKD', str(text))

def is_job(text):
    if not text: return False
    t = normalize_text(text)
    
    # Reject training/certification course advertisements
    course_keywords = ["certification course", "free certification", "enroll in course", "course registration", "bootcamp registration", "training program with certificate"]
    if any(kw in t for kw in course_keywords):
        return False
        
    # Check for direct word matches in lowercase
    has_job_word = any(w in t for w in JOB_WORDS)
    
    # Check for emojis often used in job posts
    has_job_emoji = any(e in text for e in JOB_EMOJIS)
    
    # Check for links (crucial for jobs)
    has_link = "http" in t or "bit.ly" in t or "t.me" in t
    
    # If it has a job word (even normalized) or a job emoji, and it has a link, it's likely a job
    # We also check for 'role' or 'hiring' in the original text to catch unicode bold 
    # (since 'hiring' in script might still contain searchable fragments or we match emoji)
    
    # Fallback for unicode bold: if it looks like a job post structure
    looks_like_job = any(indicator in text for indicator in ["𝗝𝗼𝗯", "𝗛𝗶𝗿𝗶𝗻𝗴", "𝗥𝗼𝗹𝗲", "𝗔𝗽𝗽𝗹𝘆"])
    
    return (has_job_word or has_job_emoji or looks_like_job) and has_link

from google import genai
from google.genai import types
import json

client_gemini = genai.Client(api_key=API_KEY) if API_KEY else None

# =========================
# EXTRACTOR (AI + Basic Fallback)
# =========================
def extract_basic(text):
    """Fallback Regex Parser for Telegram posts if Gemini fails or is not setup"""
    # 1. Clean mathematical bold/italic to standard Latin text
    text_clean = normalize_text_keep_case(text)
    
    # 2. Extract Title (first non-empty line, stripped of emojis and special characters)
    lines = [l.strip() for l in text_clean.split("\n") if l.strip()]
    raw_title = lines[0][:120] if lines else "Job Opening"
    title = re.sub(r"[^a-zA-Z0-9\s|:\-–]", " ", raw_title).strip()
    # Normalize double spaces
    title = re.sub(r"\s+", " ", title)
    
    # 3. Extract Links
    urls = re.findall(r'https?://[^\s]+', text)
    apply_link = urls[0] if urls else ""
    
    # 4. Guess Company
    company = guess_company_from_title(title)
    if not company:
        # Search for company field in text
        for l in lines:
            if "company" in l.lower() or "organization" in l.lower():
                company_val = l.split(":")[-1].strip()
                company = clean_company_name(company_val)
                break
    if not company:
        company = get_company_from_link(apply_link) or "Top Company"

    # 5. Extract Location
    location = "Pan India"
    for l in lines:
        if "location" in l.lower() or "job location" in l.lower():
            location_val = l.split(":")[-1].strip()
            # Clean location value
            location = re.sub(r"[^a-zA-Z0-9\s,.\-]", " ", location_val).strip()
            location = re.sub(r"\s+", " ", location)
            break

    # 6. Extract Eligibility / Education
    education = "Any Graduate"
    eligibility = ""
    for l in lines:
        l_lower = l.lower()
        if "eligibility" in l_lower or "education" in l_lower or "qualification" in l_lower:
            val = l.split(":")[-1].strip()
            val = re.sub(r"[^a-zA-Z0-9\s,.\-/]", " ", val).strip()
            education = re.sub(r"\s+", " ", val)
            eligibility = education
            break
            
    # Heuristic match for B.Tech/Degree if not explicitly in education line
    if education == "Any Graduate":
        elig_keywords = [
            r"\b(?:b\.?e\.?|b\.?tech)\b",
            r"\b(?:m\.?e\.?|m\.?tech)\b",
            r"\b(?:diploma)\b",
            r"\b(?:degree|graduate|graduation)\b",
            r"\b(?:m\.?sc\.?|b\.?sc\.?|m\.?c\.?a\.?|b\.?c\.?a\.?)\b"
        ]
        matches = []
        for pattern in elig_keywords:
            match = re.search(pattern, text_clean, re.IGNORECASE)
            if match:
                matches.append(match.group(0).upper())
        if matches:
            education = ", ".join(list(set(matches)))
            eligibility = education
       # 7. Extract Salary
    salary = "Best in Industry"
    for l in lines:
        if "salary" in l.lower() or "stipend" in l.lower() or "package" in l.lower():
            val = l.split(":")[-1].strip()
            salary = re.sub(r"[^a-zA-Z0-9\s,.\-₹$#LPA]", " ", val).strip()
            salary = re.sub(r"\s+", " ", salary)
            break
            
    if salary == "Best in Industry":
        # Match currency symbol + digits near keywords (pay, salary, stipend, scale)
        salary_match = re.search(r'\b(?:pay|salary|stipend|remuneration|scale)\b[^0-9\n]{0,40}(?:rs\.?|inr|₹|rs|rs\.)\s*(\d+[\d,]*)\b', text_clean, re.IGNORECASE)
        if salary_match:
            salary = f"Rs. {salary_match.group(1).strip()}"
        else:
            # Match standalone digits near keywords
            salary_match2 = re.search(r'\b(?:pay|salary|stipend|remuneration|scale)\b[^0-9\n]{0,40}\b(\d{4,6}|\d{1,3},\d{3})\b', text_clean, re.IGNORECASE)
            if salary_match2:
                salary = f"Rs. {salary_match2.group(1).strip()}"

    # 8. Extract Vacancies
    vacancies = "Various Vacancies"
    for l in lines:
        if "vacancies" in l.lower() or "vacancy" in l.lower() or "slots" in l.lower() or "posts" in l.lower():
            val = l.split(":")[-1].strip()
            vacancies = re.sub(r"[^a-zA-Z0-9\s,.\-]", " ", val).strip()
            vacancies = re.sub(r"\s+", " ", vacancies)
            break
    if vacancies == "Various Vacancies":
        vac_match = re.search(r'\b(\d+)\s*(?:posts|vacancies|slots|positions|seats)\b', text_clean, re.IGNORECASE)
        if vac_match:
            vacancies = vac_match.group(0).strip()

    # 9. Extract Last Date
    last_date = ""
    # Fallback to search entire post for dates with deadline heuristics
    months_pattern = r'(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)'
    
    # Check for date near keywords first
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
        # Fallback to general date regex (last match in text)
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

    # 10. Extract Job Type / Experience / Batch
    job_type = "Full-Time"
    experience = "Fresher / 0-2 Years"
    batch = "2024 / 2025 / 2026"
    
    for l in lines:
        l_lower = l.lower()
        if "intern" in l_lower:
            job_type = "Internship"
        if "experience" in l_lower:
            val = l.split(":")[-1].strip()
            experience = re.sub(r"[^a-zA-Z0-9\s\-/]", " ", val).strip()
            experience = re.sub(r"\s+", " ", experience)
        if "batch" in l_lower or "eligible batches" in l_lower:
            val = l.split(":")[-1].strip()
            batch = re.sub(r"[^a-zA-Z0-9\s/]", " ", val).strip()
            batch = re.sub(r"\s+", " ", batch)

    # 11. Government Job detection
    is_govt = False
    govt_keywords = ["drdo", "ssc", "upsc", "railway", "isro", "govt", "government", "sarkari", "public sector", "psu"]
    if any(kw in title.lower() or kw in company.lower() for kw in govt_keywords):
        is_govt = True

    return {
        "title": title,
        "company": company,
        "location": location,
        "applyLink": apply_link,
        "jobDescription": text_clean,
        "description": text_clean[:180] + "..." if len(text_clean) > 180 else text_clean,
        "type": job_type,
        "experience": experience,
        "education": education,
        "eligibility": eligibility,
        "vacancies": vacancies,
        "salary": salary,
        "batch": batch,
        "lastDate": last_date if last_date else None,
        "isGovernment": is_govt,
        "slug": slugify(title) + "-" + hashlib.md5(text.encode()).hexdigest()[:5]
    }

from urllib.parse import urlparse

def clean_company_name(s):
    # Normalize unicode mathematical bold/italic characters to standard Latin
    s_norm = normalize_text_keep_case(s)
    
    # Strip emojis and keep only standard characters (letters, digits, spaces, and & , . -)
    s_norm = re.sub(r"[^a-zA-Z0-9\s&,\.\-]", " ", s_norm)
    
    words_orig = s_norm.split()
    s_lower = " " + s_norm.lower() + " "
    
    # Remove common phrases and job titles
    patterns_to_remove = [
        r"\boff\s*campus\b", r"\bcampus\b", r"\bdrive\b", r"\bhiring\b", r"\brecruitment\b", 
        r"\bjobs?\b", r"\bcareers?\b", r"\bnew\b", r"\bfreshers?\b", 
        r"\binternships?\b", r"\binterns?\b", r"\b202[0-9]\b", r"\bapply\s*now\b",
        r"\bopportunity\b", r"\bopenings?\b", r"\balerts?\b", r"\bupdates?\b",
        r"\bsoftware\s*engineer\b", r"\bsoftware\s*developer\b", r"\bdeveloper\b",
        r"\bengineer\b", r"\banalyst\b", r"\btester\b", r"\bsupport\b", r"\bconsultant\b",
        r"\bassociate\b", r"\bexecutive\b", r"\btrainee\b", r"\bmanager\b",
        r"\bfor\b", r"\bat\b", r"\bthe\b", r"\ban\b", r"\ba\b", r"\bin\b", r"\bto\b", r"\bof\b", r"\bwith\b",
        r"\bis\b", r"\bare\b"
    ]
    
    cleaned = s_lower
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, " ", cleaned)
    
    cleaned = cleaned.strip(" -|:_!@#%^&*()[]{}<>.,/\\\"'")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    
    result_words = []
    for w in cleaned.split():
        orig_match = None
        for orig_w in words_orig:
            clean_orig = re.sub(r"[^a-zA-Z0-9]", "", orig_w)
            if clean_orig.lower() == w.lower():
                orig_match = clean_orig
                break
        if orig_match:
            result_words.append(orig_match)
        else:
            result_words.append(w.capitalize())
            
    return " ".join(result_words)

def get_company_from_link(url):
    if not url:
        return None
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        parts = netloc.split(".")
        if len(parts) >= 2:
            generic_domains = {"com", "org", "net", "in", "co", "io", "us", "uk", "edu", "gov", "me", "info", "tech"}
            generic_hosts = {"forms", "gle", "github", "notion", "linktr", "t", "telegram", "facebook", "twitter", "linkedin", "instagram", "youtube", "drive", "docs"}
            domain_parts = [p for p in parts if p not in generic_domains]
            if domain_parts:
                main_domain = domain_parts[-1]
                if main_domain not in generic_hosts:
                    return main_domain.upper() if len(main_domain) <= 3 else main_domain.capitalize()
    except:
        pass
    return None

def guess_company_from_title(title):
    if not title:
        return None
    
    # 1. Try pattern "... at [Company]" or "... by [Company]"
    at_match = re.search(r"\b(?:at|by)\s+([a-zA-Z0-9\s]+)", title, re.IGNORECASE)
    if at_match:
        candidate_words = at_match.group(1).strip().split()
        if candidate_words:
            candidate = " ".join(candidate_words[:2])
            cleaned = clean_company_name(candidate)
            if cleaned and cleaned.lower() not in ["new", "hiring", "apply", "urgent", "huge", "latest", "alert", "job", "software", "associate", "junior", "senior", "lead"]:
                return cleaned
                
    # 2. Try splitting by common delimiters
    delimiters = ["|", "-", ":", "–"]
    for delim in delimiters:
        if delim in title:
            parts = title.split(delim)
            for part in parts:
                cleaned = clean_company_name(part)
                if cleaned and len(cleaned.split()) <= 3 and len(cleaned) < 25:
                    if cleaned.lower() not in ["new hiring", "hiring", "apply now", "freshers", "for", "software", "associate", "junior", "senior", "lead"]:
                        return cleaned

    # 3. Try first word
    words = title.split()
    if words:
        first_word_cleaned = clean_company_name(words[0])
        if first_word_cleaned and len(first_word_cleaned) >= 2:
            if first_word_cleaned.lower() not in ["new", "hiring", "apply", "urgent", "huge", "latest", "alert", "job", "software", "associate", "junior", "senior", "lead"]:
                return first_word_cleaned
                
    # 4. Fallback to clean whole title
    cleaned = clean_company_name(title)
    if cleaned and len(cleaned.split()) <= 3 and len(cleaned) < 25:
        if cleaned.lower() not in ["new hiring", "hiring", "apply now", "freshers", "for", "software", "associate", "junior", "senior", "lead"]:
            return cleaned
            
    return None

def parse_salary_fallback(text):
    if not text:
        return None
    import re
    import unicodedata
    
    # Strip HTML tags if any
    clean_text = re.sub(r'<[^>]+>', ' ', text)
    # Normalize unicode/mathematical characters
    clean_text = unicodedata.normalize('NFKD', str(clean_text))
    
    # Pattern 1: match currency symbol + digits + range + qualifiers like LPA/month/K
    value_re = r'₹\s*[\d,.]+\s*(?:LPA|L|Lakh|lakhs?|K|\/month)?(?:\s*[-–—\u2212]\s*₹?\s*[\d,.]+\s*(?:LPA|L|Lakh|lakhs?|K|\/month)?)?(?:\s*\([^)\n]{1,30}\))?'
    
    lines = clean_text.split('\n')
    for line in lines:
        line_lower = line.lower()
        if any(kw in line_lower for kw in ["salary", "stipend", "package", "ctc", "lpa"]):
            # Look for the pattern in this specific line
            match = re.search(value_re, line, re.IGNORECASE)
            if match:
                return match.group(0).strip()
                
            # If not matched, try matching "X LPA" or "X Lakh"
            lpa_re = r'\b(\d+(?:\.\d+)?)\s*(?:LPA|Lakh|lacs?|k/month)\b'
            match_lpa = re.search(lpa_re, line, re.IGNORECASE)
            if match_lpa:
                return match_lpa.group(0).strip()
                
    # If no line matches, search globally for ₹ value pattern
    match_global = re.search(value_re, clean_text, re.IGNORECASE)
    if match_global:
        return match_global.group(0).strip()
        
    return None

def enrich_company_details(job):
    company = job.get("company", "").strip()
    if not company:
        company = "Top Company"
        job["company"] = company
        
    company_lower = company.lower()
    
    # 🏢 Known company profiles
    profiles = {
        "ibm": {
            "aboutCompany": "IBM is a leading global technology and consulting corporation pioneer in mainframe systems, cloud infrastructure, AI platforms, and quantum computing.",
            "whyJoin": "IBM offers an incredible global platform, world-class technical training resources, and hands-on experience working on enterprise-scale hybrid cloud and AI projects.",
            "howToApply": "Click the apply link, fill in your details on IBM's official candidate portal, upload your resume, and submit your application.",
            "finalThoughts": "This is a fantastic opportunity to launch your career with a global technology pioneer. Best of luck!"
        },
        "accenture": {
            "aboutCompany": "Accenture is a leading global professional services company providing advanced capabilities in strategy, consulting, digital technology, and operations.",
            "whyJoin": "Accenture is renowned for its outstanding entry-level training programs, diverse global clients, supportive work culture, and clear career growth pathways.",
            "howToApply": "Click the application link, fill out your details on the Accenture careers site, complete your candidate profile, and submit your resume.",
            "finalThoughts": "A great chance to grow your skills at scale. Don't miss this opportunity, apply today!"
        },
        "tcs": {
            "aboutCompany": "Tata Consultancy Services (TCS) is an IT services, consulting, and business solutions provider that has partnered with global enterprises for over 50 years.",
            "whyJoin": "TCS provides exceptional job stability, extensive continuous learning via the TCS iON platform, a supportive environment, and international career options.",
            "howToApply": "Click the apply link, navigate to the TCS NextStep portal or careers page, enter your academic details, and submit.",
            "finalThoughts": "A perfect start to build a long-term foundation in the IT industry. Wish you success!"
        },
        "infosys": {
            "aboutCompany": "Infosys is a global leader in next-generation digital services and technology consulting, operating across more than 50 countries.",
            "whyJoin": "Infosys is famous for its world-class training academy at Mysore, robust mentorship, and strong focus on upskilling in artificial intelligence and cloud technologies.",
            "howToApply": "Click the apply link to access the Infosys job application form, upload your resume, and verify your credentials.",
            "finalThoughts": "Take the first step toward a bright future. Apply now!"
        },
        "wipro": {
            "aboutCompany": "Wipro Limited is a premier global information technology, consulting, and business process services company.",
            "whyJoin": "Wipro offers a highly collaborative work culture, structured fresher induction programs, and diverse project exposure across global industries.",
            "howToApply": "Click the application link to go to Wipro's talent portal, fill in the candidate application form, and submit your CV.",
            "finalThoughts": "An excellent opportunity to kickstart your tech journey. Apply today!"
        },
        "cognizant": {
            "aboutCompany": "Cognizant is a multinational technology company that helps clients modernize legacy technology, reimagine processes, and transform user experiences.",
            "whyJoin": "Cognizant offers rapid professional growth, comprehensive digital training platforms, and a vibrant workspace for entry-level developers.",
            "howToApply": "Click the apply link, register on the Cognizant careers page, fill in your profile, and submit your application.",
            "finalThoughts": "Start your digital career on the right foot. Good luck with your application!"
        },
        "google": {
            "aboutCompany": "Google is a global technology company specializing in internet-related services, cloud computing, search engine technology, software, and hardware.",
            "whyJoin": "Google offers a highly creative, collaborative work environment, cutting-edge engineering challenges, and industry-leading mentorship and perks.",
            "howToApply": "Click the apply link, review the job requirements on the Google Careers site, upload your resume, and apply online.",
            "finalThoughts": "A dream opportunity to make a massive global impact. Make sure to put your best foot forward!"
        },
        "microsoft": {
            "aboutCompany": "Microsoft is a leading multinational technology corporation known for developing software, consumer electronics, and world-class cloud platforms.",
            "whyJoin": "Microsoft provides an empowering culture, flexible working modes, top-tier compensation, and resources to innovate on next-gen AI and cloud tools.",
            "howToApply": "Click the application link, sign in to Microsoft Careers, enter your details, and submit your resume.",
            "finalThoughts": "Launch your career with one of the most respected tech giants in the world. Best wishes!"
        },
        "amazon": {
            "aboutCompany": "Amazon is a global technology pioneer focusing on e-commerce, cloud computing (AWS), digital entertainment, and smart devices.",
            "whyJoin": "Amazon provides a high-ownership environment, fast-paced career advancement, and the chance to build systems that scale to millions of transactions.",
            "howToApply": "Click the apply link, complete your registration on Amazon Jobs, take any required assessments, and submit your application.",
            "finalThoughts": "A stellar company to gain fast engineering velocity. Apply as soon as possible!"
        },
        "capgemini": {
            "aboutCompany": "Capgemini is a multicultural global consulting and technology services leader enabling client business transformation.",
            "whyJoin": "Capgemini offers international mobility prospects, structured talent development, and a strong culture of collaboration and sustainability.",
            "howToApply": "Click the apply link to go to Capgemini's careers portal, complete the application form, and submit your CV.",
            "finalThoughts": "A great place to work with high global standards. Apply now!"
        },
        "myntra": {
            "aboutCompany": "Myntra is India's premier e-commerce platform for fashion, beauty, and lifestyle brands, delivering personalized shopping experiences.",
            "whyJoin": "Myntra offers direct exposure to high-scale e-commerce tech stacks, modern front-end/back-end frameworks, and a highly agile dev culture.",
            "howToApply": "Click the application link, fill out the application on Myntra's hiring portal, upload your resume, and submit.",
            "finalThoughts": "Join a highly dynamic and fashionable tech team. We wish you the best!"
        },
        "flipkart": {
            "aboutCompany": "Flipkart is one of India's leading digital commerce giants, empowering digital transactions and e-commerce services nationwide.",
            "whyJoin": "Flipkart offers complex engineering opportunities in high-performance distributed databases, logistics tech, and payment gateways.",
            "howToApply": "Click the apply link, log in or sign up on the Flipkart Careers page, enter your details, and submit your resume.",
            "finalThoughts": "A fantastic team to build state-of-the-art consumer systems. Apply today!"
        }
    }
    
    # 🔍 Try to find a match
    matched_profile = None
    for key, profile in profiles.items():
        if key in company_lower:
            matched_profile = profile
            break
            
    # fallback generic profiles
    if not matched_profile:
        matched_profile = {
            "aboutCompany": f"{company} is a leading organization dedicated to delivering innovation and excellence in its field. The company is committed to cultivating a diverse workforce and providing a growth-oriented environment for its employees.",
            "whyJoin": "This role provides a fantastic opportunity to collaborate with experienced professionals, work on impactful projects, accelerate your skill development, and build a rewarding career.",
            "howToApply": f"Click on the apply link to navigate to the official career portal for {company}, complete the registration form with your details, upload your CV, and submit.",
            "finalThoughts": "A wonderful chance to advance your career. Make sure to apply soon to secure your application!"
        }
        
    # Apply to job object if the field is empty, missing, or a placeholder
    forbidden_terms = ["not mentioned", "not specified", "not disclosed", "confidential", "hiring company", ""]
    
    for field in ["aboutCompany", "whyJoin", "howToApply", "finalThoughts"]:
        val = str(job.get(field, "")).strip()
        val_lower = val.lower()
        if not val or any(term == val_lower for term in forbidden_terms):
            job[field] = matched_profile[field]

def is_valid_job(job):
    """
    Validates the job details. If any required information is missing, not specified, 
    not disclosed, or not mentioned, we fill in a default or guess to ensure we do not skip.
    """
    # 🚫 Sarkari Result Rejection Filter
    for field in ["title", "company", "applyLink", "sourceWebsite", "sourceUrl", "jobDescription"]:
        val = str(job.get(field, "")).lower()
        if "sarkariresult" in val or "sarkari result" in val:
            return False, f"Sarkari Result reference detected in '{field}'"

    # Normalize title and company to standard Latin characters (preserving case)
    if job.get("title"):
        job["title"] = normalize_text_keep_case(job["title"])
    if job.get("company"):
        job["company"] = normalize_text_keep_case(job["company"])

    # Reject training, certification, bootcamp, academy, and course postings
    title = job.get("title", "")
    if title:
        title_lower = normalize_text(title)
        forbidden_title_keywords = ["certification", "course", "bootcamp", "training", "academy", "certified"]
        if any(kw in title_lower for kw in forbidden_title_keywords):
            return False, f"Job title '{title}' contains training/certification keyword"

    # Expiry Check (Skip if last date is in the past)
    last_date = job.get("lastDate")
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
                return False, f"Job has expired. Last date '{last_date_str}' is in the past (today is {date.today()})."

    # Auto-default salary and batch if missing or containing forbidden placeholders
    forbidden_terms = ["not mentioned", "not specified", "not disclosed", "confidential", "hiring company"]
    
    is_govt = job.get("isGovernment") is True or str(job.get("isGovernment")).lower() == "true"
    
    if is_govt:
        # 1. Auto-default salary — "As per notification" is valid for govt jobs
        salary = job.get("salary")
        if not salary or any(term in str(salary).lower() for term in forbidden_terms):
            parsed = parse_salary_fallback(job.get("jobDescription") or "")
            job["salary"] = parsed if parsed else "As per notification"
            
        # 2. Auto-default vacancies
        vacancies = job.get("vacancies")
        if not vacancies or any(term in str(vacancies).lower() for term in forbidden_terms):
            job["vacancies"] = "Various Vacancies"
            
        # 3. Auto-default eligibility
        eligibility = job.get("eligibility")
        if not eligibility or any(term in str(eligibility).lower() for term in forbidden_terms):
            job["eligibility"] = "As per notification"
            
        # 4. Auto-default company
        if not job.get("company"):
            job["company"] = "Govt Department"

        # Govt jobs only need company + eligibility + vacancies
        check_keys = ["company", "eligibility", "vacancies"]
    else:
        # 1. Auto-default salary
        salary = job.get("salary")
        if not salary or any(term in str(salary).lower() for term in forbidden_terms):
            parsed = parse_salary_fallback(job.get("jobDescription") or "")
            job["salary"] = parsed if parsed else "Best in Industry"
            
        # 2. Auto-default batch
        batch = job.get("batch")
        if not batch or any(term in str(batch).lower() for term in forbidden_terms):
            job["batch"] = "2024 / 2025 / 2026"
            
        # 3. Auto-default company (guess from title or URL first, then fallback to Top Company)
        company = job.get("company")
        
        forbidden_companies = {
            "pdlink", "placement drive", "placement drive link", "placementkit", 
            "nextjobpost", "next job post", "cseofficial", "it jobs career", 
            "joblii", "seekeras", "freshershunt", "fresherearth", "telegram", 
            "whatsapp", "youtube", "google form", "google doc", "hiring company",
            "placement link", "job post", "job alert"
        }
        
        company_lower = normalize_text(company) if company else ""
        is_forbidden_company = False
        
        for term in forbidden_terms:
            if term in company_lower:
                is_forbidden_company = True
                break
                
        if not is_forbidden_company:
            for term in forbidden_companies:
                if term == company_lower or company_lower.startswith(term + " ") or company_lower.endswith(" " + term) or (" " + term + " ") in (" " + company_lower + " "):
                    is_forbidden_company = True
                    break
        
        # Sentence / description checks to discard full sentences extracted as company names
        if not is_forbidden_company and company:
            sentence_indicators = [
                "this is", "opportunity to", "career with", "leading global", 
                "hiring for", "we are", "looking for", "about the", "join our", 
                "work with", "leading company", "fast growing", "is looking", 
                "is hiring", "apply now", "click here", "link in"
            ]
            comp_words = str(company).split()
            if len(comp_words) > 4 or len(str(company)) > 30 or any(indicator in company_lower for indicator in sentence_indicators):
                is_forbidden_company = True
        
        if not company or is_forbidden_company:
            guessed = guess_company_from_title(job.get("title"))
            if not guessed:
                guessed = get_company_from_link(job.get("applyLink"))
            
            # If the guessed company is also forbidden/placeholder, don't use it, fall back to "Top Company"
            if guessed:
                guessed_lower = normalize_text(guessed)
                is_guessed_forbidden = False
                for term in forbidden_terms:
                    if term in guessed_lower:
                        is_guessed_forbidden = True
                        break
                if not is_guessed_forbidden:
                    for term in forbidden_companies:
                        if term == guessed_lower or guessed_lower.startswith(term + " ") or guessed_lower.endswith(" " + term) or (" " + term + " ") in (" " + guessed_lower + " "):
                            is_guessed_forbidden = True
                            break
                if is_guessed_forbidden:
                    guessed = None
            
            job["company"] = guessed or "Top Company"
            
        # 4. Auto-default location
        location = job.get("location")
        if not location or any(term in str(location).lower() for term in forbidden_terms):
            job["location"] = "Pan India"
            
        # 5. Auto-default experience
        experience = job.get("experience")
        if not experience or any(term in str(experience).lower() for term in forbidden_terms):
            job["experience"] = "Fresher / 0-2 Years"
            
        # 6. Auto-default education
        education = job.get("education")
        if not education or any(term in str(education).lower() for term in forbidden_terms):
            job["education"] = "Any Graduate"
            
        # Key fields to check
        check_keys = ["company", "location", "salary", "experience", "education", "batch"]
    
    # Phrases that are legitimate defaults for govt jobs (not actual placeholders)
    govt_accepted_values = {"as per notification", "as per official notification", "various vacancies"}
    
    for key in check_keys:
        val = job.get(key)
        if not val:
            return False, f"Missing required field: {key}"
        
        val_lower = str(val).strip().lower()
        # Skip forbidden check for accepted govt defaults
        if val_lower in govt_accepted_values:
            continue
        if any(term in val_lower for term in forbidden_terms):
            return False, f"Placeholder/Missing value '{val}' detected in field: {key}"
            
    enrich_company_details(job)
    return True, ""

async def extract_with_ai(text):
    """Uses modern Gemini 2.5 Flash to extract job fields"""
    if not API_KEY or not client_gemini:
        print("💡 API_KEY (Gemini) not found in .env, using basic parser...")
        return extract_basic(text)

    prompt = f"""
Analyze this Telegram job posting and extract the details.
Return ONLY a valid, raw JSON object (no markdown formatting, no `json` blocks) with the following exact keys:
"title", "company", "location", "applyLink", "type", "experience", "education", "shortSummary", "htmlDescription", "responsibilities", "requirements", "skills", "batch", "salary", "lastDate", "aboutCompany", "whyJoin", "howToApply", "finalThoughts", "eligibility", "vacancies", "isGovernment".

Rules:
1. DO NOT guess, fabricate, or generate any details that are not explicitly present in the job posting text.
2. If any of the following fields are not clearly and explicitly specified in the text, you MUST set their value exactly to "Not Mentioned":
   - "company" (Do NOT guess from the apply link domain, do NOT use "Hiring Company" or "Confidential")
   - "location" (Do NOT default to "Pan India" or "Remote")
   - "salary"
   - "experience"
   - "education"
   - "batch"
   - "eligibility"
   - "vacancies"
3. 'type' MUST be one of: "Full-Time", "Part-Time", "Internship", "Contract", "Remote", "Hybrid".
4. 'applyLink' must be the first http/https link found.
5. 'shortSummary' MUST be a clean, professional 15-20 word summary of the role. NO emojis.
6. 'htmlDescription' MUST be beautifully formatted HTML based on the provided text. Use <h2>, <ul>, <li>, <br/> and <strong> tags.
7. 'responsibilities' MUST be a JSON array of strings detailing the job role. If none, return [].
8. 'requirements' MUST be a JSON array of strings detailing eligibility. If none, return [].
9. 'skills' MUST be a JSON array of strings. If none, return [].
10. 'lastDate' MUST be either an empty string "" or a valid date string if a deadline is mentioned.
11. 'aboutCompany' MUST be a detailed 3-4 sentence professional context about the extracted company. Generate this intelligently only if the company name is actually present, otherwise set to "".
12. 'whyJoin' MUST be a persuasive 3-4 sentence paragraph highlighting the benefits of working at this company for this role.
13. 'howToApply' MUST be clear, step-by-step instructions detailing the application process for the candidate.
14. 'finalThoughts' MUST be a short, encouraging concluding mark wishing the applicant success.
15. 'eligibility' MUST be the qualification required for government jobs, or set to "Not Mentioned" if not specified.
16. 'vacancies' MUST be the number of vacancies/posts available (e.g. "500 Posts"), or set to "Not Mentioned" if not specified.
17. 'isGovernment' MUST be a boolean (true or false). Set to true if the job/post is a government recruitment, central/state government exam, admit card, answer key, result, or government agency post (e.g., SSC, UPSC, Bank PO, Railway, PSU, PSC, Defence, etc.). Otherwise, set to false.

Job Posting Text:
{text}
"""
    candidate_models = [
        "gemini-2.5-flash-lite",   # Most efficient — try first
        "gemini-2.5-flash",        # Stronger fallback
        "gemini-2.0-flash"         # Final fallback
    ]
    
    data = None
    last_error = None
    for model in candidate_models:
        try:
            print(f"🤖 Parsing with Gemini model: {model}...")
            response = await client_gemini.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            clean_json = response.text.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json[7:-3].strip()
            elif clean_json.startswith("```"):
                clean_json = clean_json[3:-3].strip()
                
            data = json.loads(clean_json)
            break  # ✅ Success — stop trying other models
        except Exception as e:
            last_error = e
            err_str = str(e)
            if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                print(f"⚠️ Model {model} rate limited (429). Switching to next model...")
            elif "NOT_FOUND" in err_str or "404" in err_str:
                print(f"⚠️ Model {model} not found (404). Switching to next model...")
            else:
                print(f"⚠️ Model {model} failed: {e}. Switching to next model...")
            # No waiting — immediately try next model or fall back to basic parser
                
    if not data:
        # ✅ Regex + BeautifulSoup parser — fast, reliable, no quota limits
        print(f"⚠️ All Gemini models failed ({last_error}). Using regex/BS4 basic parser instantly.")
        return extract_basic(text)

        
    # 🎨 Give the beautiful HTML text to the job detail page, and clean summary to the home page cards
    title_val = data.get("title", "Job Opening")
    data["jobDescription"] = data.get("htmlDescription", text)
    data["description"] = data.get("shortSummary", title_val[:150] + "...")
    data["aboutCompany"] = data.get("aboutCompany", "")
    data["whyJoin"] = data.get("whyJoin", "")
    data["howToApply"] = data.get("howToApply", "")
    data["finalThoughts"] = data.get("finalThoughts", "")
    data["highlightText"] = data.get("title", "Freshers Eligible")
    data["eligibility"] = data.get("eligibility", "")
    data["vacancies"] = data.get("vacancies", "")
    data["isGovernment"] = data.get("isGovernment") is True or str(data.get("isGovernment")).lower() == "true"
    base_slug = slugify(data.get("title", "Job Opening"))
    unique_id = hashlib.md5(text.encode()).hexdigest()[:5]
    data["slug"] = f"{base_slug}-{unique_id}"
    
    # 🚀 Inject the predefined WhatsApp & Telegram Social links!
    data["whatsapp"] = "https://chat.whatsapp.com/LVpuUJluTpUEdIc4daAemQ"
    data["telegram"] = "https://t.me/nextjobpost"
    
    return data

# =========================
# STEP 1A → POSTER GENERATOR & UPLOAD WITH RETRY
# =========================
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = "fonts"
FONT_PATH = os.path.join(FONT_DIR, "Roboto-Bold.ttf")
FONT_URL = "https://raw.githubusercontent.com/googlefonts/roboto/master/src/hinted/Roboto-Bold.ttf"

async def ensure_font_downloaded():
    """Asynchronously downloads Roboto-Bold font from GitHub/GoogleFonts raw repository."""
    if not os.path.exists(FONT_PATH):
        os.makedirs(FONT_DIR, exist_ok=True)
        print("📥 [POSTER] Downloading Roboto-Bold font from Google Fonts GitHub repository...")
        try:
            async with aiohttp.ClientSession() as session:
                headers = {'User-Agent': 'Mozilla/5.0'}
                async with session.get(FONT_URL, headers=headers, timeout=30) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        with open(FONT_PATH, "wb") as f:
                            f.write(content)
                        print("✅ [POSTER] Font downloaded successfully!")
                    else:
                        print(f"⚠️ [POSTER] Font download failed with status {resp.status}")
        except Exception as e:
            print(f"⚠️ [POSTER] Font download failed: {e}")

def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        w = font.getbbox(test_line)[2]
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def generate_poster(title, company, location, salary, output_path):
    """Generates a professional 1200x630 job poster dynamically with Pillow."""
    width, height = 1200, 630
    
    # 1. Create a beautiful deep space blue/indigo gradient
    base_grad = Image.new("RGB", (2, 2))
    base_grad.putpixel((0, 0), (15, 23, 42))  # Slate 900
    base_grad.putpixel((1, 0), (30, 41, 59))  # Slate 800
    base_grad.putpixel((0, 1), (15, 25, 45))  # Deep Space Blue
    base_grad.putpixel((1, 1), (43, 20, 85))  # Dark Indigo
    
    img = base_grad.resize((width, height), Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(img)
    
    # Load fonts
    try:
        font_logo = ImageFont.truetype(FONT_PATH, 28)
        font_company = ImageFont.truetype(FONT_PATH, 34)
        font_title = ImageFont.truetype(FONT_PATH, 54)
        font_meta = ImageFont.truetype(FONT_PATH, 24)
        font_btn = ImageFont.truetype(FONT_PATH, 26)
    except Exception as e:
        print(f"⚠️ Error loading font, using default: {e}")
        font_logo = font_company = font_title = font_meta = font_btn = ImageFont.load_default()
        
    # Draw branding logo top-left
    draw.text((80, 50), "NEXTJOBPOST.COM", fill=(56, 189, 248), font=font_logo)
    draw.line([(80, 95), (200, 95)], fill=(56, 189, 248), width=3)
    
    # Draw "WE ARE HIRING" / Company header
    draw.text((80, 140), f"WE ARE HIRING AT {company.upper()}", fill=(244, 63, 94), font=font_company)
    
    # Draw Job Title (with wrapping)
    wrapped_title = wrap_text(title, font_title, 1040)
    y_offset = 210
    for line in wrapped_title:
        draw.text((80, y_offset), line, fill=(255, 255, 255), font=font_title)
        y_offset += 75
        
    # Draw Meta details
    meta_y = y_offset + 30
    meta_text = []
    if location:
        meta_text.append(f"Location: {location}")
    if salary:
        meta_text.append(f"Salary: {salary}")
    
    if meta_text:
        draw.text((80, meta_y), "  |  ".join(meta_text), fill=(209, 213, 219), font=font_meta)
        
    # Draw Button at the bottom
    btn_x0, btn_y0 = 80, 500
    btn_x1, btn_y1 = 280, 560
    draw.rounded_rectangle([(btn_x0, btn_y0), (btn_x1, btn_y1)], radius=12, fill=(239, 68, 68))
    
    btn_txt = "Apply Now"
    btn_txt_w = font_btn.getbbox(btn_txt)[2] - font_btn.getbbox(btn_txt)[0]
    btn_txt_h = font_btn.getbbox(btn_txt)[3] - font_btn.getbbox(btn_txt)[1]
    
    btn_txt_x = btn_x0 + (btn_x1 - btn_x0 - btn_txt_w) // 2
    btn_txt_y = btn_y0 + (btn_y1 - btn_y0 - btn_txt_h) // 2 - 3
    
    draw.text((btn_txt_x, btn_txt_y), btn_txt, fill=(255, 255, 255), font=font_btn)
    
    # Save Image
    img.save(output_path, "PNG")


def render_text_block(job, width=1200, padding=40):
    """Render the full job text into an image block to append under/alongside a poster.
    Returns a PIL Image object containing the rendered text block."""
    from PIL import ImageFont

    # Prepare fonts
    try:
        font_title = ImageFont.truetype(FONT_PATH, 42)
        font_body = ImageFont.truetype(FONT_PATH, 24)
    except Exception:
        font_title = font_body = ImageFont.load_default()

    # Build the text content
    lines = []
    lines.append(job.get('title', 'Job Opening'))
    lines.append("\n")
    summary = job.get('shortSummary') or job.get('description') or ''
    if summary:
        lines.append(summary)
        lines.append("\n")

    fields = [
        ("Company", job.get('company', 'Top Company')),
        ("Location", job.get('location', 'Pan India')),
        ("Education", job.get('education', 'Any Graduate')),
        ("Experience", job.get('experience', 'Fresher / 0-2 Years')),
        ("Salary", job.get('salary', 'Best in Industry')),
        ("Job Type", job.get('type', 'Full-Time')),
    ]

    for k, v in fields:
        lines.append(f"{k}: {v}")

    # Responsibilities, Requirements, Skills
    if job.get('responsibilities'):
        lines.append('\nResponsibilities:')
        for r in job.get('responsibilities', [])[:6]:
            lines.append(f" - {r}")

    if job.get('requirements'):
        lines.append('\nRequirements:')
        for r in job.get('requirements', [])[:6]:
            lines.append(f" - {r}")

    if job.get('skills'):
        lines.append('\nSkills: ' + ', '.join(job.get('skills', [])[:10]))

    lines.append('\nApply: ' + job.get('applyLink', job.get('image', SITE_BASE_URL)))

    # Convert to single text string and wrap
    text = "\n".join(lines)

    # Create a temporary image to calculate height
    dummy = Image.new('RGB', (width, 10), color=(20, 25, 35))
    draw = ImageDraw.Draw(dummy)

    wrapped_lines = []
    for paragraph in text.split('\n'):
        if not paragraph:
            wrapped_lines.append('')
            continue
        # wrap by approximate character width using font metrics
        words = paragraph.split()
        cur = []
        for w in words:
            test = ' '.join(cur + [w])
            wbox = draw.textbbox((0, 0), test, font=font_body)
            if wbox[2] <= (width - 2 * padding):
                cur.append(w)
            else:
                wrapped_lines.append(' '.join(cur))
                cur = [w]
        if cur:
            wrapped_lines.append(' '.join(cur))

    # Estimate height
    line_height = (font_body.getbbox('Ay')[3] - font_body.getbbox('Ay')[1]) + 8
    title_height = (font_title.getbbox('Ay')[3] - font_title.getbbox('Ay')[1]) + 16
    total_height = padding + title_height + len(wrapped_lines) * line_height + padding

    block = Image.new('RGB', (width, max(400, total_height)), color=(18, 24, 36))
    draw = ImageDraw.Draw(block)

    # Draw title
    y = padding
    draw.text((padding, y), job.get('title', 'Job Opening'), fill=(255, 255, 255), font=font_title)
    y += title_height

    # Draw wrapped lines
    for ln in wrapped_lines:
        draw.text((padding, y), ln, fill=(230, 230, 230), font=font_body)
        y += line_height

    return block


def combine_image_with_text(image_path, job, output_path, width=1200):
    """Combine an existing image (photo or poster) with the rendered text block beneath it.
    Saves combined image to output_path and returns the path."""
    try:
        base = Image.open(image_path).convert('RGB')
    except Exception:
        # If cannot open, just render text block as image
        block = render_text_block(job, width=width)
        block.save(output_path, 'PNG')
        return output_path

    # Resize base to target width while keeping aspect
    w_percent = (width / float(base.size[0]))
    new_h = int((float(base.size[1]) * float(w_percent)))
    base_resized = base.resize((width, new_h), Image.Resampling.LANCZOS)

    text_block = render_text_block(job, width=width)

    # Create final combined image
    final_h = base_resized.size[1] + text_block.size[1]
    final = Image.new('RGB', (width, final_h), (18, 24, 36))
    final.paste(base_resized, (0, 0))
    final.paste(text_block, (0, base_resized.size[1]))

    final.save(output_path, 'PNG')
    return output_path

async def upload_image_to_api(session, file_path, retries=3, delay=5):
    """
    Uploads an image to the Render backend.
    Includes cold-start mitigation, timeout/HTML response handling, and 3 retries.
    """
    # 1. Cold start handling: Ping the backend API
    health_url = API_URL.replace("/jobs", "/health")
    print(f"⏳ [UPLOAD] Pinging Render backend ({health_url}) to mitigate cold start...")
    try:
        async with session.get(health_url, timeout=60) as res:
            await res.read()
    except Exception as e:
        print(f"⚠️ [UPLOAD] Backend ping failed (expected if completely cold): {e}")

    # 2. Wait 5 seconds to ensure backend starts up/receives connections
    print("⏳ [UPLOAD] Waiting 5 seconds for Render backend connection readiness...")
    await asyncio.sleep(5)

    headers = {}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"

    upload_url = API_URL.replace("/jobs", "/upload/image")
    
    for attempt in range(1, retries + 1):
        print(f"📸 [UPLOAD] Attempt {attempt}/{retries}: Uploading {os.path.basename(file_path)}...")
        try:
            data = aiohttp.FormData()
            data.add_field('image',
                           open(file_path, 'rb'),
                           filename=os.path.basename(file_path),
                           content_type='image/jpeg')

            async with session.post(upload_url, data=data, headers=headers, timeout=30) as res:
                # Detect 503 Service Unavailable
                if res.status == 503:
                    print(f"⚠️ [UPLOAD] 503 Service Unavailable on attempt {attempt}")
                    if attempt < retries:
                        await asyncio.sleep(delay * attempt)
                        continue
                    break

                # Detect HTML response page (Render proxy/routing errors)
                content_type = res.headers.get("Content-Type", "")
                if "text/html" in content_type:
                    print(f"⚠️ [UPLOAD] Received HTML page instead of JSON on attempt {attempt}")
                    if attempt < retries:
                        await asyncio.sleep(delay * attempt)
                        continue
                    break

                # Try parsing JSON
                try:
                    resp_data = await res.json()
                except Exception as json_err:
                    print(f"⚠️ [UPLOAD] Invalid JSON output on attempt {attempt}: {json_err}")
                    if attempt < retries:
                        await asyncio.sleep(delay * attempt)
                        continue
                    break

                # Handle success response
                if resp_data.get("success"):
                    img_url_val = resp_data.get('imageUrl', '')
                    if img_url_val.startswith("http://") or img_url_val.startswith("https://"):
                        image_url = img_url_val
                    else:
                        try:
                            from urllib.parse import urlparse
                            parsed = urlparse(API_URL)
                            base_url = f"{parsed.scheme}://{parsed.netloc}"
                        except Exception:
                            base_url = "https://job-tdg8.onrender.com"
                        image_url = f"{base_url}{img_url_val}"
                    print(f"✅ [UPLOAD] Success! URL: {image_url}")
                    return image_url
                else:
                    print(f"⚠️ [UPLOAD] API returned success=False on attempt {attempt}: {resp_data}")

        except asyncio.TimeoutError:
            print(f"⚠️ [UPLOAD] Request timed out on attempt {attempt}")
        except FileNotFoundError:
            print(f"❌ [UPLOAD] File not found: {file_path}")
            break
        except Exception as e:
            print(f"⚠️ [UPLOAD] Unexpected error on attempt {attempt}: {e}")

        if attempt < retries:
            wait_time = delay * attempt
            print(f"⏳ [UPLOAD] Waiting {wait_time}s before retry...")
            await asyncio.sleep(wait_time)

    print("❌ [UPLOAD] Failed to upload image after all retries.")
    return ""

# =========================
# STEP 1B → SEND TO API FIRST
# =========================
async def send_to_api(session, job):
    headers = {
        "Content-Type": "application/json"
    }
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
        
    try:
        async with session.post(API_URL, json=job, headers=headers, timeout=30) as res:
            try:
                data = await res.json()
                return data
            except:
                return None
    except Exception as e:
        print(f"❌ [API] Failed to post job to API: {e}")
        return None

def build_post(job, slug):
    """Build a rich, fully-featured Telegram post with maximum engagement."""
    job_url    = f"{SITE_BASE_URL}/{slug}"
    title      = job.get('title', 'Job Opening')
    company    = job.get('company', 'Top Company')
    
    is_govt = job.get("isGovernment") is True or str(job.get("isGovernment")).lower() == "true"
    
    # ── Skills (up to 6) ──
    skills_raw = job.get('skills', [])
    skills_section = ''
    if skills_raw:
        skill_list = '  •  '.join(skills_raw[:6])
        skills_section = f"\n🛠 **Skills:** {skill_list}\n"

    # ── Responsibilities (up to 3) ──
    resp_raw = job.get('responsibilities', [])
    resp_section = ''
    if resp_raw:
        bullets = '\n'.join(f'   ▸ {r}' for r in resp_raw[:3])
        resp_section = f"\n📋 **What You'll Do:**\n{bullets}\n"

    # ── Requirements (up to 3) ──
    req_raw = job.get('requirements', [])
    req_section = ''
    if req_raw:
        bullets = '\n'.join(f'   ✔ {r}' for r in req_raw[:3])
        req_section = f"\n✅ **Requirements:**\n{bullets}\n"

    # ── Why Join ──
    why_join   = job.get('whyJoin', '')
    why_section = ''
    if why_join:
        trimmed = why_join[:180].rstrip()
        why_section = f"\n💡 **Why Join?**\n{trimmed}...\n"

    # ── How to Apply ──
    how_apply  = job.get('howToApply', '')
    how_section = ''
    if how_apply:
        trimmed = how_apply[:200].rstrip()
        how_section = f"\n📝 **How to Apply:**\n{trimmed}\n"

    summary    = job.get('shortSummary', '') or job.get('description', '')
    summary_line  = f"\n📣 {summary}\n" if summary else ''
    final_note = job.get('finalThoughts', '')
    final_section = ''
    if final_note:
        final_section = f"\n✨ {final_note}\n"

    if is_govt:
        eligibility = job.get('eligibility', 'As per notification')
        vacancies = job.get('vacancies', 'Various Vacancies')
        salary = job.get('salary', 'Best in Industry')
        last_date = job.get('lastDate', '')
        deadline_line = f"⏰ **Last Date:**  {last_date}\n" if last_date else ''
        
        return (
            f"🔥 **{title}** 🔥\n"
            f"{summary_line}"
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎓 **Eligibility:** {eligibility}\n"
            f"🔢 **Vacancies:**   {vacancies}\n"
            f"💰 **Salary:**      {salary}\n"
            f"{deadline_line}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
            f"{skills_section}"
            f"{resp_section}"
            f"\n🔗 **Apply Here →** {job_url}\n"
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 **Next Job Post** — Your daily job alert hub\n"
            f"🌐 More Jobs:  {SITE_BASE_URL}\n"
            f"💼 LinkedIn:   https://www.linkedin.com/in/next-job-post-199b5b371\n"
            f"👉 **Join Channel:** https://t.me/nextjobpost\n"
        )
    else:
        location   = job.get('location', 'Pan India')
        education  = job.get('education', 'Any Graduate')
        experience = job.get('experience', 'Fresher / 0-2 Years')
        salary     = job.get('salary', 'Best in Industry')
        batch      = job.get('batch', '2024 / 2025 / 2026')
        job_type   = job.get('type', 'Full-Time')
        last_date  = job.get('lastDate', '')
        
        batch_line    = f"🎯 **Batch:**      {batch}\n" if batch else ''
        type_line     = f"💼 **Job Type:**   {job_type}\n"
        deadline_line = f"⏰ **Last Date:**  {last_date}\n" if last_date else ''

        return (
            f"🔥 **{title}** 🔥\n"
            f"{summary_line}"
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏢 **Company:**    {company}\n"
            f"📍 **Location:**   {location}\n"
            f"🎓 **Education:**  {education}\n"
            f"⏳ **Experience:** {experience}\n"
            f"💰 **Salary:**     {salary}\n"
            f"{type_line}"
            f"{batch_line}"
            f"{deadline_line}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
            f"{skills_section}"
            f"{resp_section}"
            f"\n🔗 **Apply Here →** {job_url}\n"
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 **Next Job Post** — Your daily job alert hub\n"
            f"🌐 More Jobs:  {SITE_BASE_URL}\n"
            f"💼 LinkedIn:   https://www.linkedin.com/in/next-job-post-199b5b371\n"
            f"👉 **Join Channel:** https://t.me/nextjobpost\n"
        )

def build_post_caption(job, slug):
    """Build a compact Telegram image caption (max ~1000 chars to stay within limit)."""
    job_url    = f"{SITE_BASE_URL}/{slug}"
    title      = job.get('title', 'Job Opening')
    company    = job.get('company', 'Top Company')
    
    is_govt = job.get("isGovernment") is True or str(job.get("isGovernment")).lower() == "true"
    if is_govt:
        eligibility = job.get('eligibility', 'As per notification')
        vacancies   = job.get('vacancies', 'Various Vacancies')
        salary      = job.get('salary', 'Best in Industry')
        caption = (
            f"🔥 {title}\n"
            f"🏢 {company}\n"
            f"🎓 Eligibility: {eligibility} | 👥 Vacancies: {vacancies} | 💰 {salary}\n"
            f"\n🔗 Apply: {job_url}\n"
            f"👉 Join: https://t.me/nextjobpost"
        )
    else:
        location   = job.get('location', 'Pan India')
        salary     = job.get('salary', 'Best in Industry')
        caption = (
            f"🔥 {title}\n"
            f"🏢 {company}\n"
            f"📍 {location} | 💰 {salary}\n"
            f"\n🔗 Apply: {job_url}\n"
            f"👉 Join: https://t.me/nextjobpost"
        )
    
    # Ensure caption doesn't exceed Telegram's 1024 char limit for media
    if len(caption) > 1024:
        if is_govt:
            eligibility = job.get('eligibility', 'As per notification')
            vacancies   = job.get('vacancies', 'Various Vacancies')
            salary      = job.get('salary', 'Best in Industry')
            caption = (
                f"🔥 {title[:80]}\n"
                f"🏢 {company[:50]}\n"
                f"🎓 {eligibility[:40]} | 👥 {vacancies[:30]} | 💰 {salary[:30]}\n"
                f"\n🔗 Apply: {job_url}\n"
                f"👉 Join: https://t.me/nextjobpost"
            )
        else:
            location   = job.get('location', 'Pan India')
            salary     = job.get('salary', 'Best in Industry')
            caption = (
                f"🔥 {title[:80]}\n"
                f"🏢 {company[:50]}\n"
                f"📍 {location[:40]} | 💰 {salary[:40]}\n"
                f"\n🔗 Apply: {job_url}\n"
                f"👉 Join: https://t.me/nextjobpost"
            )
    
    return caption

# =========================
# STEP 2B → POST TO LINKEDIN (Rich + Image)
# =========================
def build_linkedin_post(job, slug):
    """Build a rich, fully-detailed LinkedIn post optimised for reach and engagement."""
    job_url      = f"{SITE_BASE_URL}/{slug}"
    title        = job.get('title', 'Job Opening')
    company      = job.get('company', 'Top Company')
    
    is_govt = job.get("isGovernment") is True or str(job.get("isGovernment")).lower() == "true"
    
    job_type     = job.get('type', 'Full-Time')
    location     = job.get('location', 'Pan India')
    education    = job.get('education', 'Any Graduate')
    experience   = job.get('experience', 'Fresher / 0-2 Years')
    salary       = job.get('salary', 'Best in Industry')
    batch        = job.get('batch', '')
    last_date    = job.get('lastDate', '')
    summary      = job.get('shortSummary', '') or job.get('description', '')
    about_co     = job.get('aboutCompany', '')
    why_join     = job.get('whyJoin', '')
    how_apply    = job.get('howToApply', '')
    final_note   = job.get('finalThoughts', '')

    # ── Attention-grabbing opening hook ─────────────────────────────────
    if is_govt:
        hook = f"🏛️ New Government Job Alert! {company} is hiring!\n"
    elif 'intern' in job_type.lower() or 'intern' in title.lower():
        hook = f"🎓 Freshers & Students — This is YOUR moment! {company} is hiring!\n"
    elif 'remote' in location.lower() or 'remote' in job_type.lower():
        hook = f"🏠 Work from Anywhere! {company} has a Remote opening for you!\n"
    else:
        hook = f"🚀 Exciting Career Opportunity at {company}!\n"

    # ── About Company (2-3 sentences) ───────────────────────────────────
    about_section = ''
    if about_co:
        about_section = f"\n🏢 About {company}:\n{about_co}\n"

    # ── Skills bullet points (up to 6) ──────────────────────────────────
    skills_raw = job.get('skills', [])
    skills_section = ''
    if skills_raw:
        skill_bullets = '\n'.join(f'   ▸ {s}' for s in skills_raw[:6])
        skills_section = f'\n🛠️ Key Skills Required:\n{skill_bullets}\n'

    # ── Key responsibilities (up to 5) ──────────────────────────────────
    resp_raw = job.get('responsibilities', [])
    resp_section = ''
    if resp_raw:
        resp_bullets = '\n'.join(f'   📌 {r}' for r in resp_raw[:5])
        resp_section = f'\n📋 What You Will Do:\n{resp_bullets}\n'

    # ── Requirements (up to 5) ──────────────────────────────────────────
    req_raw = job.get('requirements', [])
    req_section = ''
    if req_raw:
        req_bullets = '\n'.join(f'   ✔ {r}' for r in req_raw[:5])
        req_section = f'\n✅ Who Should Apply:\n{req_bullets}\n'

    # ── Why Join section ────────────────────────────────────────────────
    why_section = ''
    if why_join:
        why_section = f'\n💡 Why Join {company}?\n{why_join}\n'

    # ── How to Apply ────────────────────────────────────────────────────
    how_section = ''
    if how_apply:
        how_section = f'\n📝 How to Apply:\n{how_apply}\n'

    # ── Optional badge lines ─────────────────────────────────────────────
    deadline_line = f"⏰ Last Date    : {last_date}  ← Don't miss the deadline!\n" if last_date else ''

    # ── Smart dynamic hashtags ───────────────────────────────────────────
    hashtag_set = {
        '#Hiring', '#Jobs', '#JobAlert', '#NextJobPost', '#Career',
        '#JobSearch', '#Recruitment', '#OpenToWork',
    }
    if is_govt:
        hashtag_set.update(['#GovtJobs', '#GovernmentJobs', '#SarkariNaukri', '#CentralGovtJobs'])
    else:
        if 'intern' in job_type.lower() or 'intern' in title.lower():
            hashtag_set.update(['#Internship', '#InternshipAlert', '#Fresher', '#CampusHiring'])
        else:
            hashtag_set.update(['#Fresher', '#JobOpening', '#NowHiring', '#OffCampus'])
        if any(t in title.lower() for t in ['software', 'developer', 'engineer', 'tech', 'data', 'python', 'java', 'devops', 'cloud']):
            hashtag_set.update(['#TechJobs', '#SoftwareJobs', '#ITJobs', '#TechHiring'])
        if 'remote' in location.lower() or 'remote' in job_type.lower():
            hashtag_set.update(['#RemoteJobs', '#WorkFromHome', '#RemoteWork'])
        if 'finance' in title.lower() or 'banking' in title.lower():
            hashtag_set.update(['#FinanceJobs', '#BankingJobs', '#BFSI'])
        if 'data' in title.lower() or 'analyst' in title.lower():
            hashtag_set.update(['#DataScience', '#Analytics', '#DataJobs'])
    hashtags = ' '.join(sorted(hashtag_set))

    if is_govt:
        eligibility = job.get('eligibility', 'As per notification')
        vacancies = job.get('vacancies', 'Various Vacancies')
        
        post_text = (
            f"{hook}\n"
            f"🔥 {title}\n"
            f"📣 {summary}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎓 Eligibility  : {eligibility}\n"
            f"🔢 Vacancies    : {vacancies}\n"
            f"💰 Salary       : {salary}\n"
            f"{deadline_line}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
            f"{resp_section}"
            f"{skills_section}"
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 Apply Now → {job_url}\n\n"
            f"📊 Follow NextJobPost for daily fresh opportunities!\n"
            f"📢 Telegram: https://t.me/nextjobpost\n"
            f"🌐 Website:  {SITE_BASE_URL}\n"
            f"\n👍 Like  |  🔁 Repost  |  💬 Tag someone who needs this!\n\n"
            f"{hashtags}"
        )
    else:
        batch_line    = f"🎯 Batch        : {batch}\n" if batch and batch.lower() not in ('not mentioned', 'not specified', '') else ''
        type_badge    = f"💼 Job Type     : {job_type}\n"
        
        post_text = (
            f"{hook}\n"
            f"🔥 {title}\n"
            f"📣 {summary}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 Location     : {location}\n"
            f"🎓 Education    : {education}\n"
            f"⏳ Experience   : {experience}\n"
            f"💰 Salary       : {salary}\n"
            f"{type_badge}"
            f"{batch_line}"
            f"{deadline_line}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
            f"{resp_section}"
            f"{skills_section}"
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 Apply Now → {job_url}\n\n"
            f"📊 Follow NextJobPost for daily fresh opportunities!\n"
            f"📢 Telegram: https://t.me/nextjobpost\n"
            f"🌐 Website:  {SITE_BASE_URL}\n"
            f"\n👍 Like  |  🔁 Repost  |  💬 Tag someone who needs this!\n\n"
            f"{hashtags}"
        )
    return post_text


async def _upload_image_to_linkedin(session, image_url: str) -> str:
    """
    Downloads the job image and uploads it to LinkedIn.
    Returns the LinkedIn asset URN string, or "" on failure.
    """
    headers_auth = {
        "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    # Step A: Register the upload
    register_payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": LINKEDIN_PERSON_URN,
            "serviceRelationships": [
                {
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent"
                }
            ]
        }
    }
    try:
        async with session.post(
            "https://api.linkedin.com/v2/assets?action=registerUpload",
            json=register_payload,
            headers=headers_auth,
            timeout=30
        ) as reg_resp:
            if reg_resp.status not in (200, 201):
                txt = await reg_resp.text()
                print(f"⚠️  LinkedIn image register failed [{reg_resp.status}]: {txt[:200]}")
                return ""
            reg_data = await reg_resp.json()
    except Exception as e:
        print(f"❌ LinkedIn image register error: {e}")
        return ""

    upload_url = (
        reg_data.get("value", {})
                .get("uploadMechanism", {})
                .get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {})
                .get("uploadUrl", "")
    )
    asset_urn = reg_data.get("value", {}).get("asset", "")

    if not upload_url or not asset_urn:
        print("⚠️  LinkedIn: could not parse uploadUrl or asset URN from register response.")
        return ""

    # Step B: Download the image bytes
    try:
        async with session.get(image_url, timeout=30) as img_resp:
            if img_resp.status != 200:
                print(f"⚠️  Could not download job image [{img_resp.status}]: {image_url}")
                return ""
            image_bytes = await img_resp.read()
    except Exception as e:
        print(f"❌ Image download error: {e}")
        return ""

    # Step C: Upload binary to LinkedIn's CDN
    try:
        async with session.put(
            upload_url,
            data=image_bytes,
            headers={
                "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
                "Content-Type": "image/jpeg"
            },
            timeout=30
        ) as put_resp:
            if put_resp.status not in (200, 201):
                txt = await put_resp.text()
                print(f"⚠️  LinkedIn image PUT failed [{put_resp.status}]: {txt[:200]}")
                return ""
            print(f"📸 LinkedIn image uploaded: {asset_urn}")
            return asset_urn
    except Exception as e:
        print(f"❌ LinkedIn image PUT error: {e}")
        return ""


async def post_to_linkedin(session, job, slug):
    """Post a rich job card to LinkedIn (with image if available)."""
    if not LINKEDIN_ACCESS_TOKEN or not LINKEDIN_PERSON_URN:
        print("⚠️  LinkedIn credentials missing in .env — skipping LinkedIn post.")
        return False

    post_text = build_linkedin_post(job, slug)

    # Strictly check that the generated LinkedIn post does not contain any forbidden/placeholder terms
    forbidden_terms = ["not mentioned", "not specified", "not disclosed", "confidential", "hiring company"]
    if any(term in post_text.lower() for term in forbidden_terms):
        print(f"🚫 [ABORT] Generated LinkedIn post contains placeholder terms. Skipping LinkedIn post.")
        return False
    job_url   = f"{SITE_BASE_URL}/{slug}"

    headers = {
        "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    # ── Try to attach image ──────────────────────────────────────────────────
    image_url = job.get("image", "")
    asset_urn = ""
    if image_url:
        print(f"📸 Uploading image to LinkedIn: {image_url}")
        asset_urn = await _upload_image_to_linkedin(session, image_url)

    # ── Build payload (image post vs article link) ───────────────────────────
    if asset_urn:
        # Rich IMAGE post — higher reach than plain article links
        media_block = [
            {
                "status": "READY",
                "media": asset_urn,
                "title": {"text": job.get('title', 'Job Opening')[:400]},
                "description": {"text": job.get('shortSummary', '')[:256]}
            }
        ]
        media_category = "IMAGE"
    else:
        # Fallback: article / link preview
        media_block = [
            {
                "status": "READY",
                "originalUrl": job_url,
                "title": {"text": job.get('title', 'Job Opening')[:400]},
                "description": {"text": job.get('shortSummary', '')[:256]}
            }
        ]
        media_category = "ARTICLE"

    payload = {
        "author": LINKEDIN_PERSON_URN,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": post_text},
                "shareMediaCategory": media_category,
                "media": media_block
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    try:
        async with session.post(
            "https://api.linkedin.com/v2/ugcPosts",
            json=payload,
            headers=headers,
            timeout=30
        ) as resp:
            if resp.status in (200, 201):
                data    = await resp.json()
                post_id = data.get('id', 'unknown')
                mode    = "with image 📸" if asset_urn else "with article link 🔗"
                print(f"✅ LinkedIn Posted {mode}! Post ID: {post_id}")
                return True
            else:
                text = await resp.text()
                print(f"⚠️  LinkedIn post failed [{resp.status}]: {text[:400]}")
                return False
    except Exception as e:
        print(f"❌ LinkedIn post error: {e}")
        return False


# =========================
# HANDLER
# =========================
async def process_and_post_job(job_data):
    """The master function that actually builds the posts and sends them out."""
    job = job_data["job"]
    image_path = job_data.get("image_path")
    h = job_data.get("hash")

    print(f"\n🚀 [SCHEDULER] Processing job: {job['title']}")

    # Double check that the job contains all real information and no placeholder/missing values
    is_valid, reason = is_valid_job(job)
    if not is_valid:
        print(f"🚫 [ABORT] Job '{job['title']}' has invalid or missing details: {reason}. Aborting social posts.")
        return False

    async with aiohttp.ClientSession() as session:
        # 1. Image Upload (Only if real image is present)
        uploaded_url = None
        has_real_image = image_path and os.path.exists(image_path) and os.path.getsize(image_path) > 0
        
        if has_real_image:
            uploaded_url = await upload_image_to_api(session, image_path)
            if uploaded_url:
                job["image"] = uploaded_url
                print(f"📸 Real image uploaded and bound: {uploaded_url}")
            else:
                job["image"] = ""
                print("⚠️ Failed to upload real image. Proceeding without image.")
        else:
            job["image"] = ""
            print("ℹ️ No real image to upload. Proceeding without image.")

        # 2. Website Post (non-blocking — social posts continue even if website fails)
        response = await send_to_api(session, job)
        print(f"🌐 Website status: {response}")

        if not isinstance(response, dict) or response.get("success") is not True:
            print(f"⚠️ Website API rejected or failed ({response}) — continuing with Telegram & LinkedIn anyway.")


        # Get final slug
        slug = job["slug"]
        if isinstance(response, dict):
            backend_slug = (
                response.get("slug")
                or (response.get("data") or {}).get("slug")
                or (response.get("job") or {}).get("slug")
            )
            if backend_slug: slug = backend_slug

        # 3. Telegram Post
        post = build_post(job, slug)

        # Strictly check that the generated Telegram post does not contain any forbidden/placeholder terms
        forbidden_terms = ["not mentioned", "not specified", "not disclosed", "confidential", "hiring company"]
        if any(term in post.lower() for term in forbidden_terms):
            print(f"🚫 [ABORT] Generated Telegram post contains placeholder terms. Skipping Telegram post.")
            return False

        try:
            # Prepend hidden image link using Markdown to let Telegram pull it as a premium preview banner
            if uploaded_url:
                telegram_post = f"[\u200b]({uploaded_url}){post}"
            else:
                telegram_post = post

            # Use raw SendMessageRequest with invert_media=True to show the image preview at the TOP of the message
            from telethon.tl.functions.messages import SendMessageRequest
            import random

            peer_entity = await client.get_input_entity(TARGET_CHANNEL)
            msg_text, entities = await client._parse_message_text(telegram_post, 'md')

            await client(SendMessageRequest(
                peer=peer_entity,
                message=msg_text,
                entities=entities,
                no_webpage=False if uploaded_url else True,
                invert_media=True if uploaded_url else False,
                random_id=random.randint(-2**63, 2**63 - 1)
            ))
            print(f"✔ Telegram Posted in a single unified message section.")
        except Exception as e:
            print(f"❌ Telegram failed: {e}")

        # 4. LinkedIn Post
        await post_to_linkedin(session, job, slug)

        # Cleanup image
        try:
            if image_path and os.path.exists(image_path):
                os.remove(image_path)
        except Exception:
            pass

        return True


async def scheduler_task():
    """Background loop that posts one job every POST_INTERVAL seconds (default 30 min)."""
    print(f"🕒 Scheduler started. Posting every {POST_INTERVAL}s ({POST_INTERVAL//60} min).")
    last_post_time = 0  # Track when last post went out
    while True:
        now = time.time()
        time_since_last = now - last_post_time

        # Only post if enough time has passed since last post
        if time_since_last >= POST_INTERVAL:
            queue = load_queue()
            processed_any = False
            
            while queue:
                job_data = queue.pop(0)  # Dequeue the oldest item
                save_queue(queue)
                
                job = job_data.get("job", {})
                is_valid, reason = is_valid_job(job)
                if not is_valid:
                    print(f"🚫 [SCHEDULER] Skipping invalid/expired job from queue: '{job.get('title')}' - Reason: {reason}")
                    continue
                
                print(f"\n📤 [SCHEDULER] Dequeued valid job. Remaining in queue: {len(queue)}")
                try:
                    success = await process_and_post_job(job_data)
                    if success:
                        last_post_time = time.time()  # Reset timer only after successful post
                        processed_any = True
                    else:
                        print(f"⚠️ [SCHEDULER] Job '{job.get('title')}' was aborted/skipped inside process_and_post_job. Checking next queue item immediately...")
                        continue  # Check the next queue item immediately without waiting 30 min!
                except Exception as e:
                    print(f"❌ [SCHEDULER] Processing error: {e}")
                    import traceback; traceback.print_exc()
                    last_post_time = time.time()  # Still reset on error to avoid rapid-fire error loops
                    processed_any = True
                
                break  # We successfully posted or encountered an execution error (and reset timer), exit queue loop
            
            if processed_any:
                remaining = load_queue()
                print(f"⏳ [SCHEDULER] Next post in {POST_INTERVAL//60} min. Queue size: {len(remaining)}")
            elif not queue:
                print(f"📭 [SCHEDULER] Queue empty (or only contained invalid/aborted jobs). Waiting... (checked at {time.strftime('%H:%M:%S')})")
        
        # Sleep 10 seconds then re-check — allows fast response when new jobs arrive
        await asyncio.sleep(10)


async def handler(event):
    raw_text = event.message.message or ""
    if not raw_text: return
    text = normalize_text_keep_case(raw_text)

    print(f"\n[DEBUG] 📩 Incoming message: {text[:60]}...")
    if not is_job(text): return

    h = hash_text(text)
    if h in seen: return

    # Check if this is a government job channel
    is_govt_channel = False
    try:
        chat = await event.get_chat()
        username = getattr(chat, 'username', '')
        if username and username.lower() in ["government_jobs_sarkari_naukri", "freejobalertofficial"]:
            is_govt_channel = True
    except Exception as e:
        print(f"Error checking channel username: {e}")

    # Check if message has an image
    is_image_doc = event.message.document and event.message.document.mime_type and event.message.document.mime_type.startswith('image/')
    has_image = bool(event.message.photo or is_image_doc)

    # Parse and extract fields using modern AI
    job = await extract_with_ai(text)
    if is_govt_channel:
        job["isGovernment"] = True
    
    # Verify that all required fields are present and valid (no "Not Mentioned" etc.)
    is_valid, reason = is_valid_job(job)
    if not is_valid:
        print(f"🚫 [SKIPPING] Job '{text[:30]}...' rejected: {reason}")
        return

    # Capture image if present
    image_path = ""
    if has_image:
        image_path = os.path.join(PENDING_IMAGES_DIR, f"{h}.jpg")
        try:
            await event.message.download_media(file=image_path)
            if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
                print(f"⚠️ Image download failed or file empty for job '{text[:30]}...'. Proceeding without image.")
                if os.path.exists(image_path):
                    try: os.remove(image_path)
                    except: pass
                image_path = ""
        except Exception as e:
            print(f"⚠️ Error downloading image: {e}. Proceeding without image.")
            image_path = ""

    # Add to queue
    queue = load_queue()
    queue.append({
        "job": job,
        "image_path": image_path,
        "hash": h,
        "timestamp": time.time()
    })
    save_queue(queue)
    
    # Mark as seen so we don't queue it twice
    seen.add(h)
    save_cache(seen)
    
    print(f"📥 Job Queued! Total in queue: {len(queue)}")


async def run_scraper_periodically():
    """Background task that runs the government jobs scraper periodically to populate the queue."""
    # Small startup delay so the main listener has booted up
    await asyncio.sleep(15)
    while True:
        print("\n🔄 [SCRAPER] Running government jobs scraper in the background...")
        try:
            # We run it using the same Python executable to preserve dependencies
            process = await asyncio.create_subprocess_exec(
                sys.executable, "scrape_govt_jobs.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            print(f"✅ [SCRAPER] Background scraper finished with exit code {process.returncode}")
            
            # Print a snippet of stdout/stderr for logging
            if stdout:
                lines = stdout.decode(errors='replace').splitlines()
                summary_out = "\n".join(lines[-5:]) if len(lines) > 5 else lines
                print(f"[SCRAPER Output snippet]:\n{summary_out}")
            if stderr and process.returncode != 0:
                print(f"[SCRAPER Error]: {stderr.decode(errors='replace')[:500]}")
        except Exception as e:
            print(f"❌ [SCRAPER] Failed to execute background scraper: {e}")
        
        # Sleep for 6 hours (21600 seconds) before running again
        await asyncio.sleep(21600)


# =========================
# RUN
# =========================
import time
async def main():
    await client.start()
    print("Dual Pipeline Job Agent with Scheduler Running...")

    
    # 🛡️ Validate channels
    valid_channels = []
    for ch in SOURCE_CHANNELS:
        try:
            entity = await client.get_input_entity(ch)
            valid_channels.append(entity)
        except Exception as e:
            print(f"⚠️ Skipping channel '{ch}': {e}")
            
    if not valid_channels:
        print("❌ No valid channels found.")
        return

    client.add_event_handler(handler, events.NewMessage(chats=valid_channels))
    
    print(f"👂 Listening to {len(valid_channels)} channels...")
    
    # Start the scheduler in the background
    asyncio.create_task(scheduler_task())
    
    # Start the government scraper in the background
    asyncio.create_task(run_scraper_periodically())
    
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())