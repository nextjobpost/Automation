import json

with open("queue_job_11.json", "r", encoding="utf-8") as f:
    queued = json.load(f)

with open("cabinet_job_direct.json", "r", encoding="utf-8") as f:
    live = json.load(f)

print("Queued Job Keys:", sorted(queued.keys()))
print("Live Job Keys:", sorted(live.keys()))

print("\n--- Key Field Comparisons ---")
for field in ["title", "company", "location", "type", "experience", "eligibility", "vacancies", "salary", "applyLink", "pdfLink", "isGovernment", "postType", "sourceWebsite", "sourceUrl"]:
    q_val = queued.get(field)
    l_val = live.get(field)
    print(f"[{field}]:")
    print(f"  Queued: {repr(q_val)}")
    print(f"  Live:   {repr(l_val)}")
    if q_val != l_val:
        print("  --> DIFFERENT!")
