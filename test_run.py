import asyncio
import database
import json

from bot1 import process_and_post_job

async def main():
    q = database.get_queue()
    if not q:
        print("Queue is empty")
        return
    job_data = q[0]
    print(f"Testing with job: {job_data['job']['title']}")
    await process_and_post_job(job_data)

asyncio.run(main())
