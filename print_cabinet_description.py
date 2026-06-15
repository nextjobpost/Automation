import json

with open("cabinet_job_direct.json", "r", encoding="utf-8") as f:
    job = json.load(f)

# Save jobDescription to cabinet_desc.html
with open("cabinet_desc.html", "w", encoding="utf-8") as f:
    f.write(job.get("jobDescription", ""))

print("SUCCESS: HTML description saved to cabinet_desc.html")
print("Eligibility:", job.get("eligibility"))
print("Apply Link:", job.get("applyLink"))
print("PDF Link:", job.get("pdfLink"))
