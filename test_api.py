from dotenv import load_dotenv
import os
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI

load_dotenv(override=True)
api_key = os.environ.get("GOOGLE_API_KEY", "").strip('"').strip("'").strip()
print(f"Loaded API Key: {api_key[:10]}...{api_key[-5:]} (Length: {len(api_key)})")

try:
    print("Testing embeddings...")
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2", google_api_key=api_key)
    res = embeddings.embed_query("hello world")
    print(f"Embedding success, length: {len(res)}")
    
    print("Testing chat model...")
    model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3, google_api_key=api_key)
    res2 = model.invoke("say hi")
    print(f"Chat success: {res2.content}")
except Exception as e:
    print(f"ERROR: {e}")
