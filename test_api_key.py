import os
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv(override=True)
apiKey = os.getenv("API_KEY")

async def test_key():
    print(f"Testing key: {apiKey[:6]}...{apiKey[-6:] if len(apiKey) > 10 else ''}")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={apiKey}"
    payload = {
        "contents": [{"parts": [{"text": "Hello, respond with 'API Key is working' if you see this."}]}]
    }
    headers = {"Content-Type": "application/json"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                print(f"Status Code: {resp.status}")
                text = await resp.text()
                print(f"Response: {text[:300]}")
                if resp.status == 200:
                    print("✅ Key is working perfectly and calls are authenticated!")
                else:
                    print("❌ Key is invalid or rate limited.")
        except Exception as e:
            print(f"❌ Connection error: {e}")

asyncio.run(test_key())
