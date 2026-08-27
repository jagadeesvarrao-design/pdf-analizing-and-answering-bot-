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
# 1. CORS POLICY CONFIGURATION (Universal Origin & Preflight Support)
# ==============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ==============================================================================
# 2. SECURITY HEADERS MIDDLEWARE (Industry Best-Practice)
# ==============================================================================
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Applies strict OWASP security headers to every HTTP response."""
    if request.method == "OPTIONS":
        return await call_next(request)
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response

# ==============================================================================
# 3. IN-MEMORY RATE LIMITING (DoS & Brute-Force Prevention)
# ==============================================================================
class SimpleRateLimiter:
    """Sliding-window IP rate limiter without external Redis dependency."""
    def __init__(self, requests_per_minute: int = 60):
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

rate_limiter = SimpleRateLimiter(requests_per_minute=60)

@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    """Enforces rate limits on all /api/ endpoints while allowing preflight OPTIONS."""
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        client_ip = request.client.host if request.client else "unknown"
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

@app.options("/{full_path:path}")
async def options_preflight_handler(full_path: str):
    """Global OPTIONS preflight fallback handler returning 200 OK."""
    return Response(status_code=200)

# ==============================================================================
# 4. SUBSCRIPTION & TIER QUOTA MANAGEMENT ENGINE
# ==============================================================================
TIER_CONFIGS = {
    "free": {
        "title": "Free Starter",
        "max_docs_per_day": 2,
        "max_pages_per_doc": 30,
        "max_file_size_mb": 10,
        "multi_doc_allowed": False,
        "max_files_per_batch": 1,
        "export_allowed": False
    },
    "rapid_pass": {
        "title": "24-Hour Rapid Pass",
        "max_docs_per_day": 9999,
        "max_pages_per_doc": 150,
        "max_file_size_mb": 25,
        "multi_doc_allowed": True,
        "max_files_per_batch": 3,
        "export_allowed": True
    },
    "zendoc_pro": {
        "title": "ZenDoc Pro",
        "max_docs_per_day": 9999,
        "max_pages_per_doc": 500,
        "max_file_size_mb": 50,
        "multi_doc_allowed": True,
        "max_files_per_batch": 5,
        "export_allowed": True
    },
    "zen_suite": {
        "title": "Zen Suite Ultimate",
        "max_docs_per_day": 9999,
        "max_pages_per_doc": 500,
        "max_file_size_mb": 50,
        "multi_doc_allowed": True,
        "max_files_per_batch": 5,
        "export_allowed": True
    },
    "enterprise": {
        "title": "Enterprise & Teams",
        "max_docs_per_day": 99999,
        "max_pages_per_doc": 2000,
        "max_file_size_mb": 100,
        "multi_doc_allowed": True,
        "max_files_per_batch": 20,
        "export_allowed": True
    }
}

class SubscriptionManager:
    """Manages user quotas, daily ingestion limits, and tier entitlements."""
    def __init__(self):
        self.user_uploads: Dict[str, List[float]] = defaultdict(list)

    def get_tier_config(self, plan_id: str) -> dict:
        return TIER_CONFIGS.get(str(plan_id).lower(), TIER_CONFIGS["free"])

    def get_user_quota(self, user_id: str, plan_id: str = "free") -> dict:
        config = self.get_tier_config(plan_id)
        now = time.time()
        window_start = now - 86400.0
        self.user_uploads[user_id] = [t for t in self.user_uploads[user_id] if t > window_start]
        used_today = len(self.user_uploads[user_id])
        max_daily = config["max_docs_per_day"]
        remaining = max(0, max_daily - used_today)

        return {
            "plan_id": plan_id,
            "plan_title": config["title"],
            "used_today": used_today,
            "max_daily": max_daily if max_daily < 9000 else "Unlimited",
            "remaining_today": remaining if max_daily < 9000 else "Unlimited",
            "max_pages_per_doc": config["max_pages_per_doc"],
            "max_file_size_mb": config["max_file_size_mb"],
            "multi_doc_allowed": config["multi_doc_allowed"],
            "export_allowed": config["export_allowed"]
        }

    def check_and_record_upload(self, user_id: str, plan_id: str, file_count: int) -> dict:
        config = self.get_tier_config(plan_id)
        now = time.time()
        window_start = now - 86400.0
        self.user_uploads[user_id] = [t for t in self.user_uploads[user_id] if t > window_start]
        
        used_today = len(self.user_uploads[user_id])
        max_daily = config["max_docs_per_day"]
        
        if max_daily < 9000 and (used_today + file_count) > max_daily:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "DAILY_QUOTA_EXCEEDED",
                    "message": f"Daily limit reached ({used_today}/{max_daily} uploads used today). Upgrade to ZenDoc Pro or get a 24h Pass for unlimited uploads.",
                    "plan": plan_id
                }
            )

        if file_count > config["max_files_per_batch"]:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "MULTI_DOC_LIMIT_EXCEEDED",
                    "message": f"Your current plan allows up to {config['max_files_per_batch']} files per upload. Upgrade to ZenDoc Pro to cross-compare up to 5 files simultaneously.",
                    "plan": plan_id
                }
            )

        for _ in range(file_count):
            self.user_uploads[user_id].append(now)

        return config

subscription_manager = SubscriptionManager()

# ==============================================================================
# 5. REQUEST VALIDATION SCHEMAS
# ==============================================================================
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="User question to query context")

class ExportReportRequest(BaseModel):
    document_name: str = Field(default="ZenDoc AI Dossier")
    messages: List[Dict] = Field(default_factory=list)

def sanitize_filename(filename: str) -> str:
    """Sanitizes filename against path traversal attacks."""
    clean_name = os.path.basename(filename)
    clean_name = re.sub(r'[^a-zA-Z0-9_\-\. ]', '_', clean_name)
    return clean_name if clean_name else f"document_{uuid.uuid4().hex[:8]}.pdf"

def validate_magic_bytes(header: bytes, ext: str) -> bool:
    """Verifies file headers (magic bytes) to prevent executable spoofing."""
    if ext == ".pdf":
        return header.startswith(b"%PDF-")
    elif ext == ".docx":
        return header.startswith(b"PK\x03\x04")
    elif ext == ".txt":
        return b"\x00" not in header[:1024]
    return False

# ==============================================================================
# 6. API ENDPOINTS
# ==============================================================================
@app.get("/api/health")
async def health_check():
    """Health check endpoint for Cloud Run container monitoring."""
    api_key_configured = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    return {
        "status": "healthy",
        "service": "ZenDoc AI",
        "organization": "Aneevarp Solutions",
        "engine": "Google Gemini 2.5 Flash",
        "infrastructure": "Google Cloud Run",
        "security_hardening": "Active (OWASP / Rate Limited / Quota Enforced)",
        "gemini_api_configured": api_key_configured,
        "version": "2.0.0"
    }

@app.get("/api/user/quota")
async def get_user_quota(request: Request):
    """Retrieves current daily quota and plan details for active user/IP."""
    user_plan = request.headers.get("X-User-Plan", "free")
    client_ip = request.client.host if request.client else "unknown"
    user_id = request.headers.get("X-User-Id", client_ip)
    
    return {
        "status": "success",
        "quota": subscription_manager.get_user_quota(user_id=user_id, plan_id=user_plan)
    }

@app.post("/api/upload")
async def upload_document(request: Request, files: List[UploadFile] = File(...)):
    """Uploads, validates, and vectorizes documents with Tier quota enforcement."""
    correlation_id = str(uuid.uuid4())
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
        
    user_plan = request.headers.get("X-User-Plan", "free")
    client_ip = request.client.host if request.client else "unknown"
    user_id = request.headers.get("X-User-Id", client_ip)

    # 1. Enforce Tier upload allowance & multi-file limits
    tier_config = subscription_manager.check_and_record_upload(user_id=user_id, plan_id=user_plan, file_count=len(files))
    max_file_size_bytes = tier_config["max_file_size_mb"] * 1024 * 1024
    max_pages = tier_config["max_pages_per_doc"]

    try:
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
                
            # Rewind and stream to disk with tier size limiting
            await file.seek(0)
            file_path = os.path.join(TEMP_PDF_DIR, safe_name)
            
            file_size = 0
            with open(file_path, "wb") as f:
                while chunk := await file.read(64 * 1024):
                    file_size += len(chunk)
                    if file_size > max_file_size_bytes:
                        f.close()
                        os.remove(file_path)
                        raise HTTPException(
                            status_code=413, 
                            detail={
                                "code": "FILE_SIZE_LIMIT_EXCEEDED",
                                "message": f"File '{safe_name}' exceeds your plan limit of {tier_config['max_file_size_mb']}MB. Upgrade to ZenDoc Pro to upload files up to 50MB.",
                                "plan": user_plan
                            }
                        )
                    f.write(chunk)
                    
            total_uploaded_size += file_size
            file_paths.append(file_path)
            file_names.append(safe_name)
            
        logger.info(f"[{correlation_id}] Processing {len(file_paths)} files for plan '{user_plan}' (Max pages: {max_pages})")
        documents = process_documents(file_paths, max_pages=max_pages)
        
        if not documents:
            raise HTTPException(
                status_code=400, 
                detail="Could not extract readable text. The document may be empty or password protected."
            )
            
        get_vector_store(documents)
        
        quota_status = subscription_manager.get_user_quota(user_id=user_id, plan_id=user_plan)
        return {
            "status": "success", 
            "message": f"Successfully processed {len(files)} document(s).",
            "files": file_names,
            "total_chunks": len(documents),
            "quota": quota_status,
            "correlation_id": correlation_id
        }
    except HTTPException:
        raise
    except ValueError as ve:
        err_str = str(ve)
        logger.warning(f"[{correlation_id}] Validation error: {err_str}")
        if "PAGE_LIMIT_EXCEEDED" in err_str:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "PAGE_LIMIT_EXCEEDED",
                    "message": err_str,
                    "plan": user_plan
                }
            )
        raise HTTPException(status_code=400, detail=err_str)
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

@app.post("/api/export/report")
async def export_executive_report(request: Request, report_req: ExportReportRequest):
    """Generates a downloadable Markdown / Executive Summary Report for Pro users."""
    user_plan = request.headers.get("X-User-Plan", "free")
    config = subscription_manager.get_tier_config(user_plan)
    
    if not config["export_allowed"]:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "FEATURE_LOCKED",
                "message": "Report Exporting is a ZenDoc Pro feature. Upgrade to export executive dossiers to PDF & Word.",
                "plan": user_plan
            }
        )

    # Format Markdown dossier
    lines = [
        f"# 📄 Executive Intelligence Dossier: {report_req.document_name}",
        f"*Generated by **ZenDoc AI** (Aneevarp Solutions) • {time.strftime('%Y-%m-%d %H:%M:%S')}*\n",
        "---",
        "## 🔍 Key Questions & Verified Insights\n"
    ]
    
    for i, msg in enumerate(report_req.messages, 1):
        if msg.get("type") == "user":
            lines.append(f"### Q{i}: {msg.get('text', '')}\n")
        elif msg.get("type") == "ai":
            lines.append(f"**Answer:**\n{msg.get('text', '')}\n")
            if msg.get("page"):
                lines.append(f"*Verified Source: Page {msg.get('page')}*\n")
            lines.append("---\n")
            
    content = "\n".join(lines)
    return JSONResponse({
        "status": "success",
        "filename": f"ZenDoc_Dossier_{sanitize_filename(report_req.document_name)}.md",
        "content": content
    })

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

