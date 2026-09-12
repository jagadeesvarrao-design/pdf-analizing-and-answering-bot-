import os
import re
import fitz  # PyMuPDF
import base64
import json

try:
    import docx
except ImportError:
    docx = None
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    try:
        from langchain.text_splitter import RecursiveCharacterTextSplitter
    except ImportError:
        RecursiveCharacterTextSplitter = None

from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from langchain_core.documents import Document

MAX_PAGES_PER_DOC = 150

def get_api_key():
    """Retrieve Google Gemini API Key from environment."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    return key.strip('"').strip("'").strip()

def sanitize_html_output(raw_html: str) -> str:
    """
    Sanitizes AI-generated HTML against XSS payloads, DOM clobbering, and malicious schemes.
    Preserves safe formatting (<b>, <i>, <strong>, <em>, <ul>, <ol>, <li>, <table>, <tr>, <th>, <td>, <p>, <br>, <a>).
    """
    if not raw_html:
        return ""
    
    # 1. Strip dangerous tags and their contents
    dangerous_tags = ['script', 'iframe', 'object', 'embed', 'applet', 'meta', 'link', 
                      'style', 'form', 'input', 'button', 'textarea', 'select', 'svg', 
                      'math', 'base', 'xml', 'frameset', 'frame']
    cleaned = raw_html
    for tag in dangerous_tags:
        cleaned = re.sub(rf'<\s*{tag}\b[^>]*>.*?<\s*/\s*{tag}\s*>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(rf'<\s*{tag}\b[^>]*\/?\s*>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
        
    # 2. Strip all inline DOM event handlers (e.g. onload=, onclick=, onerror=)
    cleaned = re.sub(r'(?i)\bon[a-z]+\s*=\s*(?:["\'][^"\']*["\']|[^\s>]+)', '', cleaned)
    
    # 3. Strip dangerous protocol schemes (javascript:, data:, vbscript:, file:)
    cleaned = re.sub(r'(?i)(?:href|src)\s*=\s*["\']\s*(?:javascript|data|vbscript|file):[^"\']*["\']', '', cleaned)
    
    # 4. Enforce secure anchor attributes (rel="noopener noreferrer") on any remaining links
    def sanitize_anchor(match):
        attrs = match.group(1)
        href_match = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        if not href_match:
            return "<a>"
        href_url = href_match.group(1).strip()
        # Allow only http://, https:// or relative paths
        if not (href_url.startswith("http://") or href_url.startswith("https://") or href_url.startswith("/")):
            return "<a>"
        return f'<a href="{href_url}" target="_blank" rel="noopener noreferrer">'

    cleaned = re.sub(r'<a\b([^>]*)>', sanitize_anchor, cleaned, flags=re.IGNORECASE)
    return cleaned

def perform_gemini_ocr_on_page(page) -> str:
    """Performs high-accuracy multimodal OCR on scanned or canvas-rendered PDF pages."""
    try:
        api_key = get_api_key()
        if not api_key:
            return ""
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='models/gemini-3.6-flash',
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type='image/png'),
                'Extract all text, headers, sections, bullet points, links, numbers, and details from this document page verbatim. Maintain full structural accuracy.'
            ]
        )
        return response.text.strip() if response and response.text else ""
    except Exception as e:
        print(f"Gemini OCR fallback error: {e}")
        return ""

def process_documents(file_paths, max_pages: int = 150):
    """
    Extracts text and embedded links from PDFs, Word docs, and text files.
    Splits text into chunks for vector indexing with DoS/Bomb and Subscription Tier page protections.
    """
    documents = []
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=400)
    
    for file_path in file_paths:
        try:
            ext = os.path.splitext(file_path)[1].lower()
            
            if ext == '.pdf':
                doc = fitz.open(file_path)
                doc_len = len(doc)
                if doc_len > max_pages:
                    doc.close()
                    raise ValueError(
                        f"PAGE_LIMIT_EXCEEDED: File '{os.path.basename(file_path)}' contains {doc_len} pages, "
                        f"which exceeds your plan limit of {max_pages} pages. Upgrade to ZenDoc Pro to unlock up to 500 pages."
                    )
                
                total_pages = doc_len
                for page_num in range(total_pages):
                    page = doc.load_page(page_num)
                    
                    # Extract text blocks preserving tabular structure & layout
                    blocks = page.get_text("blocks")
                    page_text_blocks = [b[4].strip() for b in blocks if len(b) > 4 and b[4].strip()]
                    text = "\n\n".join(page_text_blocks) if page_text_blocks else page.get_text("text")
                    
                    # If page has no selectable text stream (scanned/canvas image PDF), trigger Gemini OCR
                    if not text or len(text.strip()) < 25:
                        print(f"Image/Scanned page detected ({os.path.basename(file_path)} p.{page_num + 1}). Performing Gemini OCR...")
                        ocr_text = perform_gemini_ocr_on_page(page)
                        if ocr_text:
                            text = ocr_text
                    
                    # Extract embedded hyperlinks so Gemini can ground links
                    links = page.get_links()
                    extracted_links = [
                        link.get("uri") for link in links 
                        if link.get("kind") == fitz.LINK_URI and link.get("uri")
                    ]
                    if extracted_links:
                        text += "\n\n[Hyperlinks in Page " + str(page_num + 1) + "]: " + ", ".join(extracted_links)
                        
                    if text and text.strip():
                        chunks = text_splitter.split_text(text)
                        for chunk in chunks:
                            documents.append(
                                Document(
                                    page_content=f"[Document: {os.path.basename(file_path)} | Page {page_num + 1}]\n{chunk}", 
                                    metadata={"source": file_path, "filename": os.path.basename(file_path), "page": page_num}
                                )
                            )
                doc.close()
                
            elif ext == '.docx':
                if not docx:
                    raise ValueError("DOCX parsing library is not installed on this host. Please upload a PDF or TXT file, or install python-docx.")
                doc = docx.Document(file_path)
                text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
                if text.strip():
                    chunks = text_splitter.split_text(text)
                    for chunk in chunks:
                        documents.append(
                            Document(
                                page_content=chunk,
                                metadata={"source": file_path, "filename": os.path.basename(file_path), "page": -1}
                            )
                        )
                        
            elif ext == '.txt':
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                if text.strip():
                    chunks = text_splitter.split_text(text)
                    for chunk in chunks:
                        documents.append(
                            Document(
                                page_content=chunk,
                                metadata={"source": file_path, "filename": os.path.basename(file_path), "page": -1}
                            )
                        )
                        
        except Exception as e:
            if "PAGE_LIMIT_EXCEEDED" in str(e):
                raise
            print(f"Error reading {file_path}: {e}")
            
    return documents

SESSION_VECTOR_STORES: Dict[str, Any] = {}

def sanitize_session_id(session_id: str) -> str:
    """Sanitizes session ID against directory traversal."""
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '', str(session_id or 'default'))
    return clean if clean else "default_session"

def get_embeddings_model():
    """Initializes Google GenAI Embeddings (gemini-embedding-001 / gemini-embedding-2)."""
    api_key = get_api_key()
    if not api_key:
        raise ValueError("Google Gemini API Key is missing. Please configure GEMINI_API_KEY in environment variables.")
    try:
        return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=api_key)
    except Exception:
        return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2", google_api_key=api_key)

def get_vector_store(documents, session_id: str = "default"):
    """Embeds documents into an isolated, per-session FAISS vector index."""
    safe_sid = sanitize_session_id(session_id)
    embeddings = get_embeddings_model()
    vector_store = FAISS.from_documents(documents, embedding=embeddings)
    SESSION_VECTOR_STORES[safe_sid] = vector_store
    
    session_faiss_dir = os.path.join("./faiss_index", safe_sid)
    try:
        os.makedirs(session_faiss_dir, exist_ok=True)
        vector_store.save_local(session_faiss_dir)
    except Exception as e:
        print(f"Warning saving local faiss index for session {safe_sid}: {e}")
    return vector_store

def clear_session_vector_store(session_id: str = "default"):
    """Safely purges in-memory and on-disk FAISS index for a session."""
    safe_sid = sanitize_session_id(session_id)
    if safe_sid in SESSION_VECTOR_STORES:
        del SESSION_VECTOR_STORES[safe_sid]
    session_faiss_dir = os.path.join("./faiss_index", safe_sid)
    if os.path.exists(session_faiss_dir):
        shutil.rmtree(session_faiss_dir, ignore_errors=True)

def get_conversational_chain():
    """Builds the Gemini 2.5 Flash multimodal conversational reasoning chain."""
    prompt_template = """
    You are ZenDoc AI, an enterprise document intelligence and reasoning engine developed by Aneevarp Solutions, powered by Google Gemini 2.5 Flash.

    Answer the user's question accurately, concisely, and insightfully based ONLY on the provided document context.

    Follow these strict formatting standards:
    - Use <b>bold text</b> for key metrics, conclusions, terms, and critical data points.
    - Use clean bullet points (<ul><li>...</li></ul>) or numbered lists (<ol><li>...</li></ol>) to break down multi-step answers.
    - Render tabular data or financial balance sheets in clean HTML tables (<table border="1">...</table>) or clean markdown.
    - If comparing multiple documents, explicitly state the source filename for each point (e.g. <b>[Document A.pdf]</b> vs <b>[Document B.pdf]</b>).
    - If links/URLs are found in the context, render them as clickable links: <a href="..." target="_blank" rel="noopener">link</a>.
    - If the context does NOT contain the answer, politely respond: "I could not find relevant information in the uploaded document. Please check the file or rephrase your question." Do NOT hallucinate.

    CRITICAL: Output your response as a valid JSON object ONLY, with no surrounding markdown code blocks (no ```json).
    JSON Structure:
    {{
      "answer": "<HTML-formatted comprehensive answer>",
      "exact_quote": "<Exact short verbatim quote from the text supporting this answer, or empty string if not found>"
    }}

    Document Context:
    {context}

    User Question:
    {question}

    JSON Output:
    """
    
    api_key = get_api_key()
    if not api_key:
        raise ValueError("Google Gemini API Key is missing. Please set GEMINI_API_KEY.")

    try:
        model = ChatGoogleGenerativeAI(
            model="gemini-3.6-flash", 
            temperature=0.2, 
            google_api_key=api_key,
            model_kwargs={"response_mime_type": "application/json"}
        )
    except Exception:
        model = ChatGoogleGenerativeAI(
            model="gemini-flash-latest", 
            temperature=0.2, 
            google_api_key=api_key,
            model_kwargs={"response_mime_type": "application/json"}
        )
    prompt = PromptTemplate(template=prompt_template, input_variables=["context", "question"])
    return prompt | model

def get_base64_image(pdf_path, page_num, quote=""):
    """Crops visual bounding-box snippet from original PDF page for visual grounding."""
    try:
        if not os.path.exists(pdf_path):
            return None
            
        doc = fitz.open(pdf_path)
        if page_num < 0 or page_num >= len(doc):
            doc.close()
            return None
            
        page = doc.load_page(page_num)
        clip_rect = None
        
        if quote and len(quote.strip()) > 3:
            words = quote.strip().split()
            search_phrase = " ".join(words[:8]) if len(words) > 8 else quote.strip()
            rects = page.search_for(search_phrase)
            
            if not rects and len(words) > 5:
                search_phrase = " ".join(words[-8:])
                rects = page.search_for(search_phrase)
                
            if rects:
                x0 = min([r.x0 for r in rects])
                y0 = min([r.y0 for r in rects])
                x1 = max([r.x1 for r in rects])
                y1 = max([r.y1 for r in rects])
                
                # Expand bounding box to capture surrounding visual context
                padding_y = 50
                padding_x = 30
                page_rect = page.rect
                
                clip_rect = fitz.Rect(
                    max(0, x0 - padding_x),
                    max(0, y0 - padding_y),
                    min(page_rect.x1, x1 + padding_x),
                    min(page_rect.y1, y1 + padding_y)
                )

        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), clip=clip_rect)
        img_bytes = pix.tobytes("png")
        b64_img = base64.b64encode(img_bytes).decode("utf-8")
        doc.close()
        return b64_img
    except Exception as e:
        print(f"Error rendering visual bounding box: {e}")
        return None

def process_user_query(user_question: str, session_id: str = "default", temp_dir_path: str = None):
    """Performs semantic vector search in isolated FAISS session index and invokes Gemini conversational reasoning."""
    safe_sid = sanitize_session_id(session_id)
    db = SESSION_VECTOR_STORES.get(safe_sid)
    session_faiss_dir = os.path.join("./faiss_index", safe_sid)
    
    # 1. Try loading from persisted per-session FAISS index with file integrity checks
    if db is None and os.path.exists(session_faiss_dir):
        faiss_file = os.path.join(session_faiss_dir, "index.faiss")
        pkl_file = os.path.join(session_faiss_dir, "index.pkl")
        if os.path.exists(faiss_file) and os.path.exists(pkl_file) and os.path.getsize(faiss_file) > 0 and os.path.getsize(pkl_file) > 0:
            try:
                embeddings = get_embeddings_model()
                db = FAISS.load_local(session_faiss_dir, embeddings, allow_dangerous_deserialization=True)
                SESSION_VECTOR_STORES[safe_sid] = db
            except Exception as e:
                print(f"Error loading session faiss_index from disk ({safe_sid}): {e}")
                db = None
            
    # 2. Self-healing auto-recovery from session temp directory
    session_temp_dir = temp_dir_path or os.path.join("./temp_pdfs", safe_sid)
    if db is None and os.path.exists(session_temp_dir):
        files = [os.path.join(session_temp_dir, f) for f in os.listdir(session_temp_dir) if os.path.isfile(os.path.join(session_temp_dir, f))]
        if files:
            try:
                print(f"Self-healing: Re-indexing {len(files)} files for session {safe_sid}...")
                docs = process_documents(files)
                if docs:
                    db = get_vector_store(docs, session_id=safe_sid)
            except Exception as e:
                print(f"Self-healing re-index error ({safe_sid}): {e}")
                db = None

    # Fallback to root temp_pdfs if needed
    if db is None and os.path.exists("./temp_pdfs"):
        root_files = [os.path.join("./temp_pdfs", f) for f in os.listdir("./temp_pdfs") if os.path.isfile(os.path.join("./temp_pdfs", f))]
        if root_files:
            try:
                docs = process_documents(root_files)
                if docs:
                    db = get_vector_store(docs, session_id=safe_sid)
            except Exception as e:
                print(f"Fallback re-index error: {e}")
                db = None
                
    if db is None:
        return {
            "answer": "<b>No active document found in session.</b> Please upload a PDF, Word, or Text document on the left to start reasoning.",
            "source_image": None,
            "page": None,
            "file_type": None,
            "filename": None
        }
    
    # Dynamic Top-K chunk retrieval: Expand for broad / analytical questions
    q_lower = user_question.lower()
    is_broad_query = any(w in q_lower for w in ["summary", "summarize", "overview", "all", "table", "financial", "compare", "difference", "metrics", "risks", "key terms", "action items", "dossier"])
    k_val = 8 if is_broad_query else 4
    
    docs = db.similarity_search(user_question, k=k_val)
    if not docs:
        return {
            "answer": "No relevant context found in the uploaded document for your query.",
            "source_image": None,
            "page": None,
            "file_type": None,
            "filename": None
        }
        
    context_text = "\n\n---\n\n".join([doc.page_content for doc in docs])
    chain = get_conversational_chain()
    
    response = chain.invoke({"context": context_text, "question": user_question})
    
    # Parse LLM response content safely (handles string and list of blocks)
    raw_content = response.content
    if isinstance(raw_content, list):
        response_text = "".join([
            block.get("text", "") if isinstance(block, dict) else getattr(block, "text", str(block))
            for block in raw_content
        ]).strip()
    else:
        response_text = str(raw_content).strip()
        
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
    response_text = response_text.strip()
    
    try:
        data = json.loads(response_text)
        answer = data.get("answer", "Could not format answer.")
        exact_quote = data.get("exact_quote", "")
    except Exception as e:
        print("JSON parse error:", e)
        answer = response_text
        exact_quote = ""
    
    # Visual Grounding extraction: Search through retrieved docs for best visual crop
    source_image = None
    best_doc = docs[0]
    source_file = best_doc.metadata.get("source", "")
    filename = best_doc.metadata.get("filename", os.path.basename(source_file) if source_file else "")
    page_num = best_doc.metadata.get("page")
    file_ext = os.path.splitext(source_file)[1].lower() if source_file else ""
    
    # If the first doc is a PDF, crop it; otherwise check if any retrieved doc is a PDF with visual proof
    for d in docs:
        s_file = d.metadata.get("source", "")
        p_num = d.metadata.get("page")
        if s_file and os.path.splitext(s_file)[1].lower() == '.pdf' and p_num is not None and p_num >= 0:
            cropped = get_base64_image(s_file, p_num, exact_quote)
            if cropped:
                source_image = cropped
                source_file = s_file
                filename = d.metadata.get("filename", os.path.basename(s_file))
                page_num = p_num
                file_ext = '.pdf'
                break
    
    return {
        "answer": sanitize_html_output(answer),
        "source_image": source_image,
        "page": page_num,
        "file_type": file_ext,
        "filename": filename,
        "exact_quote": exact_quote
    }
