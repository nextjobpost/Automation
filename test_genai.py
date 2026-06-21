from google import genai
client = genai.Client(api_key="test")
print(client.aio)
print(client.aio.models)
