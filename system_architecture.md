# Job Posting Automation System Architecture and Rules

## 1. Database Layer (`database.py`)
The system uses **SQLite** for relational, thread-safe, and collision-proof queue management. To handle potential concurrent access between the main bot scheduler and periodic scraping processes, database connections are configured with a `timeout=20.0` (wait up to 20 seconds for lock release before throwing exceptions).

### Schema Definition
The database (`automation.db`) consists of three primary tables and a query optimization index:

1. **`job_queue`**: Stores jobs pending processing and distribution.
   - `job_hash` (TEXT UNIQUE): MD5 identifier of source text.
   - `job_data` (TEXT): JSON serialized job details dictionary.
   - `image_path` (TEXT): Local filesystem path to downloaded/generated poster image.
   - `is_government` (BOOLEAN): Flag separating Government (1) and Private IT (0) postings.
   - `timestamp` (REAL): Epoch time of insertion.
   - `retries` (INTEGER): Retry attempt counter (capped at 3).
   - *Includes an index `idx_is_govt` on the `is_government` column to speed up scheduler queries.*

2. **`seen_jobs`**: Deduplication index preventing duplicate scraping and posting. Stores `job_hash` (source hashes, semantic hashes, and apply link hashes) and `timestamp`.

3. **`failed_jobs`**: Dead-letter queue for debugging and manual review. Stores the `job_hash`, `job_data`, `error_message`, and `timestamp`.

### Cloud Persistence Strategy
To prevent data loss when deploying containers to ephemeral cloud environments (e.g., Render, Railway):
- **Directory Override:** The database file path is dynamically configured via the `DATA_DIR` environment variable.
- **Bootstrapping:** If `DATA_DIR` points to a mounted persistent volume and no database exists there, the application copies a bundled, preloaded `automation.db` (seeded via git) into the persistent volume directory.

---

## 2. Ingestion Flow (Dual Ingress Paths)
Jobs enter the SQLite database through two distinct channels:

### Path A: Real-Time Telegram Monitoring
- The bot runs a Telethon client session that listens to a defined array of `SOURCE_CHANNELS`.
- When an incoming message arrives, the bot:
  1. Validates the post contains job indicators using the `is_job(text)` heuristic.
  2. Generates an MD5 hash of the raw text to verify it has not been processed.
  3. Uses Gemini AI to parse fields, then classifies if it belongs to a Government channel.
  4. Runs sanitization and semantic deduplication checks.
  5. Downloads any attached image to the local `pending_images/` directory.
  6. Atomically queues the job via `database.add_job_to_queue`.

### Path B: Periodic Background Scrapers
- The bot runs an async background task (`run_scraper_periodically`) that sleeps for 6 hours.
- Every 6 hours, it spawns two sub-processes using the active Python interpreter (`sys.executable`):
  - `scrape_govt_jobs.py` (scrapes government websites/portals).
  - `scrape_additional_sources.py` (scrapes secondary sources).
- These scripts run independently, parse external web portals, and write jobs directly into the persistent SQLite DB via `database.add_job_to_queue`.

---

## 3. Scheduler & Posting Orchestrator
The main scheduler loop (`scheduler_task` in `bot1.py`) runs continuously, waking up every 10 seconds to coordinate posting pacing:

### Batch Selection and Processing Cycle
1. **Post Interval Check:** The loop checks if `POST_INTERVAL` seconds (defaulting to 1800s/30m, capped at 3600s/1h) has elapsed since the last successful post.
2. **Atomic Dequeue:** 
   - The scheduler queries the database using `BEGIN EXCLUSIVE` transaction blocks.
   - It fetches up to **1 Government Job** and **1 Private IT Job** ordered by oldest timestamp.
   - The fetched rows are immediately **deleted** from the `job_queue` table so that concurrent worker threads or bot restarts cannot duplicate the posts.
3. **Pre-Posting Validation:** Dequeued jobs are put through `is_valid_job(job)`. If a job is invalid or has expired, it is logged and skipped, and the scheduler attempts to grab the next batch immediately.
4. **Execution and Posting:** The jobs are processed in parallel (`asyncio.gather`). If any job is successfully published to the website, `last_post_time` is updated, and the scheduler sleeps until the next posting interval. If all fail or are duplicates, it immediately pulls the next batch.

### Retry & Recovery Policies
If an exception occurs during the posting pipeline:
- The bot increments the job's `retries` count.
- **If retries < 3:** The job is pushed back into the queue table using `database.return_job_to_queue`.
- **If retries >= 3:** The job is moved to the `failed_jobs` dead-letter queue with the error stack trace.

---

## 4. LLM Extraction & Processing Rules
The system uses Google Gemini for extraction with an active fallback strategy (`gemini-2.5-flash-lite` -> `gemini-2.5-flash` -> `gemini-2.0-flash` -> Regex Fallback `extract_basic`).

**Extraction Rules:**
- **No Guessing:** Fields not explicitly mentioned must output `"Not Mentioned"`. It strictly prohibits guessing companies from domain names.
- **Job Type Validation:** Values must be exactly `"Full-Time"`, `"Part-Time"`, `"Internship"`, `"Contract"`, `"Remote"`, or `"Hybrid"`.
- **Competitor URL Sanitization:** Domains like `sarkariresult.com` or `freejobalert.com` are strictly forbidden in LLM outputs.
- **Sanitization Pipeline:** The system strips Placement Drive (PD) links, LinkedIn social links, and Telegram/WhatsApp group URLs. If the primary apply link is a Telegram/WhatsApp group, the job is discarded. Unicode normalization is applied to standard text for matching.

---

## 5. Multi-Channel Routing
The system distributes validated jobs based on category:

- **Website API:** All valid Private and Government jobs are POSTed as JSON to the backend `API_URL` using a JWT Admin Token. The returned `slug` is used to construct the redirect link (`https://nextjobpost.in/<slug>`).
- **Telegram Channel:** Posts all valid jobs. It uses an inverted media trick (`[\u200b](image_url)` + `invert_media=True`) to render the image banner at the top of the message.
- **LinkedIn Page:** **Private / IT jobs ONLY** (Government jobs are excluded). Constructs a rich post using UGC/Asset APIs, dynamic hashtags (`#TechJobs`, `#RemoteJobs`), and bulleted keys.
- **Smart Filter for Non-Job Updates:** If a post is an **Admit Card, Syllabus, Result, or Answer Key**, it is published to the Website API but **strictly excluded** from Telegram and LinkedIn.

---

## 6. Cloud Health Server (Keep-Alive)
To maintain active status and prevent cloud providers from spinning down or suspending the server container, the bot initializes a dummy web server on startup using `aiohttp.web`:
- It binds to the environment variable `PORT` (configured by the host platform).
- Exposes a `/` health check endpoint returning `200 OK`.
- Runs alongside the Telethon client and scheduler tasks in the same event loop.
