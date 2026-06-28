with open("bot1.py", "r") as f:
    content = f.read()

import re

# Remove the line: client_gemini = None  # Disabled Gemini Integration if API_KEY else None
content = re.sub(r'client_gemini = genai\.Client\(api_key=API_KEY\) if API_KEY else None\n', '', content)

# Replace extract_with_ai
new_func = '''async def extract_with_ai(text):
    """Uses basic fallback extraction since AI was removed."""
    data = extract_basic(text)
    
    title_val = data.get("title", "Job Opening")
    data["jobDescription"] = sanitize_text(data.get("htmlDescription", text))
    data["description"] = sanitize_text(data.get("shortSummary", title_val[:150] + "..."))
    data["aboutCompany"] = sanitize_text(data.get("aboutCompany", ""))
    data["whyJoin"] = sanitize_text(data.get("whyJoin", ""))
    data["howToApply"] = data.get("howToApply", "")
    data["finalThoughts"] = data.get("finalThoughts", "")
    data["highlightText"] = data.get("title", "Freshers Eligible")
    data["eligibility"] = data.get("eligibility", "")
    data["vacancies"] = data.get("vacancies", "")
    data["isGovernment"] = data.get("isGovernment") is True or str(data.get("isGovernment")).lower() == "true"
    
    from slugify import slugify
    import hashlib
    base_slug = slugify(data.get("title", "Job Opening"))
    unique_id = hashlib.md5(text.encode()).hexdigest()[:5]
    data["slug"] = f"{base_slug}-{unique_id}"
    
    # 🚀 Inject the predefined WhatsApp & Telegram Social links!
    data["whatsapp"] = "https://chat.whatsapp.com/LVpuUJluTpUEdIc4daAemQ"
    data["telegram"] = "https://t.me/nextjobpost"
    
    # 🧹 Sanitize any mobile LinkedIn URLs to ensure universal compatibility
    for key, value in data.items():
        if isinstance(value, str) and "linkedin.com" in value:
            data[key] = value.replace("linkedin.com/mwlite/", "linkedin.com/").replace("linkedin.com/m/", "linkedin.com/")
            
    return data
'''

# Find the start of extract_with_ai
match = re.search(r'async def extract_with_ai\(text\):.*?(?=\ndef is_valid_job\(job\):)', content, re.DOTALL)
if match:
    content = content[:match.start()] + new_func + content[match.end():]
else:
    print("Could not find extract_with_ai block")

with open("bot1.py", "w") as f:
    f.write(content)
