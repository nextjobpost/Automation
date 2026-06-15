import os
import requests
import json
import re

# Set up backend API URL
API_URL = "https://nextjobpost-backend.onrender.com/api/jobs/6a29a723f43222cbce153dad"
API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok"

def clean_raw_text(val):
    if not val:
        return val
    if isinstance(val, list):
        return [clean_raw_text(item) for item in val]
    if not isinstance(val, str):
        return val
        
    competitor_domains = [
        r'freshershunt\.(?:in|com|org)',
        r'freshersvoice\.(?:in|com|org)',
        r'jobsarkari\.(?:in|com|org)',
        r'sarkariresult\.(?:in|com|org)',
        r'careerbywell\.(?:in|com|org)',
        r'sarkarijob\.(?:in|com|org)',
        r'freejobalert\.(?:in|com|org)',
        r'indgovtjobs\.(?:in|com|org)',
        r'govtjobsalert\.(?:in|com|org)'
    ]
    cleaned = val
    for comp in competitor_domains:
        cleaned = re.sub(r'(?i)https?://\S*' + comp + r'\S*', '', cleaned)
        cleaned = re.sub(r'(?i)\b\S*' + comp + r'\S*', '', cleaned)

    cleaned = re.sub(r'(?i)https?://\.in/\S*', '', cleaned)
    cleaned = re.sub(r'(?i)https?://\.in\b', '', cleaned)

    phrases_to_remove = [
        r'(?i)\bvisit\s+the\s+full\s+details\s+and\s+application\s+page\b',
        r'(?i)\bfollow\s+the\s+instructions\s+provided\s+on\s+the\s+page\s+to\s+complete\s+your\s+application\b',
        r'(?i)\bfor\s+a\s+detailed\s+guide\s+on\s+the\s+application\s+process\s*,\s*refer\s+to\s+the\s+youtube\s+video\b',
        r'(?i)\bclick\s+here\s+to\s+apply\b',
        r'(?i)\bofficial\s+website\b',
        r'(?i)\bofficial\s+notification\b',
        r'(?i)\bapply\s+online\b'
    ]
    for phrase in phrases_to_remove:
        cleaned = re.sub(phrase, '', cleaned)

    competitor_names = ['freshershunt', 'freshersvoice', 'jobsarkari', 'sarkariresult', 'careerbywell', 'sarkarijob', 'freejobalert', 'indgovtjobs', 'govtjobsalert']
    for name in competitor_names:
        cleaned = re.sub(r'(?i)\b' + name + r'\b', '', cleaned)

    cleaned = re.sub(r'\b\d+\.\s*(?:\.|:|-|\s)*\b', '', cleaned)

    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'\.\s*\.+', '.', cleaned)
    cleaned = re.sub(r'-\s*-+', '-', cleaned)
    cleaned = re.sub(r':\s*:+', ':', cleaned)
    cleaned = re.sub(r'\.\s*\.', '.', cleaned)
    cleaned = re.sub(r':\s*\.', ':', cleaned)

    cleaned = cleaned.strip(" -|:_!@#%^&*()[]{}<>.,/\\\"'")
    cleaned = re.sub(r'(?i)\s+\b(at|on|visit|from|link|website|official)\b\s*$', '', cleaned)
    cleaned = cleaned.strip(" -|:_!@#%^&*()[]{}<>.,/\\\"'")
    return cleaned

def main():
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }

    resp = requests.get(API_URL, headers=headers)
    job = resp.json().get("data", {})
    
    exclude_fields = {"applyLink", "pdfLink", "telegram", "whatsapp", "image", "sourceUrl", "sourceWebsite", "isActive", "isGovernment", "createdAt", "updatedAt", "_id", "id", "__v"}
    
    update_payload = {}
    for field, val in job.items():
        if field not in exclude_fields and isinstance(val, (str, list)):
            cleaned_val = clean_raw_text(val)
            if cleaned_val != val:
                update_payload[field] = cleaned_val
                
    print("Payload to send:")
    print(json.dumps(update_payload, indent=2))
    
    up_resp = requests.put(API_URL, json=update_payload, headers=headers)
    print("Response Status:", up_resp.status_code)
    print("Response Text:", up_resp.text)

if __name__ == "__main__":
    main()
