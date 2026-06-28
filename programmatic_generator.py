"""
programmatic_generator.py — Programmatic SEO Page Pre-Generator
Part of the NextJobPost Automation Engine (D:/Automation)

Pre-calculates highly-optimized metadata and content blocks for all 732 landing page combinations:
  - 36 States
  - 12 Qualifications
  - 7 Categories
  - State-Qualification Combinations
  - State-Category Combinations

Saves all pre-generated content to:
  - D:/job/client/src/utils/customProgrammaticContent.json
"""

import os
import json
import asyncio
import logging
import sys
from datetime import datetime

# Enforce UTF-8 output encoding for Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace') # type: ignore
    except AttributeError:
        pass

# ── Config ────────────────────────────────────────────────────────────────────
CLIENT_OUTPUT_PATH = "d:/job/client/src/utils/customProgrammaticContent.json"
API_KEY = os.getenv("API_KEY", "")

# Lists matching the server/seo.js sitemap definition
QUALIFICATIONS = [
    '10th-pass', '12th-pass', 'graduate', 'post-graduate', 'diploma', 'iti',
    'engineering', 'medical', 'teaching', 'computer-it', 'commerce', 'law'
]
CATEGORIES = ['ssc', 'railway', 'bank', 'upsc', 'defence', 'psu', 'police']
STATES = [
    'gujarat', 'bihar', 'rajasthan', 'maharashtra', 'delhi', 'punjab',
    'haryana', 'karnataka', 'tamil-nadu', 'west-bengal', 'andhra-pradesh',
    'telangana', 'kerala', 'odisha', 'andaman-nicobar', 'arunachal-pradesh',
    'assam', 'chandigarh', 'chhattisgarh', 'dnh-dd', 'goa', 'himachal-pradesh',
    'jammu-kashmir', 'jharkhand', 'ladakh', 'lakshadweep', 'madhya-pradesh',
    'manipur', 'meghalaya', 'mizoram', 'nagaland', 'puducherry', 'sikkim',
    'tripura', 'uttar-pradesh', 'uttarakhand'
]

# Mapping names for human-readable title structures
STATE_NAMES = {
    'andaman-nicobar': 'Andaman & Nicobar', 'andhra-pradesh': 'Andhra Pradesh', 'arunachal-pradesh': 'Arunachal Pradesh',
    'assam': 'Assam', 'bihar': 'Bihar', 'chandigarh': 'Chandigarh', 'chhattisgarh': 'Chhattisgarh', 'delhi': 'Delhi',
    'dnh-dd': 'Dadra Nagar Haveli & Daman Diu', 'goa': 'Goa', 'gujarat': 'Gujarat', 'haryana': 'Haryana',
    'himachal-pradesh': 'Himachal Pradesh', 'jammu-kashmir': 'Jammu & Kashmir', 'jharkhand': 'Jharkhand',
    'karnataka': 'Karnataka', 'kerala': 'Kerala', 'ladakh': 'Ladakh', 'lakshadweep': 'Lakshadweep',
    'madhya-pradesh': 'Madhya Pradesh', 'maharashtra': 'Maharashtra', 'manipur': 'Manipur', 'meghalaya': 'Meghalaya',
    'mizoram': 'Mizoram', 'nagaland': 'Nagaland', 'odisha': 'Odisha', 'puducherry': 'Puducherry', 'punjab': 'Punjab',
    'rajasthan': 'Rajasthan', 'sikkim': 'Sikkim', 'tamil-nadu': 'Tamil Nadu', 'telangana': 'Telangana',
    'tripura': 'Tripura', 'uttar-pradesh': 'Uttar Pradesh', 'uttarakhand': 'Uttarakhand', 'west-bengal': 'West Bengal'
}

QUAL_NAMES = {
    '10th-pass': '10th Pass', '12th-pass': '12th Pass', 'graduate': 'Graduate', 'post-graduate': 'Post Graduate',
    'diploma': 'Diploma', 'iti': 'ITI', 'engineering': 'Engineering', 'medical': 'Medical', 'teaching': 'Teaching',
    'computer-it': 'Computer & IT', 'commerce': 'Commerce & Finance', 'law': 'Law & Judicial'
}

CAT_NAMES = {
    'ssc': 'SSC', 'railway': 'Railway', 'bank': 'Bank', 'upsc': 'UPSC', 'defence': 'Defence', 'psu': 'PSU', 'police': 'Police'
}

