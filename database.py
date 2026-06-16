import sqlite3
import json
import time
import os
import shutil

# Allow overriding the data directory via environment variable for cloud persistent storage
DATA_DIR = os.getenv("DATA_DIR", ".")
DB_PATH = os.path.join(DATA_DIR, "automation.db")
LOCAL_DB = "automation.db"

# Seed the persistent volume if it is fresh and we shipped a local DB via git
if DATA_DIR != "." and not os.path.exists(DB_PATH) and os.path.exists(LOCAL_DB):
    try:
        shutil.copy2(LOCAL_DB, DB_PATH)
        print(f"📦 Copied bundled {LOCAL_DB} to persistent volume at {DB_PATH}")
    except Exception as e:
        print(f"⚠️ Failed to copy bundled DB: {e}")

def get_connection():
    # timeout=20 ensures that if the DB is locked by another script, it waits up to 20 seconds before failing.
    return sqlite3.connect(DB_PATH, timeout=20.0)

def init_db():
    """Initializes the SQLite database and creates necessary tables."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # job_queue: Holds the pending jobs to be posted
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS job_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_hash TEXT UNIQUE,
            job_data TEXT,
            image_path TEXT,
            is_government BOOLEAN,
            timestamp REAL,
            retries INTEGER DEFAULT 0
        )
    ''')
    
    # seen_jobs: Tracks job hashes to avoid duplicate scraping
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS seen_jobs (
            job_hash TEXT PRIMARY KEY,
            timestamp REAL
        )
    ''')
    
    # failed_jobs: Dead-letter queue for jobs that exhausted retries
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS failed_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_hash TEXT,
            job_data TEXT,
            error_message TEXT,
            timestamp REAL
        )
    ''')
    
    # Create an index on is_government for faster querying
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_is_govt ON job_queue(is_government)')
    
    conn.commit()
    conn.close()

def add_job_to_queue(job_dict, job_hash, image_path="", is_government=False):
    """Inserts a new job into the queue. Ignores if hash already exists in queue."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO job_queue (job_hash, job_data, image_path, is_government, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (job_hash, json.dumps(job_dict), image_path, is_government, time.time()))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"Database error adding job to queue: {e}")
        return False
    finally:
        conn.close()

def get_jobs_batch(limit_govt=1, limit_private=1):
    """Atomically retrieves and deletes up to `limit_govt` govt jobs and `limit_private` private jobs."""
    conn = get_connection()
    # Enable dict-like row access
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    jobs = []
    try:
        # Begin exclusive transaction
        cursor.execute('BEGIN EXCLUSIVE')
        
        # 1. Fetch govt jobs
        if limit_govt > 0:
            cursor.execute('''
                SELECT id, job_hash, job_data, image_path, is_government, timestamp, retries 
                FROM job_queue WHERE is_government = 1 ORDER BY timestamp ASC LIMIT ?
            ''', (limit_govt,))
            govt_rows = cursor.fetchall()
            for row in govt_rows:
                jobs.append(dict(row))
                
        # 2. Fetch private jobs
        if limit_private > 0:
            cursor.execute('''
                SELECT id, job_hash, job_data, image_path, is_government, timestamp, retries 
                FROM job_queue WHERE is_government = 0 ORDER BY timestamp ASC LIMIT ?
            ''', (limit_private,))
            private_rows = cursor.fetchall()
            for row in private_rows:
                jobs.append(dict(row))
                
        # 3. Delete fetched jobs from queue so no other process can take them
        if jobs:
            ids_to_delete = [job['id'] for job in jobs]
            placeholders = ','.join('?' for _ in ids_to_delete)
            cursor.execute(f'DELETE FROM job_queue WHERE id IN ({placeholders})', ids_to_delete)
            
        conn.commit()
        
        # Parse JSON back into dictionaries and map job_hash to hash for backwards compatibility
        for j in jobs:
            j['job'] = json.loads(j['job_data'])
            j['hash'] = j['job_hash']
            
        return jobs
    except Exception as e:
        conn.rollback()
        print(f"Database error getting jobs: {e}")
        return []
    finally:
        conn.close()

def return_job_to_queue(job_row):
    """Puts a job back in the queue (e.g. if it fails and needs retry)."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO job_queue (job_hash, job_data, image_path, is_government, timestamp, retries)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (job_row['job_hash'], job_row['job_data'], job_row['image_path'], job_row['is_government'], time.time(), job_row['retries']))
        conn.commit()
    except Exception as e:
        print(f"Database error returning job to queue: {e}")
    finally:
        conn.close()

def add_to_failed_queue(job_row, error_msg):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO failed_jobs (job_hash, job_data, error_message, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (job_row['job_hash'], job_row['job_data'], error_msg, time.time()))
        conn.commit()
    except Exception as e:
        print(f"Database error logging failed job: {e}")
    finally:
        conn.close()

def get_queue_size():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT COUNT(*) FROM job_queue')
        return cursor.fetchone()[0]
    except:
        return 0
    finally:
        conn.close()

# ---- SEEN JOBS CACHE ----

def mark_job_seen(job_hash):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO seen_jobs (job_hash, timestamp)
            VALUES (?, ?)
        ''', (job_hash, time.time()))
        conn.commit()
    except Exception as e:
        pass
    finally:
        conn.close()

def is_job_seen(job_hash):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT 1 FROM seen_jobs WHERE job_hash = ?', (job_hash,))
        return cursor.fetchone() is not None
    except:
        return False
    finally:
        conn.close()

def get_all_seen_hashes():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT job_hash FROM seen_jobs')
        return {row[0] for row in cursor.fetchall()}
    except:
        return set()
    finally:
        conn.close()

def preload_seen_jobs(hash_list):
    """Utility to quickly load a large list of hashes into the DB."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        now = time.time()
        cursor.executemany('''
            INSERT OR IGNORE INTO seen_jobs (job_hash, timestamp)
            VALUES (?, ?)
        ''', [(h, now) for h in hash_list])
        conn.commit()
    except Exception as e:
        print(f"Error preloading seen jobs: {e}")
    finally:
        conn.close()

# Initialize DB on import
init_db()
