import asyncio
import database
import json

from bot1 import process_and_post_job

async def main():
    q = database.get_jobs_batch(5)
    if not q:
        print("Queue is empty")
        return
    for job_data in q:
        print("================================")
        print(f"Testing with job: {job_data['job']['title']}")
        await process_and_post_job(job_data)
        print("================================\n")

asyncio.run(main())
