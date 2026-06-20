import os
import json
import asyncio
import aiohttp
import sys
import subprocess
from dotenv import load_dotenv

# Add the script's directory to python path so it can import bot1 and database correctly
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

# Load env variables from .env in Automation directory
load_dotenv(os.path.join(script_dir, ".env"), override=True)

import bot1
from bot1 import (
    generate_poster,
    upload_image_to_api,
    post_to_linkedin,
    build_linkedin_post,
    ensure_font_downloaded,
    PENDING_IMAGES_DIR,
    LINKEDIN_ACCESS_TOKEN,
    LINKEDIN_PERSON_URN
)

JOBS_FILE = os.path.join(script_dir, "website_jobs.json")
POSTED_FILE = os.path.join(script_dir, "linkedin_posted_slugs.json")
POST_INTERVAL_SECS = int(os.getenv("POST_INTERVAL_SECS", 1800))

def load_jobs():
    if not os.path.exists(JOBS_FILE):
        print(f"❌ {JOBS_FILE} not found!")
        return []
    with open(JOBS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception as e:
            print(f"❌ Error reading {JOBS_FILE}: {e}")
            return []

def load_posted():
    if not os.path.exists(POSTED_FILE):
        return []
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_posted(slugs):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(slugs, f, indent=2)

async def main():
    print("=====================================================")
    print("🚀 LinkedIn Staggered Website Posting Daemon started.")
    print("=====================================================")
    
    await ensure_font_downloaded()
    
    # Validate credentials
    load_dotenv(os.path.join(script_dir, ".env"), override=True)
    bot1.LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    bot1.LINKEDIN_PERSON_URN = os.getenv("LINKEDIN_PERSON_URN", "")
    
    if not bot1.LINKEDIN_ACCESS_TOKEN or not bot1.LINKEDIN_PERSON_URN:
        print("❌ Error: LinkedIn credentials missing in environment (.env).")
        sys.exit(1)
        
    print(f"LinkedIn Person URN: {bot1.LINKEDIN_PERSON_URN}")
    print(f"Stagger Interval   : {POST_INTERVAL_SECS} seconds ({POST_INTERVAL_SECS / 60:.1f} minutes)")
    
    while True:
        # Reload env variables dynamically in case token is updated in .env
        load_dotenv(os.path.join(script_dir, ".env"), override=True)
        bot1.LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
        bot1.LINKEDIN_PERSON_URN = os.getenv("LINKEDIN_PERSON_URN", "")
        
        jobs = load_jobs()
        posted = load_posted()
        
        # Filter unposted jobs
        unposted_jobs = [j for j in jobs if j.get("slug") not in posted]
        print(f"\n📊 Total active jobs on website: {len(jobs)}")
        print(f"📊 Already posted to LinkedIn : {len(posted)}")
        print(f"📊 Pending LinkedIn queue     : {len(unposted_jobs)}")
        
        if not unposted_jobs:
            print("📭 No new unposted jobs in website_jobs.json. Sleeping for 10 minutes before checking again...")
            await asyncio.sleep(600)
            continue

            
        # Get the next job to post. Since the exported list is sorted by createdAt desc,
        # the recently seeded jobs are at the top. We process from the beginning of the list
        # to ensure the seeded ones get posted first!
        next_job = unposted_jobs[0]
        slug = next_job.get("slug")
        title = next_job.get("title")
        print(f"\n👉 Next Job: '{title}' ({slug})")
        
        # 1. Validation of post text structure
        post_text = build_linkedin_post(next_job, slug)
        forbidden_terms = ["not mentioned", "not specified", "not disclosed", "confidential", "hiring company"]
        if any(term in post_text.lower() for term in forbidden_terms):
            print(f"🚫 [SKIP] Post text contains forbidden placeholder terms. Skipping permanently.")
            posted.append(slug)
            save_posted(posted)
            continue
            
        async with aiohttp.ClientSession() as session:
            # 2. Poster Image Generation and Upload if empty
            if not next_job.get("image"):
                print("🎨 No image URL found. Generating a dynamic poster...")
                image_path = os.path.join(bot1.PENDING_IMAGES_DIR, f"gen_{slug}.jpg")
                
                # Determine salary context
                salary_val = next_job.get("salary", "Best in Industry")
                post_type = str(next_job.get("postType", "")).lower()
                is_non_job = any(k in post_type for k in ["admit card", "result", "answer key", "syllabus"])
                if is_non_job:
                    salary_val = ""
                    
                try:
                    generate_poster(
                        title=next_job.get("title", "Job Opening"),
                        company=next_job.get("company", "Top Company"),
                        location=next_job.get("location", "Across India"),
                        salary=salary_val,
                        output_path=image_path
                    )
                    
                    if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
                        print("📸 Uploading generated poster to Render backend...")
                        uploaded_url = await upload_image_to_api(session, image_path)
                        if uploaded_url:
                            next_job["image"] = uploaded_url
                            print(f"✅ Image uploaded and bound: {uploaded_url}")
                            
                            # Sync back to MongoDB so the website also has the poster
                            print("🔄 Syncing image URL back to MongoDB...")
                            try:
                                script_path = os.path.abspath(os.path.join(script_dir, "../job/server/scripts/update_job_image.js"))
                                subprocess.run(["node", script_path, slug, uploaded_url], check=True)
                                print("✅ Database updated successfully.")
                            except Exception as db_err:
                                print(f"⚠️ Failed to sync image URL to MongoDB: {db_err}")
                        else:
                            print("⚠️ Image upload failed. Posting to LinkedIn without image.")
                    else:
                        print("⚠️ Poster file is empty or not generated.")
                except Exception as e:
                    print(f"❌ Failed to generate/upload poster: {e}")
                    
            # 3. Post to LinkedIn
            print("📤 Dispatching post to LinkedIn API...")
            try:
                linkedin_url = await post_to_linkedin(session, next_job, slug)
                if linkedin_url:
                    print(f"🎉 SUCCESS! Posted to LinkedIn: {linkedin_url}")
                    posted.append(slug)
                    save_posted(posted)
                else:
                    print("❌ LinkedIn posting failed. Will retry on next iteration.")
                    # Sleep short duration before retry to prevent infinite looping immediately
                    await asyncio.sleep(60)
                    continue
            except Exception as e:
                print(f"❌ Exception posting to LinkedIn: {e}")
                # Sleep short duration before retry
                await asyncio.sleep(60)
                continue
                
        # Sleep for the designated interval
        print(f"⏳ Waiting {POST_INTERVAL_SECS} seconds ({POST_INTERVAL_SECS/60:.1f} minutes) before next post...")
        await asyncio.sleep(POST_INTERVAL_SECS)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Scheduler daemon stopped manually.")
