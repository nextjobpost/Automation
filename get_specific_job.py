import requests
import json

API_URL = "https://nextjobpost-backend.onrender.com/api/jobs?limit=1000&status=all"
API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"

headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

resp = requests.get(API_URL, headers=headers)
if resp.status_code == 200:
    jobs = resp.json().get("data", [])
    found = False
    for job in jobs:
        title = job.get("title", "")
        slug = job.get("slug", "")
        if "Cabinet" in title or "cabinet" in slug:
            print("FOUND JOB:")
            print("ID:", job.get("_id"))
            print("Title:", title)
            print("Slug:", slug)
            with open("cabinet_job_debug.json", "w", encoding="utf-8") as f:
                json.dump(job, f, indent=2)
            print("Saved job details to cabinet_job_debug.json")
            found = True
            break
    if not found:
        print("No job matching 'Cabinet' found in the database.")
else:
    print(f"FAILED to fetch jobs: {resp.status_code}")
