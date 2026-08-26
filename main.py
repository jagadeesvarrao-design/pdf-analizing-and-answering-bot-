import os
import shutil
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from utils.rag_engine import process_documents, get_vector_store, process_user_query

load_dotenv(override=True)

app = FastAPI(
    title="Aneevalp DocAI API",
    description="Enterprise Document Intelligence Platform powered by Google Gemini & Google Cloud Run",
    version="2.0.0"
)

TEMP_PDF_DIR = "./temp_pdfs"

# Enable CORS for browser clients (Vercel, Cloud Run, Localhost, Firebase)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    question: str

@app.get("/api/health")
async def health_check():
    """Health check endpoint for Cloud Run and monitoring."""
    return {
        "status": "healthy",
        "service": "Aneevalp DocAI",
        "organization": "Aneevalp Solutions",
        "engine": "Google Gemini 1.5 Flash",
        "infrastructure": "Google Cloud Run",
        "version": "2.0.0"
    }

@app.post("/api/upload")
async def upload_document(
    files: List[UploadFile] = File(...)
):
    """Uploads and vectorizes documents into in-memory FAISS index."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
        
    try:
        # Recreate the temp directory to clean up old files
        if os.path.exists(TEMP_PDF_DIR):
            shutil.rmtree(TEMP_PDF_DIR)
        os.makedirs(TEMP_PDF_DIR, exist_ok=True)
        
        # Clear the old vector index for fresh session
        if os.path.exists("./faiss_index"):
            shutil.rmtree("./faiss_index")
        
        file_paths = []
        file_names = []
        for file in files:
            file_path = os.path.join(TEMP_PDF_DIR, file.filename)
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            file_paths.append(file_path)
            file_names.append(file.filename)
            
        documents = process_documents(file_paths)
        
        if not documents:
            raise HTTPException(status_code=400, detail="Could not extract text from the documents.")
            
        get_vector_store(documents)
        
        return {
            "status": "success", 
            "message": f"Successfully processed {len(files)} document(s).",
            "files": file_names,
            "total_chunks": len(documents)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat_with_document(request: ChatRequest):
    """Queries the vectorized document context with Google Gemini."""
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
        
    try:
        response_data = process_user_query(request.question.strip())
        return {"status": "success", **response_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount Static Frontend for unified single-container Cloud Run deployment
if os.path.exists("frontend"):
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

