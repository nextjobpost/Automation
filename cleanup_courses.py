import os
import requests
import json
import unicodedata

# Set up local API URL
API_URL = os.getenv("API_URL", "http://localhost:4000/api/jobs")
ADMIN_URL = os.getenv("ADMIN_URL", "http://localhost:4000/api/admin/login")

def get_auth_token():
    payload = {"username": "admin", "password": "admin123"}
    try:
        response = requests.post(ADMIN_URL, json=payload, timeout=10)
        if response.status_code == 200:
            return response.json().get("token")
    except Exception as e:
        print(f"Login failed: {e}")
    return None

def normalize_text(text):
    if not text:
        return ""
    return unicodedata.normalize('NFKD', str(text)).lower()

def main():
    print("Connecting to local NextJobPost API...")
    token = get_auth_token()
    if not token:
        print("[ERROR] Failed to login to Admin API.")
        return
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Fetch all jobs (both active and inactive/draft) from database
    print("Fetching jobs list...")
    # Fetch a large limit to catch all listings
    resp = requests.get(f"{API_URL}?limit=500&status=all", headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"[ERROR] Failed to fetch jobs. API returned {resp.status_code}: {resp.text}")
        return
    
    jobs = resp.json().get("data", [])
    print(f"Total jobs found on site: {len(jobs)}")

    forbidden_keywords = ["certification", "course", "bootcamp", "training", "academy", "certified"]
    deleted_count = 0

    for job in jobs:
        title = job.get("title", "")
        job_id = job.get("_id", job.get("id"))
        
        # Normalize mathematical bold characters
        normalized_title = normalize_text(title)
        
        # Check for spam keywords
        has_spam = any(kw in normalized_title for kw in forbidden_keywords)
        
        if has_spam:
            # Safely encode the title to ascii or skip printing the title directly to avoid errors, or clean it
            safe_title = title.encode('ascii', 'ignore').decode('ascii')
            print(f"[DELETE] Deleting spam: '{safe_title}' (ID: {job_id})")
            del_resp = requests.delete(f"{API_URL}/{job_id}", headers=headers, timeout=15)
            if del_resp.status_code == 200:
                print(f"   -> Success!")
                deleted_count += 1
            else:
                print(f"   -> [ERROR] Failed to delete: {del_resp.status_code} - {del_resp.text}")

    print("\n=============================================")
    print(f"[SUCCESS] Cleanup Complete! Deleted {deleted_count} spam postings.")
    print("=============================================")

if __name__ == "__main__":
    main()
