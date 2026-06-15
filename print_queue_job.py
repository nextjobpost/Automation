import sqlite3
import json

db_path = "automation.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT job_data FROM job_queue WHERE id=11;")
row = cursor.fetchone()
if row:
    job_data = json.loads(row[0])
    with open("queue_job_11.json", "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=2)
    print("SUCCESS: job_data for ID 11 saved to queue_job_11.json")
    print("Keys in queue job_data:", list(job_data.keys()))
    print("jobDescription length in queue:", len(job_data.get("jobDescription", "")))
else:
    print("ID 11 not found in job_queue")

conn.close()
