import requests
import json

API_URL = "https://nextjobpost-backend.onrender.com/api/jobs"
API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"

headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

test_job = {
    "title": "Indian Navy Technical Officer Recruitment 2026",
    "slug": "indian-navy-technical-officer-recruitment-2026-xyz",
    "company": "Indian Navy",
    "location": "Test Location",
    "type": "Full-Time",
    "experience": "0-1 Years",
    "eligibility": "Test Eligibility",
    "vacancies": "1 Post",
    "salary": "Test Salary",
    "applyLink": "https://nextjobpost.in/",
    "jobDescription": "<div><p>This is a test with a competitor link: <a href=\"https://govtjobsalert.in/other-govt-jobs/\">central government jobs</a> available right now.</p></div>",
    "description": "Short summary description.",
    "isGovernment": True,
    "postType": "Job Post"
}

resp = requests.post(API_URL, json=test_job, headers=headers)
print("POST Status Code:", resp.status_code)
if resp.status_code in [200, 201]:
    data = resp.json().get("data", {})
    job_id = data.get("_id") or data.get("id")
    print(f"POST Success! Created Job ID: {job_id}")
    print("Response JSON keys:", list(data.keys()))
    print("Response jobDescription:", data.get("jobDescription"))
    
    # Let's also do a GET to verify it remains in the database
    get_resp = requests.get(f"{API_URL}/{job_id}", headers=headers)
    print("\nGET Status Code:", get_resp.status_code)
    if get_resp.status_code == 200:
        get_data = get_resp.json().get("data", {})
        print("GET Response jobDescription:", get_data.get("jobDescription"))
        
        # Clean up by deleting the test job
        del_resp = requests.delete(f"{API_URL}/{job_id}", headers=headers)
        print("DELETE Status Code:", del_resp.status_code)
else:
    print(f"POST Failed! Response: {resp.text}")
