import json
import os
import time
import hashlib
import database

def inject_dummy_job():
    # 1. Create a perfectly valid test job object
    job = {
        "title": "🧪 TEST MODE - Senior Automation Engineer",
        "company": "NextJobPost Labs",
        "location": "Remote / Pan India",
        "type": "Full-Time",
        "experience": "0-2 Years",
        "education": "B.Tech / B.E. / MCA",
        "batch": "2024 / 2025",
        "salary": "₹12,00,000 - ₹15,00,000 LPA",
        "shortSummary": "This is an automated test job to verify the end-to-end processing pipeline of the NextJobPost bot.",
        "htmlDescription": "<h2>Test Job Details</h2><p>This job was injected automatically via the sandbox injector script.</p><ul><li>Testing poster generation.</li><li>Testing AI extraction mocking.</li><li>Testing API routing logic.</li></ul>",
        "responsibilities": [
            "Verify the Telegram message format.",
            "Verify the LinkedIn payload format.",
            "Verify the Website API payload format."
        ],
        "requirements": [
            "Must be running in TEST_MODE.",
            "Must correctly save outputs to /test_output/ directory."
        ],
        "skills": ["Python", "Automation", "Testing", "Telegram Bot API"],
        "applyLink": "https://nextjobpost.in/test-apply",
        "lastDate": "",
        "aboutCompany": "NextJobPost Labs is the internal testing division ensuring the job automation pipeline remains robust and flawless.",
        "whyJoin": "Because testing is crucial to prevent live environment pollution and to ensure high-quality job postings.",
        "howToApply": "This is a test job, no actual application is required.",
        "finalThoughts": "Happy Testing!",
        "eligibility": "Not Mentioned",
        "vacancies": "Not Mentioned",
        "isGovernment": False,
        "postToSocials": True
    }
    
    # 2. Hash it to give it a unique ID
    unique_string = f"TEST_JOB_{time.time()}"
    job_hash = hashlib.md5(unique_string.encode()).hexdigest()[:10]
    job["slug"] = f"test-automation-engineer-{job_hash}"
    
    # 3. Insert directly into SQLite via database
    if database.add_job_to_queue(job, job_hash, image_path="", is_government=False):
        print(f"✅ Successfully injected test job into SQLite queue: {job['title']}")
        print(f"🔄 The scheduler should pick this up within its next cycle (or instantly if starting).")
    else:
        print(f"❌ Failed to write to SQLite queue.")

if __name__ == "__main__":
    inject_dummy_job()
