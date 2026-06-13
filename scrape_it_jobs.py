import os
import json
import time
import hashlib
import logging
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# =========================
# LOGGING SETUP
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper_it.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

load_dotenv()

CACHE_FILE = "scraped_it_urls.json"
QUEUE_FILE = "job_queue.json"

def load_cache():
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception as e:
            logging.error(f"Error loading cache: {e}")
    return cache

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving cache: {e}")

def scrape_it_jobs():
    """
    Skeleton function to scrape IT jobs.
    You can use requests/BeautifulSoup or Selenium here.
    """
    logging.info("Starting IT Jobs scraper...")
    cache = load_cache()
    
    # Example placeholder job
    mock_jobs = [
        {
            "title": "Software Engineer (Backend)",
            "url": "https://example.com/job/software-engineer",
            "company": "Tech Corp",
            "experience": "1-3 Years",
            "salary": "₹12,00,000 PA",
            "applyLink": "https://example.com/job/software-engineer/apply"
        }
    ]
    
    # Load queue
    queue = []
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                queue = json.load(f)
        except Exception:
            queue = []
            
    added_jobs = 0
    
    for item in mock_jobs:
        href = item["url"]
        if href in cache:
            continue
            
        logging.info(f"New IT Job found: {item['title']}")
        
        # Build queue object
        slug = hashlib.md5(href.encode()).hexdigest()[:10]
        
        queue_job = {
            "title": item["title"],
            "slug": slug,
            "company": item["company"],
            "location": "India",
            "type": "Full-Time",
            "experience": item["experience"],
            "eligibility": "B.Tech/BE in CS/IT",
            "vacancies": "Multiple",
            "salary": item["salary"],
            "applyLink": item["applyLink"],
            "education": "B.Tech",
            "batch": "2023/2024",
            "lastDate": None,
            "jobDescription": f"<p>Great opportunity for {item['title']} at {item['company']}.</p>",
            "description": f"Hiring for {item['title']}",
            "shortSummary": f"Hiring for {item['title']}",
            "metaTitle": item["title"],
            "metaDescription": item["title"],
            
            # THE IMPORTANT PART: Tags it as Private/IT job for LinkedIn
            "isGovernment": False,
            "postType": "IT Job",
            
            "sourceWebsite": "example.com",
            "sourceUrl": href,
            "importantDates": "Apply ASAP",
            "pdfLink": "",
            "isActive": True,
            "whatsapp": "https://chat.whatsapp.com/LVpuUJluTpUEdIc4daAemQ",
            "telegram": "https://t.me/nextjobpost"
        }

        queue.append({
            "job": queue_job,
            "image_path": "", 
            "hash": slug,
            "timestamp": time.time()
        })
        
        cache[href] = time.time()
        added_jobs += 1
        
    # Save queue and cache
    if added_jobs > 0:
        try:
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(queue, f, indent=2)
            save_cache(cache)
            logging.info(f"Successfully queued {added_jobs} IT jobs.")
        except Exception as e:
            logging.error(f"Failed to write to queue: {e}")
    else:
        logging.info("No new IT jobs found.")

if __name__ == "__main__":
    scrape_it_jobs()
