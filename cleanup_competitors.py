import os
import requests
import json
import re
import sys

# Set up backend API URL
API_URL = os.getenv("API_URL", "https://nextjobpost-backend.onrender.com/api/jobs")
API_TOKEN = os.getenv("API_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok")

def clean_raw_text(val, is_html=False):
    if not val:
        return val
    if isinstance(val, list):
        return [clean_raw_text(item, is_html=is_html) for item in val]
    if not isinstance(val, str):
        return val
        
    competitor_domains = [
        r'freshershunt\.(?:in|com|org)',
        r'freshersvoice\.(?:in|com|org)',
        r'jobsarkari\.(?:in|com|org)',
        r'sarkariresult\.(?:in|com|org)',
        r'careerbywell\.(?:in|com|org)',
        r'sarkarijob\.(?:in|com|org)',
        r'freejobalert\.(?:in|com|org)',
        r'indgovtjobs\.(?:in|com|org)',
        r'govtjobsalert\.(?:in|com|org)'
    ]
    cleaned = val
    for comp in competitor_domains:
        cleaned = re.sub(r'(?i)https?://\S*' + comp + r'\S*', '', cleaned)
        cleaned = re.sub(r'(?i)\b\S*' + comp + r'\S*', '', cleaned)

    cleaned = re.sub(r'(?i)https?://\.in/\S*', '', cleaned)
    cleaned = re.sub(r'(?i)https?://\.in\b', '', cleaned)

    phrases_to_remove = [
        r'(?i)\bvisit\s+the\s+full\s+details\s+and\s+application\s+page\b',
        r'(?i)\bfollow\s+the\s+instructions\s+provided\s+on\s+the\s+page\s+to\s+complete\s+your\s+application\b',
        r'(?i)\bfor\s+a\s+detailed\s+guide\s+on\s+the\s+application\s+process\s*,\s*refer\s+to\s+the\s+youtube\s+video\b',
        r'(?i)\bclick\s+here\s+to\s+apply\b',
        r'(?i)\bofficial\s+website\b',
        r'(?i)\bofficial\s+notification\b',
        r'(?i)\bapply\s+online\b'
    ]
    for phrase in phrases_to_remove:
        cleaned = re.sub(phrase, '', cleaned)

    competitor_names = ['freshershunt', 'freshersvoice', 'jobsarkari', 'sarkariresult', 'careerbywell', 'sarkarijob', 'freejobalert', 'indgovtjobs', 'govtjobsalert']
    for name in competitor_names:
        cleaned = re.sub(r'(?i)\b' + name + r'\b', '', cleaned)

    # Only strip numbered lists if they are followed by spacing, avoiding decimal values in dates/numbers
    cleaned = re.sub(r'\b\d+\.\s*(?:\.|:|-)*\s+', '', cleaned)

    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'\.\s*\.+', '.', cleaned)
    cleaned = re.sub(r'-\s*-+', '-', cleaned)
    cleaned = re.sub(r':\s*:+', ':', cleaned)
    cleaned = re.sub(r'\.\s*\.', '.', cleaned)
    cleaned = re.sub(r':\s*\.', ':', cleaned)

    strip_chars = " -|:_!@#%^&*()[]{}.,/\\\"'" if is_html else " -|:_!@#%^&*()[]{}<>.,/\\\"'"
    cleaned = cleaned.strip(strip_chars)
    cleaned = re.sub(r'(?i)\s+\b(at|on|visit|from|link|website|official)\b\s*$', '', cleaned)
    cleaned = cleaned.strip(strip_chars)
    return cleaned

def main():
    print("Connecting to NextJobPost API...")
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }

    print("Fetching jobs list...")
    resp = requests.get(f"{API_URL}?limit=1000&status=all", headers=headers, timeout=30)
    if resp.status_code != 200:
        print(f"[ERROR] Failed to fetch jobs. API returned {resp.status_code}: {resp.text}")
        return
    
    jobs = resp.json().get("data", [])
    print(f"Total jobs found: {len(jobs)}")

    updated_count = 0
    competitors = ['freshershunt', 'freshersvoice', 'jobsarkari', 'sarkariresult', 'careerbywell', 'sarkarijob', 'freejobalert', 'indgovtjobs', 'govtjobsalert']
    
    exclude_fields = {
        "applyLink", "pdfLink", "telegram", "whatsapp", "image", 
        "sourceUrl", "sourceWebsite", "isActive", "isGovernment", 
        "createdAt", "updatedAt", "lastDate", "postedAt", "slug", 
        "views", "applications", "postedBy", "postType", "type", 
        "isFeatured", "_id", "id", "__v"
    }
    html_fields = {"jobDescription", "howToApply"}

    for job in jobs:
        job_id = job.get("_id", job.get("id"))
        title = job.get("title", "")
        safe_title = title.encode('ascii', 'ignore').decode('ascii')
        
        dirty_job = False
        is_govt = job.get("isGovernment") is True or str(job.get("isGovernment")).lower() == "true"
        
        for field, val in job.items():
            if field not in exclude_fields and isinstance(val, (str, list)):
                is_html = field in html_fields
                cleaned_val = clean_raw_text(val, is_html=is_html)
                
                # Check for empty string on required fields
                if field == "company" and not cleaned_val:
                    cleaned_val = "Government Department" if is_govt else "Top Company"
                if field == "title" and not cleaned_val:
                    cleaned_val = "Job Opportunity"
                    
                if cleaned_val != val:
                    print(f"[DIRTY] Updating field '{field}' for job: '{safe_title}' (ID: {job_id})")
                    up_resp = requests.put(f"{API_URL}/{job_id}", json={field: cleaned_val}, headers=headers, timeout=15)
                    if up_resp.status_code == 200:
                        dirty_job = True
                    else:
                        print(f"   -> [ERROR] Failed to update field '{field}': {up_resp.status_code} - {up_resp.text}")
        
        apply_link = job.get("applyLink")
        if apply_link:
            apply_link_str = str(apply_link).lower()
            if any(comp in apply_link_str for comp in competitors):
                print(f"[DIRTY] Updating field 'applyLink' for job: '{safe_title}' (ID: {job_id})")
                up_resp = requests.put(f"{API_URL}/{job_id}", json={"applyLink": "https://nextjobpost.in/"}, headers=headers, timeout=15)
                if up_resp.status_code == 200:
                    dirty_job = True
                else:
                    print(f"   -> [ERROR] Failed to update applyLink: {up_resp.status_code} - {up_resp.text}")
                
        pdf_link = job.get("pdfLink")
        if pdf_link:
            pdf_link_str = str(pdf_link).lower()
            if any(comp in pdf_link_str for comp in competitors):
                print(f"[DIRTY] Updating field 'pdfLink' for job: '{safe_title}' (ID: {job_id})")
                up_resp = requests.put(f"{API_URL}/{job_id}", json={"pdfLink": ""}, headers=headers, timeout=15)
                if up_resp.status_code == 200:
                    dirty_job = True
                else:
                    print(f"   -> [ERROR] Failed to update pdfLink: {up_resp.status_code} - {up_resp.text}")
                
        if dirty_job:
            updated_count += 1

    print("\n=============================================")
    print(f"[SUCCESS] DB Sanitization Complete! Cleaned/Updated {updated_count} postings.")
    print("=============================================")

if __name__ == "__main__":
    main()
