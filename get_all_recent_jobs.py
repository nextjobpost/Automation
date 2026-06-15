import requests
import json

API_URL = "https://nextjobpost-backend.onrender.com/api/jobs?limit=10&status=all"
API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"

headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

resp = requests.get(API_URL, headers=headers)
if resp.status_code == 200:
    jobs = resp.json().get("data", [])
    print(f"Fetched {len(jobs)} jobs:")
    for i, job in enumerate(jobs):
        title = job.get("title", "")
        job_id = job.get("_id")
        created_at = job.get("createdAt")
        has_desc = "jobDescription" in job
        desc_len = len(job.get("jobDescription", "")) if has_desc else 0
        print(f"{i+1}. '{title}' (ID: {job_id})")
        print(f"   Created at: {created_at}")
        print(f"   Has jobDescription: {has_desc} (Length: {desc_len})")
else:
    print(f"FAILED to fetch recent jobs: {resp.status_code}")
