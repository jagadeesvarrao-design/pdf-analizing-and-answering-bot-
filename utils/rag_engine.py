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
    key = os.environ.get("GOOGLE_API_KEY", "")
    return key.strip('"').strip("'").strip()

def process_documents(file_paths):
    documents = []
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=5000, chunk_overlap=500)
    
    for file_path in file_paths:
        try:
            ext = os.path.splitext(file_path)[1].lower()
            text_content = ""
            
            if ext == '.pdf':
                doc = fitz.open(file_path)
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    text = page.get_text()
                    
                    # Extract embedded hyperlinks so the AI can see them
                    links = page.get_links()
                    extracted_links = [link.get("uri") for link in links if link.get("kind") == fitz.LINK_URI and link.get("uri")]
                    if extracted_links:
                        text += "\n\n[Links found on this page]: " + ", ".join(extracted_links)
                        
                    if text.strip():
                        chunks = text_splitter.split_text(text)
                        for chunk in chunks:
                            documents.append(
                                Document(
                                    page_content=chunk, 
                                    metadata={"source": file_path, "page": page_num}
                                )
                            )
            elif ext == '.docx':
                doc = docx.Document(file_path)
                text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
                if text.strip():
                    chunks = text_splitter.split_text(text)
                    for chunk in chunks:
                        documents.append(
                            Document(
                                page_content=chunk,
                                metadata={"source": file_path, "page": -1}
                            )
                        )
            elif ext == '.txt':
                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read()
                if text.strip():
                    chunks = text_splitter.split_text(text)
                    for chunk in chunks:
                        documents.append(
                            Document(
                                page_content=chunk,
                                metadata={"source": file_path, "page": -1}
                            )
                        )
                        
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            raise ValueError(f"Failed to process {os.path.basename(file_path)}: {str(e)}")
            
    if not documents:
        raise ValueError("The uploaded document is either empty or consists entirely of scanned images. No text could be extracted.")
        
    return documents

def get_vector_store(documents):
    api_key = get_api_key()
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2", google_api_key=api_key)
    
    # Store vectors in local FAISS index
    vector_store = FAISS.from_documents(documents, embedding=embeddings)
    vector_store.save_local("./faiss_index")
    return vector_store

def get_conversational_chain():
    prompt_template = """
    You are a friendly, conversational AI assistant analyzing a document for a user. 
    Answer the user's question naturally and conversationally, as if you are chatting with a friend.
    Be helpful, detailed, and structure your response beautifully using HTML tags (like <b>, <br>, <ul>, <li>, etc.) so it renders nicely in a web browser.
    
    If the context contains any links or URLs relevant to the user's question, make sure to explicitly provide them using HTML <a> tags with target="_blank".
    If the answer is not in the provided context, politely and conversationally let the user know you couldn't find it in the uploaded document. Do not hallucinate outside information.
    
    IMPORTANT: You must output your ENTIRE response in valid JSON format. Do not include markdown code blocks (like ```json), just raw JSON.
    The JSON must have exactly two keys:
    "answer": Your conversational HTML-formatted response.
    "exact_quote": The exact, verbatim sentence or short paragraph from the context that you used to answer the question. If you didn't find the answer, leave this empty.
    
    Context:
    {context}
    
    User's Question: 
    {question}
    
    JSON Output:
    """
    
    api_key = get_api_key()
    model = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", 
        temperature=0.3, 
        google_api_key=api_key,
        model_kwargs={"response_mime_type": "application/json"}
    )
    prompt = PromptTemplate(template=prompt_template, input_variables=["context", "question"])
    chain = prompt | model
    
    return chain

def get_base64_image(pdf_path, page_num, quote=""):
    try:
        doc = fitz.open(pdf_path)
        page = doc.load_page(page_num)
        
        clip_rect = None
        if quote:
            words = quote.split()
            search_phrase = " ".join(words[:10]) if len(words) > 10 else quote
            rects = page.search_for(search_phrase)
            
            if not rects and len(words) > 5:
                # Try the end of the quote if the beginning had weird formatting
                search_phrase = " ".join(words[-10:])
                rects = page.search_for(search_phrase)
                
            if rects:
                x0 = min([r.x0 for r in rects])
                y0 = min([r.y0 for r in rects])
                x1 = max([r.x1 for r in rects])
                y1 = max([r.y1 for r in rects])
                
                # Expand bounding box to show surrounding context (e.g., the whole paragraph)
                padding_y = 60
                padding_x = 40
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
        return b64_img
    except Exception as e:
        print(f"Error rendering image: {e}")
        return None

def process_user_query(user_question):
    api_key = get_api_key()
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2", google_api_key=api_key)
    
    # Load the existing database
    if not os.path.exists("./faiss_index"):
        return {"answer": "Please upload and process a PDF first.", "source_image": None, "page": None}
        
    db = FAISS.load_local("./faiss_index", embeddings, allow_dangerous_deserialization=True)
    
    # Retrieve relevant chunks
    docs = db.similarity_search(user_question, k=4)
    if not docs:
        return {"answer": "No relevant context found.", "source_image": None, "page": None}
        
    context_text = "\n\n".join([doc.page_content for doc in docs])
    
    chain = get_conversational_chain()
    
    # Generate answer
    response = chain.invoke({"context": context_text, "question": user_question})
    
    # Parse JSON response safely
    response_text = response.content.strip()
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
    response_text = response_text.strip()
    
    try:
        data = json.loads(response_text)
        answer = data.get("answer", "Could not parse answer.")
        exact_quote = data.get("exact_quote", "")
    except Exception as e:
        print("JSON parse error:", e)
        answer = response_text
        exact_quote = ""
    
    # Extract metadata from the highest ranked document
    best_doc = docs[0]
    source_file = best_doc.metadata.get("source", "")
    page_num = best_doc.metadata.get("page")
    
    source_image = None
    file_ext = os.path.splitext(source_file)[1].lower() if source_file else ""
    
    if file_ext == '.pdf' and source_file and page_num is not None and page_num >= 0:
        source_image = get_base64_image(source_file, page_num, exact_quote)
    
    return {
        "answer": answer,
        "source_image": source_image,
        "page": page_num,
        "file_type": file_ext
    }
