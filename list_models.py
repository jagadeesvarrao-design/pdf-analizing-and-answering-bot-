from dotenv import load_dotenv
import os
import requests

load_dotenv(override=True)
api_key = os.environ.get("GOOGLE_API_KEY", "").strip('"').strip("'").strip()

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
res = requests.get(url)
data = res.json()

if "models" in data:
    embed_models = [m["name"] for m in data["models"] if "embedContent" in m.get("supportedGenerationMethods", [])]
    print(f"Supported Embedding Models: {embed_models}")
else:
    print(data)
