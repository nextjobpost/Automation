import requests
import json

API_URL = "https://nextjobpost-backend.onrender.com/api/jobs/6a2ff07ddbaf8a2f4f19ea8d"
API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"

headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

resp = requests.get(API_URL, headers=headers)
print("Status Code:", resp.status_code)
if resp.status_code == 200:
    data = resp.json().get("data", {})
    print("Keys in specific job GET:", list(data.keys()))
    print("Has jobDescription:", "jobDescription" in data)
    print("jobDescription length:", len(data.get("jobDescription", "")))
    print("jobDescription excerpt:", data.get("jobDescription", "")[:500])
    
    # Save the actual full JSON
    with open("cabinet_job_direct.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
else:
    print("Failed to fetch job:", resp.text)
