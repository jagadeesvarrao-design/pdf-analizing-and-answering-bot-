const fileInput = document.getElementById('pdfUpload');
const fileNameDisplay = document.getElementById('file-name');
const processBtn = document.getElementById('processBtn');
const statusIndicator = document.getElementById('status-indicator');
const statusText = document.getElementById('status-text');

const uploadSection = document.getElementById('upload-section');
const successSection = document.getElementById('success-section');
const uploadAnotherBtn = document.getElementById('uploadAnotherBtn');

const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const chatWindow = document.getElementById('chatWindow');

// API Base URL (FastAPI)
const API_URL = 'http://127.0.0.1:8002';

// Handle File Selection
fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
        if (fileInput.files.length === 1) {
            fileNameDisplay.textContent = fileInput.files[0].name;
        } else {
            fileNameDisplay.textContent = `${fileInput.files.length} files selected`;
        }
    } else {
        fileNameDisplay.textContent = 'No files selected';
    }
});

// Helper to add messages to chat
function addMessage(content, type) {
    const msgDiv = document.createElement('div');
    msgDiv.classList.add('message', type);
    
    const contentDiv = document.createElement('div');
    contentDiv.classList.add('msg-content');
    contentDiv.innerHTML = content; // Using innerHTML to support basic formatting if needed
    
    msgDiv.appendChild(contentDiv);
    chatWindow.appendChild(msgDiv);
    
    // Scroll to bottom
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

// Process Document Event
processBtn.addEventListener('click', async () => {
    
    if (fileInput.files.length === 0) {
        alert('Please select at least one document to upload.');
        return;
    }

    // UI Updates
    processBtn.disabled = true;
    statusIndicator.classList.remove('status-hidden');
    statusText.textContent = "Extracting & Embedding PDF...";

    const formData = new FormData();
    for (let i = 0; i < fileInput.files.length; i++) {
        formData.append('files', fileInput.files[i]);
    }

    try {
        const response = await fetch(`${API_URL}/api/upload`, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            statusIndicator.classList.add('status-hidden');
            
            // Swap UI sections
            uploadSection.classList.add('hidden');
            successSection.classList.remove('hidden');
            
            // Enable Chat
            chatInput.disabled = false;
            sendBtn.disabled = false;
            addMessage("Documents processed! I am ready to answer your questions.", "system-msg");
        } else {
            throw new Error(data.detail || "Upload failed");
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
        statusIndicator.classList.add('status-hidden');
        processBtn.disabled = false;
    }
});

// Upload Another Event
uploadAnotherBtn.addEventListener('click', () => {
    successSection.classList.add('hidden');
    uploadSection.classList.remove('hidden');
    fileInput.value = '';
    fileNameDisplay.textContent = 'No files selected';
    processBtn.disabled = false;
    chatInput.disabled = true;
    sendBtn.disabled = true;
    chatWindow.innerHTML = '<div class="message system-msg"><div class="msg-content">Welcome! Upload a PDF, Word, or Text document on the left and ask me questions about it.</div></div>';
});

// Chat Send Event
async function sendMessage() {
    const question = chatInput.value.trim();
    
    if (!question) return;

    // Append User Message
    addMessage(question, "user-msg");
    chatInput.value = '';
    
    // Disable inputs while waiting
    chatInput.disabled = true;
    sendBtn.disabled = true;
    
    // Add temporary loading message for AI
    const loadingId = 'loading-' + Date.now();
    const loadingMsg = document.createElement('div');
    loadingMsg.classList.add('message', 'ai-msg');
    loadingMsg.id = loadingId;
    loadingMsg.innerHTML = '<div class="msg-content"><i class="fa-solid fa-circle-notch fa-spin"></i> Thinking...</div>';
    chatWindow.appendChild(loadingMsg);
    chatWindow.scrollTop = chatWindow.scrollHeight;

    try {
        const response = await fetch(`${API_URL}/api/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                question: question
            })
        });

        const data = await response.json();
        
        // Remove loading message
        document.getElementById(loadingId).remove();

        if (response.ok) {
            // Check if we have an image or if it's a non-pdf file
            let contentHTML = data.answer;
            if (data.file_type === '.pdf' && data.source_image) {
                contentHTML += `
                    <div class="source-image-wrapper">
                        <div class="source-label"><i class="fa-solid fa-file-pdf"></i> Source: Page ${data.page + 1}</div>
                        <img src="data:image/png;base64,${data.source_image}" alt="PDF Source Page">
                    </div>
                `;
            } else if (data.file_type === '.docx' || data.file_type === '.txt') {
                contentHTML += `
                    <div class="source-image-wrapper" style="opacity: 0.7; text-align: center; border-top: 1px dashed rgba(255,255,255,0.2); padding-top: 10px;">
                        <div class="source-label" style="justify-content: center; font-style: italic;">
                            <i class="fa-solid fa-circle-info"></i> Image preview is only available for PDFs.
                        </div>
                    </div>
                `;
            }
            addMessage(contentHTML, "ai-msg");
        } else {
            throw new Error(data.detail || "Failed to get answer");
        }
    } catch (error) {
        document.getElementById(loadingId).remove();
        addMessage(`Error: ${error.message}`, "system-msg");
    } finally {
        chatInput.disabled = false;
        sendBtn.disabled = false;
        chatInput.focus();
    }
}

sendBtn.addEventListener('click', sendMessage);

chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        sendMessage();
    }
});
