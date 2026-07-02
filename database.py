import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

# Allow overriding the data directory via environment variable for cloud persistent storage
DATA_DIR = os.getenv("DATA_DIR", ".")
DB_PATH = os.path.join(DATA_DIR, "automation.db")

# Detect environment to determine the backend base url
IS_PRODUCTION = os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER") or os.getenv("PORT") is not None
DEFAULT_JOBS_URL = "https://nextjobpost-backend.onrender.com/api/jobs" if IS_PRODUCTION else "http://localhost:4000/api/jobs"
JOBS_URL = os.getenv("API_URL", DEFAULT_JOBS_URL)

# Expose base URL for /api/queue
BASE_API_URL = JOBS_URL.rsplit("/jobs", 1)[0]
QUEUE_API_URL = f"{BASE_API_URL}/queue"

API_TOKEN = os.getenv("API_TOKEN")
OLD_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4ifQ.ts-o1us7bsOOJunK2dL4HNmz1ONh3tywCLj0D079k4M"
NEW_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"
if not API_TOKEN or API_TOKEN == OLD_TOKEN:
    API_TOKEN = NEW_TOKEN

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

def send_request(method, endpoint, **kwargs):
    """Sends HTTP request to the API, falling back to production if local fails."""
    kwargs.setdefault("timeout", 15)
    kwargs.setdefault("headers", HEADERS)
    url = f"{QUEUE_API_URL}{endpoint}"
    try:
        if method.upper() == "POST":
            return requests.post(url, **kwargs)
        else:
            return requests.get(url, **kwargs)
    except Exception as e:
        if "onrender.com" in QUEUE_API_URL:
            raise e
        # Fallback URL
        prod_queue_url = "https://nextjobpost-backend.onrender.com/api/queue"
        fallback_url = f"{prod_queue_url}{endpoint}"
        if method.upper() == "POST":
            return requests.post(fallback_url, **kwargs)
        else:
            return requests.get(fallback_url, **kwargs)

def get_connection():
    # Return None as we don't connect to SQLite for queue/seen jobs anymore.
    # Keep function signature for backward compatibility.
    return None

def init_db():
    # No-op since we initialize everything via MongoDB collections.
    pass

def add_job_to_queue(job_dict, job_hash, image_path="", is_government=False, retries=5):
    """Inserts a new job into the MongoDB queue via REST API."""
    payload = {
        "jobData": job_dict,
        "jobHash": job_hash,
        "imagePath": image_path,
        "isGovernment": bool(is_government)
    }
    try:
        resp = send_request("POST", "/add", json=payload)
        if resp.status_code == 200:
            return resp.json().get("created", False)
    except Exception as e:
        print(f"Error adding job to MongoDB queue: {e}")
    return False

def get_jobs_batch(limit=1):
    """Atomically retrieves and deletes up to `limit` jobs from MongoDB queue."""
    try:
        resp = send_request("POST", "/batch", json={"limit": limit})
        if resp.status_code == 200:
            jobs = resp.json().get("data", [])
            for j in jobs:
                j['job'] = json.loads(j['job_data'])
                j['hash'] = j['job_hash']
            return jobs
    except Exception as e:
        print(f"Error getting jobs from MongoDB queue: {e}")
    return []

def return_job_to_queue(job_row):
    """Puts a job back in the MongoDB queue (e.g. if it fails and needs retry)."""
    payload = {
        "jobHash": job_row.get("job_hash") or job_row.get("hash"),
        "jobData": job_row.get("job") or json.loads(job_row["job_data"]),
        "imagePath": job_row.get("image_path", ""),
        "isGovernment": bool(job_row.get("is_government", False)),
        "retries": job_row.get("retries", 0)
    }
    try:
        resp = send_request("POST", "/return", json=payload)
        return resp.status_code == 200
    except Exception as e:
        print(f"Error returning job to MongoDB queue: {e}")
    return False

def add_to_failed_queue(job_row, error_msg):
    payload = {
        "jobHash": job_row.get("job_hash") or job_row.get("hash"),
        "jobData": job_row.get("job") or json.loads(job_row["job_data"]),
        "errorMessage": error_msg
    }
    try:
        resp = send_request("POST", "/failed", json=payload)
        return resp.status_code == 200
    except Exception as e:
        print(f"Error adding to failed queue in MongoDB: {e}")
    return False

def get_queue_size():
    try:
        resp = send_request("GET", "/size")
        if resp.status_code == 200:
            return resp.json().get("size", 0)
    except Exception as e:
        print(f"Error getting queue size: {e}")
    return 0

def mark_job_seen(job_hash):
    try:
        send_request("POST", "/seen/mark", json={"jobHash": job_hash})
    except Exception as e:
        print(f"Error marking job seen: {e}")

def is_job_seen(job_hash):
    try:
        resp = send_request("GET", f"/seen/{job_hash}")
        if resp.status_code == 200:
            return resp.json().get("seen", False)
    except Exception as e:
        print(f"Error checking is_job_seen: {e}")
    return False

def get_all_seen_hashes():
    try:
        resp = send_request("GET", "/seen/all")
        if resp.status_code == 200:
            return set(resp.json().get("data", []))
    except Exception as e:
        print(f"Error preloading seen jobs: {e}")
    return set()

def preload_seen_jobs(hash_list):
    """Utility to quickly mark a list of hashes as seen in the DB."""
    for h in hash_list:
        mark_job_seen(h)

def count_linkedin_govt_posts_last_24h():
    """Returns the number of government jobs posted to LinkedIn in the last 24 hours."""
    try:
        resp = send_request("GET", "/linkedin-limit")
        if resp.status_code == 200:
            return resp.json().get("count", 0)
    except Exception as e:
        print(f"Error counting linkedin govt posts: {e}")
    return 0

def log_linkedin_govt_post():
    """Logs a new government job post to LinkedIn to track daily limits."""
    try:
        send_request("POST", "/linkedin-limit/log", json={})
    except Exception as e:
        print(f"Error logging linkedin govt post: {e}")

def get_queue_breakdown():
    """Returns a dictionary showing count of jobs in queue grouped by source/website."""
    try:
        resp = send_request("GET", "/breakdown")
        if resp.status_code == 200:
            return resp.json().get("data", {})
    except Exception as e:
        print(f"Error getting queue breakdown: {e}")
    return {}