# Top 20 popular slugs to target with custom Gemini descriptions
POPULAR_SLUGS = [
    'gujarat-govt-jobs', 'bihar-govt-jobs', 'rajasthan-govt-jobs', 'uttar-pradesh-govt-jobs',
    '10th-pass-jobs', '12th-pass-jobs', 'graduate-jobs', 'engineering-jobs',
    '10th-pass-jobs-in-gujarat', '12th-pass-jobs-in-bihar', 'graduate-jobs-in-rajasthan', 'graduate-jobs-in-gujarat',
    'ssc-jobs-in-gujarat', 'railway-jobs-in-bihar', 'bank-jobs-in-uttar-pradesh', 'ssc-jobs-in-bihar',
    'ssc-jobs-in-uttar-pradesh', 'police-jobs-in-uttar-pradesh', 'police-jobs-in-bihar', 'railway-jobs-in-gujarat'
]

# ── Gemini Client Setup ───────────────────────────────────────────────────────
_client = None
if API_KEY:
    try:
        from google import genai
        _client = None  # Disabled Gemini Integration
    except Exception as e:
        logging.warning(f"[P-SEO] Gemini init failed: {e}")

# ── Dynamic Rule-Based SEO Builder ────────────────────────────────────────────
def build_rule_based_content(slug: str, type_name: str, key: str, state: str = None) -> dict:
    """Builds a rich, search-optimized dynamic structure for programmatic page combinations."""
    year = datetime.now().year
    
    state_name = STATE_NAMES.get(state, "") if state else ""
    qual_name = QUAL_NAMES.get(key, "") if type_name == "qual" else ""
    cat_name = CAT_NAMES.get(key, "") if type_name == "cat" else ""
    
    # ── Heading & Metadata ────────────────────────────────────────────────────
    if type_name == "state":
        h1 = f"Government Jobs in {state_name} {year}"
        meta_title = f"Govt Jobs in {state_name} {year} – Online Apply & Vacancies"
        meta_desc = f"Latest Government Jobs in {state_name} {year}. Apply online for state government recruitments, central jobs, results, and syllabus in {state_name}."
        intro = f"Welcome to the comprehensive directory of Government Jobs in {state_name} for the year {year}. {state_name} offers a wide spectrum of recruitment opportunities across diverse administrative, technical, and educational departments. Candidates looking for stable employment, competitive pay scales, and pension benefits can explore multiple state government departments including administrative service, revenue, health, education, and police departments."
        eligibility = f"Eligibility criteria for government jobs in {state_name} vary depending on the department and post. Generally, age limits range between 18 and 38 years, with age relaxations applicable for reserved categories (SC, ST, OBC, PwD) as per state government norms. Educational qualification ranges from 10th pass, 12th pass to graduates and postgraduates."
        salary = f"Positions in {state_name} state departments carry salary packages matching the 7th Pay Commission. Regular postings include grade pay benefits, Dearness Allowance (DA), House Rent Allowance (HRA), medical packages, and travel allowances. Salaries range from Level 1 (approx. Rs. 18,000) for entry staff to Level 12+ for senior administrative officers."
        selection = f"The selection process in {state_name} usually entails a preliminary written test, a main competitive exam, followed by a skill test or interview for senior-grade vacancies. Strict document verification (DV) and medical screening tests are mandatory stages before final deployment."
        
    elif type_name == "qual_only":
        h1 = f"{qual_name} Government & Private Jobs {year}"
        meta_title = f"{qual_name} Jobs {year} – Apply Online for Vacancies"
        meta_desc = f"Latest recruitment notifications for {qual_name} candidates. Search and apply for Central government jobs, State jobs, and Private vacancies."
        intro = f"Explore the latest government and private sector job opportunities curated specifically for {qual_name} candidates in {year}. Across India, various organizations are recruiting personnel with a background in {qual_name} to fill essential posts. Both government organizations (UPSC, SSC, Railways, PSUs) and leading corporate houses regularly post recruitment alerts matching this qualification."
        eligibility = f"Candidates holding a {qual_name} qualification from a recognized board, technical institute, or university are eligible to apply. The general age bracket is 18 to 30 years for private roles and 18 to 35+ years for government services. Age relaxation norms are strictly followed for reserved categories under government regulations."
        salary = f"Positions for {qual_name} graduates and candidates offer salary structures based on industry standards. For government sectors, pay scale aligns with the 7th Pay Commission (Level 2 to Level 7). Private sector packages range between Rs. 15,000 and Rs. 45,000 per month depending on experience and key technical skills."
        selection = f"The recruitment process features a competitive written exam (for government jobs) covering general awareness, quantitative aptitude, and English, or a technical screening interview (for private corporate roles). Final lists are declared after document verification."
        
    elif type_name == "qual_state":
        h1 = f"{qual_name} Jobs in {state_name} {year}"
        meta_title = f"{qual_name} Jobs in {state_name} {year} – Apply Online"
        meta_desc = f"Latest {qual_name} job notifications in {state_name} {year}. Find and apply online for qualifications matching {qual_name} across multiple departments."
        intro = f"Discover a wealth of career opportunities for {qual_name} candidates located in {state_name} for the year {year}. Multiple organizations, administrative sectors, and local departments are looking to recruit qualified personnel for permanent and contract-based positions in the region. This directory gathers both government and private vacancies matching a {qual_name} qualification."
        eligibility = f"Applicants must have completed their {qual_name} from a school, college, or university recognized by the government of {state_name} or Central bodies. Age limits are normally 18 to 40 years, with official relaxations given to SC, ST, OBC, and women candidates."
        salary = f"Salaries range depending on the role and sector. In state departments, salaries follow the {state_name} civil services grade pay, offering attractive DA, HRA, and pension options. Average starting packages for {qual_name} posts range from Rs. 20,000 to Rs. 50,000 monthly."
        selection = f"Selection usually relies on a written merit examination, physical standard check (where applicable), and subsequent document verification. Interviews are reserved for group A/B level technical posts."
        
    else:  # cat_state
        h1 = f"{cat_name} Jobs in {state_name} {year}"
        meta_title = f"{cat_name} Jobs in {state_name} {year} – Notifications & Exam Updates"
        meta_desc = f"Latest {cat_name} recruitment notifications, exams, admit cards, and results in {state_name} {year}. Check eligibility and apply now."
        intro = f"Get updated with all the recruitment notifications for {cat_name} jobs in {state_name} for {year}. The {cat_name} sector represents one of the most popular avenues for employment, attracting millions of job seekers. This dedicated section brings you real-time updates regarding new openings, eligibility requirements, exam calendars, and application details."
        eligibility = f"Eligibility requirements for {cat_name} postings in {state_name} demand specific minimum educational criteria (such as matriculation, intermediate, or university degree depending on the post). Candidates must be citizens of India and satisfy domicile requirements of {state_name} if applicable."
        salary = f"Sarkari salaries in the {cat_name} category follow the 7th central pay commission scale, ensuring premium job security, gratuity benefits, medical cover, and promotional pathways. Pay ranges from Rs. 21,700 to Rs. 69,100 for executive levels."
        selection = f"The screening mechanism is highly competitive, generally consisting of a computer-based test (CBT), descriptive paper, followed by a typing or physical efficiency test depending on the post. Final sorting is based on score merit lists."

    # ── 5 Custom FAQs ─────────────────────────────────────────────────────────
    target_subject = f"{qual_name or cat_name} jobs" if state else f"govt jobs in {state_name or qual_name}"
    loc_part = f" in {state_name}" if state else ""
    
    faqs = [
        {
            "q": f"How can I apply for {target_subject}{loc_part} online?",
            "a": f"You can apply by visiting NextJobPost, locating the latest job post for your desired profile, and clicking the direct 'Apply Online' link. Fill out the application form on the official department portal and submit the fees before the deadline."
        },
        {
            "q": f"What is the age limit for {target_subject}{loc_part}?",
            "a": f"The general age limit is 18 to 35 years. Domicile candidates of reserved categories (SC, ST, OBC, PwD) receive age relaxations ranging from 3 to 10 years as per government norms."
        },
        {
            "q": f"What is the educational qualification required?",
            "a": f"Educational qualifications vary from a basic 10th pass, 12th pass, ITI, or Diploma to professional University degrees in engineering, commerce, or medical disciplines depending on the vacancy."
        },
        {
            "q": f"What is the average starting salary?",
            "a": f"Starting salaries average around Rs. 18,000 to Rs. 45,000 per month depending on the post category, grade pay, and whether it falls under Central or State government salary boards."
        },
        {
            "q": f"Are there any special reservation benefits for female candidates?",
            "a": f"Yes, female candidates receive priority benefits, application fee exemptions in many notifications, and up to 33% horizontal reservation in several state departments."
        }
    ]

    return {
        "h1": h1,
        "metaTitle": meta_title,
        "metaDescription": meta_desc,
        "intro": intro,
        "eligibility": eligibility,
        "salary": salary,
        "selection": selection,
        "faqs": faqs
    }

