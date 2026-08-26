import os
import fitz  # PyMuPDF
import docx
import base64
import json
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from langchain_core.documents import Document

def get_api_key():
    """Retrieve Google Gemini API Key from environment."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    return key.strip('"').strip("'").strip()

def process_documents(file_paths):
    """
    Extracts text and embedded links from PDFs, Word docs, and text files.
    Splits text into chunks for vector indexing.
    """
    documents = []
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=400)
    
    for file_path in file_paths:
        try:
            ext = os.path.splitext(file_path)[1].lower()
            
            if ext == '.pdf':
                doc = fitz.open(file_path)
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    text = page.get_text("text")
                    
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
                                    page_content=chunk, 
                                    metadata={"source": file_path, "filename": os.path.basename(file_path), "page": page_num}
                                )
                            )
                doc.close()
                
            elif ext == '.docx':
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
            print(f"Error processing {file_path}: {e}")
            raise ValueError(f"Failed to process {os.path.basename(file_path)}: {str(e)}")
            
    if not documents:
        raise ValueError("The uploaded document is either empty or consists solely of non-extractable scanned images. Please upload a digital PDF, DOCX, or TXT file.")
        
    return documents

def get_embeddings_model():
    """Initializes Google GenAI Embeddings with automatic fallback."""
    api_key = get_api_key()
    if not api_key:
        raise ValueError("Google Gemini API Key is missing. Please configure GEMINI_API_KEY in environment variables.")
    try:
        return GoogleGenerativeAIEmbeddings(model="models/text-embedding-004", google_api_key=api_key)
    except Exception:
        return GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=api_key)

def get_vector_store(documents):
    """Embeds documents into an in-memory & persisted FAISS vector index."""
    embeddings = get_embeddings_model()
    vector_store = FAISS.from_documents(documents, embedding=embeddings)
    vector_store.save_local("./faiss_index")
    return vector_store

def get_conversational_chain():
    """Builds the Gemini 1.5 Flash multimodal conversational reasoning chain."""
    prompt_template = """
    You are Aneevarp DocAI, an enterprise document intelligence assistant developed by Aneevarp Solutions, powered by Google Gemini and Google Cloud Run.

    Answer the user's question accurately, concisely, and insightfully based ONLY on the provided document context.

    Follow these strict formatting standards:
    - Use <b>bold text</b> for key facts, numbers, dates, and conclusions.
    - Use clean bullet points (<ul><li>...</li></ul>) or numbered steps (<ol><li>...</li></ol>) to break down information.
    - Use HTML tables or <code>code snippets</code> if tabular or technical data is present.
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

    model = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash", 
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

def process_user_query(user_question):
    """Performs semantic vector search in FAISS and invokes Gemini conversational reasoning."""
    if not os.path.exists("./faiss_index"):
        return {
            "answer": "<b>No active document found.</b> Please upload a PDF, Word, or Text document first.",
            "source_image": None,
            "page": None,
            "file_type": None,
            "filename": None
        }
        
    embeddings = get_embeddings_model()
    db = FAISS.load_local("./faiss_index", embeddings, allow_dangerous_deserialization=True)
    
    # Retrieve top 4 relevant chunks
    docs = db.similarity_search(user_question, k=4)
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
    
    # Parse JSON output safely
    response_text = response.content.strip()
    if response_text.startswith("```json"):
        response_text = response_text[7:]
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
    
    # Visual Grounding extraction
    best_doc = docs[0]
    source_file = best_doc.metadata.get("source", "")
    filename = best_doc.metadata.get("filename", os.path.basename(source_file) if source_file else "")
    page_num = best_doc.metadata.get("page")
    
    source_image = None
    file_ext = os.path.splitext(source_file)[1].lower() if source_file else ""
    
    if file_ext == '.pdf' and source_file and page_num is not None and page_num >= 0:
        source_image = get_base64_image(source_file, page_num, exact_quote)
    
    return {
        "answer": answer,
        "source_image": source_image,
        "page": page_num,
        "file_type": file_ext,
        "filename": filename,
        "exact_quote": exact_quote
    }
