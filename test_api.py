import json
import urllib.request
import sqlite3
import os

def get_job():
    conn = sqlite3.connect("automation.db")
    c = conn.cursor()
    c.execute("SELECT job_data FROM job_queue LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

job = get_job()

# Fix the missing fields for the test job
if "jobDescription" not in job:
    job["jobDescription"] = job.get("htmlDescription", "Test Description")
if "description" not in job:
    job["description"] = job.get("shortSummary", "Test Summary")

# Also let's check what 'type' is
print("Job Type:", job.get("type"))

API_TOKEN = os.getenv("API_TOKEN")

OLD_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4ifQ.ts-o1us7bsOOJunK2dL4HNmz1ONh3tywCLj0D079k4M"
NEW_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"
if not API_TOKEN or API_TOKEN == OLD_TOKEN:
    API_TOKEN = NEW_TOKEN

req = urllib.request.Request("https://nextjobpost-backend.onrender.com/api/jobs", method="POST")
req.add_header("Content-Type", "application/json")
req.add_header("Authorization", f"Bearer {API_TOKEN}")

job_payload = dict(job)
job_payload.pop("image", None)

try:
    resp = urllib.request.urlopen(req, data=json.dumps(job_payload).encode())
    print("Success:", resp.read().decode())
except urllib.error.HTTPError as e:
    print("HTTPError:", e.code, e.read().decode())
except Exception as e:
    print("Error:", e)
