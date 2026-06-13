import json
import os
import hashlib
import database

def migrate():
    print("Starting migration from JSON files to SQLite database...")
    
    # 1. Migrate active jobs
    queue_file = "job_queue.json"
    if os.path.exists(queue_file):
        try:
            with open(queue_file, "r", encoding="utf-8") as f:
                queue = json.load(f)
            
            migrated_jobs = 0
            for item in queue:
                job_data = item.get("job", {})
                job_hash = item.get("hash", "")
                image_path = item.get("image_path", "")
                is_govt = job_data.get("isGovernment", False)
                
                if database.add_job_to_queue(job_data, job_hash, image_path, is_govt):
                    migrated_jobs += 1
            print(f"✅ Migrated {migrated_jobs} active jobs into SQLite job_queue.")
        except Exception as e:
            print(f"❌ Error migrating job_queue.json: {e}")
    else:
        print("ℹ️ No job_queue.json found to migrate.")

    # 2. Migrate seen jobs from bot posted_cache
    cache_file = "posted_cache.json"
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
            for h in cache:
                database.mark_job_seen(h)
            print(f"✅ Migrated {len(cache)} seen jobs from {cache_file}.")
        except Exception as e:
            print(f"❌ Error migrating {cache_file}: {e}")
            
    # 3. Migrate Govt scraped urls
    scraped_govt = "scraped_urls.json"
    if os.path.exists(scraped_govt):
        try:
            with open(scraped_govt, "r", encoding="utf-8") as f:
                cache = json.load(f)
            for url in cache.keys():
                # Govt scraper uses full MD5 of the URL
                url_hash = hashlib.md5(url.encode()).hexdigest()
                database.mark_job_seen(url_hash)
            print(f"✅ Migrated {len(cache)} seen URLs from {scraped_govt}.")
        except Exception as e:
            print(f"❌ Error migrating {scraped_govt}: {e}")

    # 4. Migrate IT scraped urls
    scraped_it = "scraped_it_urls.json"
    if os.path.exists(scraped_it):
        try:
            with open(scraped_it, "r", encoding="utf-8") as f:
                cache = json.load(f)
            for url in cache.keys():
                # IT scraper uses 10-char MD5 of the URL
                url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
                database.mark_job_seen(url_hash)
            print(f"✅ Migrated {len(cache)} seen URLs from {scraped_it}.")
        except Exception as e:
            print(f"❌ Error migrating {scraped_it}: {e}")
            
    # 5. Failed jobs
    failed_file = "failed_jobs.json"
    if os.path.exists(failed_file):
        try:
            with open(failed_file, "r", encoding="utf-8") as f:
                # Assuming failed_jobs is ndjson (one JSON object per line)
                failed_count = 0
                for line in f:
                    if line.strip():
                        item = json.loads(line)
                        job_data = item.get("job", {})
                        job_hash = item.get("hash", "")
                        image_path = item.get("image_path", "")
                        is_govt = job_data.get("isGovernment", False)
                        # We just add it to failed_jobs DB (it expects a row dictionary)
                        row = {
                            "job_hash": job_hash,
                            "job_data": json.dumps(job_data),
                            "image_path": image_path,
                            "is_government": is_govt,
                            "retries": 3
                        }
                        database.add_to_failed_queue(row, "Migrated from failed_jobs.json")
                        failed_count += 1
            print(f"✅ Migrated {failed_count} failed jobs into SQLite.")
        except Exception as e:
            print(f"❌ Error migrating failed_jobs.json: {e}")

    print("\n🎉 Migration Complete! You can now safely delete the .json cache/queue files.")

if __name__ == "__main__":
    migrate()