# ── Gemini Content Generator ──────────────────────────────────────────────────
async def generate_gemini_content(slug: str, rule_fallback: dict) -> dict:
    """Uses Google Gemini to write incredibly rich and unique SEO text blocks."""
    if not _client:
        return rule_fallback

    prompt = f"""
You are an expert SEO content strategist for an Indian recruitment portal called NextJobPost.
Generate unique, high-quality, long-form SEO copy for the landing page with slug: "/{slug}".

Use the following basic details to expand on the topic:
- H1: {rule_fallback['h1']}
- Title tag suggestion: {rule_fallback['metaTitle']}
- Meta description suggestion: {rule_fallback['metaDescription']}

You must write:
1. "intro": A beautiful 120-150 word introductory overview of the job market for this profile.
2. "eligibility": A detailed 80-100 word description outlining educational qualifications and general age brackets.
3. "salary": A detailed 80-100 word section detailing the salary levels, 7th pay commission details (if govt), and other perks.
4. "selection": A detailed 80-100 word section explaining the selection steps (written test, typing/physical, medical, DV).
5. "faqs": A JSON array of exactly 5 collapsible Q&A items relevant to this search. Keep answers under 60 words.

Return ONLY a raw JSON object (no markdown formatting, no `json` code block backticks) with the keys:
"h1", "metaTitle", "metaDescription", "intro", "eligibility", "salary", "selection", "faqs".
Keep it highly professional and do not mention competitor sites.
"""
    try:
        logging.info(f"[P-SEO] 🤖 Generating AI content for popular page: /{slug}...")
        response = await _client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=dict(response_mime_type="application/json")
        )
        raw = response.text.strip()
        if raw.startswith("```json"):
            raw = raw[7:-3].strip()
        elif raw.startswith("```"):
            raw = raw[3:-3].strip()
        data = json.loads(raw)
        
        required = ["h1", "metaTitle", "metaDescription", "intro", "eligibility", "salary", "selection", "faqs"]
        if all(k in data for k in required) and len(data["faqs"]) == 5:
            logging.info(f"[P-SEO] ✅ Generated AI content successfully for /{slug}")
            return data
    except Exception as e:
        logging.warning(f"[P-SEO] AI generation failed for /{slug}: {e}. Using fallback.")
    
    return rule_fallback

