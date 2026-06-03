import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)
api_key = os.environ.get("GOOGLE_API_KEY", "").strip('"').strip("'").strip()

url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={api_key}"
data = {
    "model": "models/gemini-embedding-2",
    "content": {
        "parts": [{"text": "Hello world"}]
    }
}
response = requests.post(url, json=data)
print("Status Code:", response.status_code)
print("Response:", response.text)
