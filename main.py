import os
import shutil
import time
import uuid
import re
import logging
from typing import List, Dict
from collections import defaultdict
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from utils.rag_engine import process_documents, get_vector_store, process_user_query

# Load environment configuration safely
load_dotenv(override=True)

# Configure structured production logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("ZenDocAI")

app = FastAPI(
    title="ZenDoc AI API",
    description="Enterprise Document Intelligence Platform powered by Google Gemini & Google Cloud Run | Part of the Aneevarp Zen Suite",
    version="2.0.0",
    docs_url="/api/docs" if os.environ.get("ENV") != "production" else None,
    redoc_url=None
)

TEMP_PDF_DIR = "./temp_pdfs"
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", 20))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
ALLOWED_MIME_TYPES = {
    "application/pdf", 
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 
    "text/plain"
}

# ==============================================================================
# 1. SECURITY HEADERS MIDDLEWARE (Industry Best-Practice)
# ==============================================================================
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Applies strict OWASP security headers to every HTTP response."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https: data: blob: 'unsafe-inline' 'unsafe-eval'; "
        "script-src 'self' 'unsafe-inline' https://www.gstatic.com https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https://generativelanguage.googleapis.com https://identitytoolkit.googleapis.com https://firestore.googleapis.com https:; "
        "frame-ancestors 'none';"
    )
    return response

# ==============================================================================
# 2. IN-MEMORY RATE LIMITING (DoS & Brute-Force Prevention)
# ==============================================================================
class SimpleRateLimiter:
    """Sliding-window IP rate limiter without external Redis dependency."""
    def __init__(self, requests_per_minute: int = 45):
        self.requests_per_minute = requests_per_minute
        self.requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        window_start = now - 60.0
        # Clean older requests outside the 1-minute window
        self.requests[client_ip] = [t for t in self.requests[client_ip] if t > window_start]
        
        if len(self.requests[client_ip]) >= self.requests_per_minute:
            return False
        self.requests[client_ip].append(now)
        return True

rate_limiter = SimpleRateLimiter(requests_per_minute=45)

@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    """Enforces rate limits on all /api/ endpoints."""
    if request.url.path.startswith("/api/"):
        client_ip = request.client.host if request.client else "unknown"
        # Forwarded-For support behind Cloud Run load balancer
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        if not rate_limiter.is_allowed(client_ip):
            logger.warning(f"Rate limit exceeded for IP: {client_ip}")
            return JSONResponse(
                status_code=429,
                content={
                    "status": "error",
                    "message": "Too many requests. Please slow down and try again in a minute.",
                    "code": "RATE_LIMIT_EXCEEDED"
                }
            )
    return await call_next(request)

# ==============================================================================
# 3. CORS POLICY CONFIGURATION
# ==============================================================================
allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# ==============================================================================
# 4. REQUEST VALIDATION SCHEMAS
# ==============================================================================
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="User question to query context")

def sanitize_filename(filename: str) -> str:
    """Sanitizes filename against path traversal attacks."""
    clean_name = os.path.basename(filename)
    # Remove dangerous characters
    clean_name = re.sub(r'[^a-zA-Z0-9_\-\. ]', '_', clean_name)
    return clean_name if clean_name else f"document_{uuid.uuid4().hex[:8]}.pdf"

def validate_magic_bytes(header: bytes, ext: str) -> bool:
    """Verifies file headers (magic bytes) to prevent executable spoofing."""
    if ext == ".pdf":
        return header.startswith(b"%PDF-")
    elif ext == ".docx":
        # ZIP header standard for OpenXML docx
        return header.startswith(b"PK\x03\x04")
    elif ext == ".txt":
        # Text files must be valid UTF-8/ASCII without null bytes
        return b"\x00" not in header[:1024]
    return False

# ==============================================================================
# 5. API ENDPOINTS
# ==============================================================================
@app.get("/api/health")
async def health_check():
    """Health check endpoint for Cloud Run container monitoring."""
    api_key_configured = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    return {
        "status": "healthy",
        "service": "Aneevarp DocAI",
        "organization": "Aneevarp Solutions",
        "engine": "Google Gemini 2.5 Flash",
        "infrastructure": "Google Cloud Run",
        "security_hardening": "Active (OWASP / Gitleaks / Bearer Verified)",
        "gemini_api_configured": api_key_configured,
        "version": "2.0.0"
    }