# ── Main Generator Loop ───────────────────────────────────────────────────────
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logging.info("🚀 Starting Programmatic SEO Generator...")
    start_time = datetime.now()

    db = {}
    count = 0

    # 1. State Pages (36)
    for s in STATES:
        slug = f"{s}-govt-jobs"
        db[slug] = build_rule_based_content(slug, "state", s)
        count += 1

    # 2. Qualification Pages (12)
    for q in QUALIFICATIONS:
        slug = f"{q}-jobs"
        db[slug] = build_rule_based_content(slug, "qual_only", q)
        count += 1

    # 3. Qualification-State Combinations (432)
    for q in QUALIFICATIONS:
        for s in STATES:
            slug = f"{q}-jobs-in-{s}"
            db[slug] = build_rule_based_content(slug, "qual_state", q, s)
            count += 1

    # 4. Category-State Combinations (252)
    for c in CATEGORIES:
        for s in STATES:
            slug = f"{c}-jobs-in-{s}"
            db[slug] = build_rule_based_content(slug, "cat_state", c, s)
            count += 1

    logging.info(f"[P-SEO] 📋 Pre-calculated {count} landing page combinations.")

    # 5. Run AI enrichment for popular pages
    if _client:
        logging.info(f"[P-SEO] 🤖 AI key detected. Enriching top {len(POPULAR_SLUGS)} popular pages...")
        for slug in POPULAR_SLUGS:
            if slug in db:
                enriched = await generate_gemini_content(slug, db[slug])
                db[slug] = enriched
                await asyncio.sleep(1.5)
    else:
        logging.info("[P-SEO] ℹ️ No AI key found in env. Generated 100% rule-based optimized cache.")

    # 6. Save JSON
    try:
        out_dir = os.path.dirname(CLIENT_OUTPUT_PATH)
        os.makedirs(out_dir, exist_ok=True)
        with open(CLIENT_OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        logging.info(f"[P-SEO] 💾 Saved programmatic database ({len(db)} pages) to:")
        logging.info(f"        {CLIENT_OUTPUT_PATH}")
        logging.info(f"🎉 Programmatic SEO Generator completed in {elapsed:.1f}s!")
    except Exception as e:
        logging.error(f"[P-SEO] ❌ Failed to save output database: {e}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(override=True)
    asyncio.run(main())
