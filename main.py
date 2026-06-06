from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from typing import List

import shutil
from utils.rag_engine import process_documents, get_vector_store, process_user_query
from dotenv import load_dotenv

load_dotenv(override=True)
app = FastAPI()

TEMP_PDF_DIR = "./temp_pdfs"

# Enable CORS for the frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    question: str

@app.post("/api/upload")
async def upload_document(
    files: List[UploadFile] = File(...)
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
        
    try:
        # Recreate the temp directory to clean up old files
        if os.path.exists(TEMP_PDF_DIR):
            shutil.rmtree(TEMP_PDF_DIR)
        os.makedirs(TEMP_PDF_DIR, exist_ok=True)
        
        # Clear the old database so we don't mix old vectors with new documents
        if os.path.exists("./faiss_index"):
            shutil.rmtree("./faiss_index")
        
        file_paths = []
        for file in files:
            file_path = os.path.join(TEMP_PDF_DIR, file.filename)
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            file_paths.append(file_path)
            
        documents = process_documents(file_paths)
        
        if not documents:
            raise HTTPException(status_code=400, detail="Could not extract text from the PDFs.")
            
        get_vector_store(documents)
        
        return {"status": "success", "message": "Documents processed and indexed successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat_with_document(request: ChatRequest):
    if not request.question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
        
    try:
        response_data = process_user_query(request.question)
        return {"status": "success", **response_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