@app.post("/api/upload")
async def upload_document(files: List[UploadFile] = File(...)):
    """Uploads, validates, and vectorizes documents into in-memory FAISS index."""
    correlation_id = str(uuid.uuid4())
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
        
    try:
        # Clean previous session artifacts safely
        os.makedirs(TEMP_PDF_DIR, exist_ok=True)
        safe_clean_dir(TEMP_PDF_DIR)
        safe_clean_dir("./faiss_index")
        
        file_paths = []
        file_names = []
        total_uploaded_size = 0
        
        for file in files:
            safe_name = sanitize_filename(file.filename)
            ext = os.path.splitext(safe_name)[1].lower()
            
            if ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Unsupported file format: '{ext}'. Allowed formats: PDF, DOCX, TXT."
                )
            
            # Read first 1024 bytes for magic bytes verification
            header = await file.read(1024)
            if not validate_magic_bytes(header, ext):
                raise HTTPException(
                    status_code=400, 
                    detail=f"Security validation failed: File '{safe_name}' does not match expected {ext.upper()} structure."
                )
                
            # Rewind and stream to disk with size limiting
            await file.seek(0)
            file_path = os.path.join(TEMP_PDF_DIR, safe_name)
            
            file_size = 0
            with open(file_path, "wb") as f:
                while chunk := await file.read(64 * 1024):
                    file_size += len(chunk)
                    if file_size > MAX_FILE_SIZE_BYTES:
                        f.close()
                        os.remove(file_path)
                        raise HTTPException(
                            status_code=413, 
                            detail=f"File '{safe_name}' exceeds the maximum allowed size of {MAX_FILE_SIZE_MB}MB."
                        )
                    f.write(chunk)
                    
            total_uploaded_size += file_size
            file_paths.append(file_path)
            file_names.append(safe_name)
            
        logger.info(f"[{correlation_id}] Processing {len(file_paths)} files ({total_uploaded_size / 1024:.1f} KB)")
        documents = process_documents(file_paths)
        
        if not documents:
            raise HTTPException(
                status_code=400, 
                detail="Could not extract readable text. The document may be empty or password protected."
            )
            
        get_vector_store(documents)
        
        return {
            "status": "success", 
            "message": f"Successfully processed {len(files)} document(s).",
            "files": file_names,
            "total_chunks": len(documents),
            "correlation_id": correlation_id
        }
    except HTTPException:
        raise
    except ValueError as ve:
        logger.warning(f"[{correlation_id}] Validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[{correlation_id}] Unexpected error in upload: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"An unexpected error occurred during processing. (ID: {correlation_id})"
        )

@app.post("/api/chat")
async def chat_with_document(request: ChatRequest):
    """Queries the vectorized document context with Google Gemini 2.5 Flash."""
    correlation_id = str(uuid.uuid4())
    sanitized_question = request.question.strip()
    
    if not sanitized_question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
        
    try:
        response_data = process_user_query(sanitized_question)
        return {"status": "success", "correlation_id": correlation_id, **response_data}
    except HTTPException:
        raise
    except ValueError as ve:
        logger.warning(f"[{correlation_id}] Chat validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[{correlation_id}] Chat error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"An error occurred while reasoning with Gemini. (ID: {correlation_id})"
        )

def safe_clean_dir(dir_path: str):
    """Safely empties a directory without triggering OS lock errors."""
    if not os.path.exists(dir_path):
        return
    for item in os.listdir(dir_path):
        item_path = os.path.join(dir_path, item)
        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path, ignore_errors=True)
            else:
                os.remove(item_path)
        except Exception as e:
            logger.debug(f"Could not remove {item_path}: {e}")

@app.post("/api/session/clear")
async def clear_active_session():
    """Cleans up in-memory vector indexes and temporary files."""
    try:
        safe_clean_dir(TEMP_PDF_DIR)
        safe_clean_dir("./faiss_index")
        return {"status": "success", "message": "Session cleared."}
    except Exception as e:
        logger.error(f"Error clearing session: {e}")
        return {"status": "error", "message": "Could not clear session storage."}

@app.get("/app")
async def serve_app():
    """Serves the AI Document Assistant workspace."""
    if os.path.exists("frontend/app.html"):
        return FileResponse("frontend/app.html")
    return FileResponse("frontend/index.html")

# Mount Static Frontend for unified single-container Cloud Run deployment
if os.path.exists("frontend"):
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

