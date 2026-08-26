// Aneevarp DocAI - Main Client Controller
// Built for Google Cloud Gen AI Ideathon

import { 
    loginWithGoogle, 
    logoutUser, 
    onUserAuthStateChanged, 
    saveSessionToFirestore, 
    saveMessageToFirestore, 
    fetchUserSessions, 
    fetchSessionMessages, 
    deleteSessionFromFirestore 
} from './firebase-config.js';

// DOM Elements
const googleSignInBtn = document.getElementById('googleSignInBtn');
const userProfile = document.getElementById('userProfile');
const profileTrigger = document.getElementById('profileTrigger');
const profileDropdown = document.getElementById('profileDropdown');
const userAvatar = document.getElementById('userAvatar');
const dropdownUserName = document.getElementById('dropdownUserName');
const dropdownUserEmail = document.getElementById('dropdownUserEmail');
const logoutBtn = document.getElementById('logoutBtn');

// Sidebar Tabs
const tabUpload = document.getElementById('tabUpload');
const tabHistory = document.getElementById('tabHistory');
const uploadTabContent = document.getElementById('uploadTabContent');
const historyTabContent = document.getElementById('historyTabContent');
const historyList = document.getElementById('historyList');
const historyCount = document.getElementById('historyCount');

// Upload & Document DOM
const fileInput = document.getElementById('pdfUpload');
const dropZone = document.getElementById('dropZone');
const fileNameDisplay = document.getElementById('file-name');
const fileNameContainer = document.getElementById('file-name-container');
const processBtn = document.getElementById('processBtn');
const statusIndicator = document.getElementById('status-indicator');
const statusText = document.getElementById('status-text');
const uploadSection = document.getElementById('upload-section');
const successSection = document.getElementById('success-section');
const successDocName = document.getElementById('successDocName');
const uploadAnotherBtn = document.getElementById('uploadAnotherBtn');

// Chat DOM
const activeDocTitle = document.getElementById('activeDocTitle');
const newChatBtn = document.getElementById('newChatBtn');
const chatWindow = document.getElementById('chatWindow');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const suggestedPrompts = document.getElementById('suggestedPrompts');

// State Management
let currentUser = null;
let currentSessionId = null;
let activeDocumentName = "Aneevarp DocAI Workspace";
let isProcessing = false;

// Determine API Base URL (Relative if hosted unified on Cloud Run, or fallback)
const API_BASE = (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" || window.location.hostname.endsWith(".run.app")) 
    ? "" 
    : (window.__API_URL__ || "https://pdf-analizing-and-answering-bot-1.onrender.com");

// ==========================================================================
// 1. AUTHENTICATION (FIREBASE GOOGLE SIGN-IN)
// ==========================================================================
onUserAuthStateChanged((user) => {
    currentUser = user;
    if (user) {
        googleSignInBtn.classList.add('hidden');
        userProfile.classList.remove('hidden');
        userAvatar.src = user.photoURL || "https://lh3.googleusercontent.com/a/default-user=s96-c";
        dropdownUserName.textContent = user.displayName || "Google Cloud User";
        dropdownUserEmail.textContent = user.email || "user@googlecloud.apac";
        loadHistoryList();
    } else {
        googleSignInBtn.classList.remove('hidden');
        userProfile.classList.add('hidden');
        profileDropdown.classList.add('hidden');
    }
});

googleSignInBtn.addEventListener('click', async () => {
    try {
        await loginWithGoogle();
    } catch (e) {
        alert("Google Sign-In failed: " + e.message);
    }
});

profileTrigger.addEventListener('click', (e) => {
    e.stopPropagation();
    profileDropdown.classList.toggle('hidden');
});

document.addEventListener('click', () => {
    if (!profileDropdown.classList.contains('hidden')) {
        profileDropdown.classList.add('hidden');
    }
});

logoutBtn.addEventListener('click', async () => {
    await logoutUser();
    window.location.reload();
});

// ==========================================================================
// 2. SIDEBAR TABS & HISTORY
// ==========================================================================
tabUpload.addEventListener('click', () => {
    tabUpload.classList.add('active');
    tabHistory.classList.remove('active');
    uploadTabContent.classList.remove('hidden');
    historyTabContent.classList.add('hidden');
});

tabHistory.addEventListener('click', () => {
    tabHistory.classList.add('active');
    tabUpload.classList.remove('active');
    historyTabContent.classList.remove('hidden');
    uploadTabContent.classList.add('hidden');
    loadHistoryList();
});

async function loadHistoryList() {
    if (!currentUser) return;
    const sessions = await fetchUserSessions(currentUser.uid);
    historyCount.textContent = sessions.length;

    if (sessions.length === 0) {
        historyList.innerHTML = `
            <div class="history-empty">
                <i class="fa-solid fa-box-archive"></i>
                <p>No past sessions found. Upload a document to start a session.</p>
            </div>
        `;
        return;
    }

    historyList.innerHTML = '';
    sessions.forEach(sess => {
        const item = document.createElement('div');
        item.classList.add('history-item');
        if (sess.id === currentSessionId) item.classList.add('active');

        const formattedDate = sess.updatedAt ? new Date(sess.updatedAt.seconds ? sess.updatedAt.seconds * 1000 : sess.updatedAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Recent';

        item.innerHTML = `
            <div class="history-info">
                <div class="history-title"><i class="fa-solid fa-file-pdf"></i> ${escapeHTML(sess.fileName || "Document Session")}</div>
                <div class="history-meta"><i class="fa-regular fa-clock"></i> ${formattedDate}</div>
            </div>
            <button class="history-delete-btn" title="Delete Session">
                <i class="fa-solid fa-trash-can"></i>
            </button>
        `;

        item.querySelector('.history-info').addEventListener('click', () => {
            restoreSession(sess);
        });

        item.querySelector('.history-delete-btn').addEventListener('click', async (e) => {
            e.stopPropagation();
            if (confirm(`Delete history for "${sess.fileName}"?`)) {
                await deleteSessionFromFirestore(currentUser.uid, sess.id);
                if (currentSessionId === sess.id) {
                    resetChatUI();
                }
                loadHistoryList();
            }
        });

        historyList.appendChild(item);
    });
}

async function restoreSession(sess) {
    currentSessionId = sess.id;
    activeDocumentName = sess.fileName || "Active Document";
    activeDocTitle.textContent = activeDocumentName;

    // Switch to upload tab success state
    uploadSection.classList.add('hidden');
    successSection.classList.remove('hidden');
    successDocName.textContent = `Loaded session for: ${sess.fileName}`;
    tabUpload.click();

    // Enable chat
    chatInput.disabled = false;
    sendBtn.disabled = false;
    chatWindow.innerHTML = '';

    // Fetch and render messages
    const msgs = await fetchSessionMessages(currentUser.uid, sess.id);
    if (msgs.length === 0) {
        addSystemMessage(`Loaded session for <strong>${escapeHTML(sess.fileName)}</strong>. You can continue asking questions.`);
    } else {
        msgs.forEach(m => {
            if (m.role === 'user') {
                renderUserMessage(m.content);
            } else {
                renderAiMessage(m.content, m.sourceImage, m.page, m.fileType);
            }
        });
    }

    if (window.innerWidth <= 768) {
        setMobileView('chat');
    }
}

// ==========================================================================
// 3. FILE UPLOAD & DRAG AND DROP
// ==========================================================================
fileInput.addEventListener('change', handleFileSelected);

['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    }, false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
    }, false);
});

dropZone.addEventListener('drop', (e) => {
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        fileInput.files = e.dataTransfer.files;
        handleFileSelected();
    }
});

function handleFileSelected() {
    if (fileInput.files.length > 0) {
        fileNameContainer.classList.remove('hidden');
        if (fileInput.files.length === 1) {
            fileNameDisplay.textContent = fileInput.files[0].name;
        } else {
            fileNameDisplay.textContent = `${fileInput.files.length} files selected`;
        }
    } else {
        fileNameContainer.classList.add('hidden');
        fileNameDisplay.textContent = 'No file selected';
    }
}

processBtn.addEventListener('click', async () => {
    if (fileInput.files.length === 0) {
        alert('Please select at least one PDF, DOCX, or TXT document.');
        return;
    }

    if (!currentUser) {
        // Trigger Google Sign In
        try {
            await loginWithGoogle();
        } catch (e) {
            alert("Please sign in with Google to index and save documents.");
            return;
        }
    }

    isProcessing = true;
    processBtn.disabled = true;
    statusIndicator.classList.remove('status-hidden');
    statusText.textContent = "Extracting & Vectorizing with Gemini...";

    const formData = new FormData();
    for (let i = 0; i < fileInput.files.length; i++) {
        formData.append('files', fileInput.files[i]);
    }

    const firstFileName = fileInput.files[0].name;

    try {
        const response = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            statusIndicator.classList.add('status-hidden');
            uploadSection.classList.add('hidden');
            successSection.classList.remove('hidden');
            successDocName.textContent = `Indexed: ${firstFileName}`;

            // Initialize Session
            currentSessionId = `session_${Date.now()}`;
            activeDocumentName = firstFileName;
            activeDocTitle.textContent = activeDocumentName;

            // Save to Firestore
            if (currentUser) {
                await saveSessionToFirestore(currentUser.uid, currentSessionId, {
                    fileName: firstFileName,
                    fileCount: fileInput.files.length,
                    createdAt: new Date().toISOString()
                });
                loadHistoryList();
            }

            // Enable Chat & Reset Window
            chatInput.disabled = false;
            sendBtn.disabled = false;
            chatWindow.innerHTML = '';
            addSystemMessage(`<strong>${escapeHTML(firstFileName)}</strong> indexed successfully! You can ask questions or click a starter prompt below.`);
            
            // Show starter prompts
            if (suggestedPrompts) {
                chatWindow.appendChild(suggestedPrompts);
            }

            if (window.innerWidth <= 768) {
                setMobileView('chat');
            }
        } else {
            throw new Error(data.detail || "Document extraction failed");
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
        statusIndicator.classList.add('status-hidden');
        processBtn.disabled = false;
    } finally {
        isProcessing = false;
    }
});

uploadAnotherBtn.addEventListener('click', () => {
    resetUploadUI();
});

function resetUploadUI() {
    successSection.classList.add('hidden');
    uploadSection.classList.remove('hidden');
    fileInput.value = '';
    fileNameContainer.classList.add('hidden');
    fileNameDisplay.textContent = 'No file selected';
    processBtn.disabled = false;
}

function resetChatUI() {
    currentSessionId = null;
    activeDocumentName = "Aneevarp DocAI Workspace";
    activeDocTitle.textContent = activeDocumentName;
    chatInput.disabled = true;
    sendBtn.disabled = true;
    chatWindow.innerHTML = `
        <div class="message system-msg">
            <div class="msg-content">
                <div class="system-welcome-title"><i class="fa-solid fa-hand-wave"></i> Welcome to Aneevarp DocAI</div>
                <p>Upload a document on the left to start a new reasoning session.</p>
            </div>
        </div>
    `;
    resetUploadUI();
}

newChatBtn.addEventListener('click', () => {
    if (confirm("Start a new conversation?")) {
        resetChatUI();
    }
});

// ==========================================================================
// 4. CHAT EXECUTION & PROMPT CHIPS
// ==========================================================================
document.addEventListener('click', (e) => {
    const chip = e.target.closest('.prompt-chip');
    if (chip && !chatInput.disabled) {
        const promptText = chip.getAttribute('data-prompt');
        if (promptText) {
            chatInput.value = promptText;
            sendMessage();
        }
    }
});

async function sendMessage() {
    const question = chatInput.value.trim();
    if (!question || isProcessing) return;

    // Remove starter chips if present
    if (suggestedPrompts && suggestedPrompts.parentElement === chatWindow) {
        suggestedPrompts.remove();
    }

    // Render User Message
    renderUserMessage(question);
    chatInput.value = '';

    // Save to Firestore
    if (currentUser && currentSessionId) {
        await saveMessageToFirestore(currentUser.uid, currentSessionId, {
            role: 'user',
            content: question
        });
    }

    // Disable inputs & add loading spinner
    chatInput.disabled = true;
    sendBtn.disabled = true;

    const loadingId = 'loading-' + Date.now();
    const loadingMsg = document.createElement('div');
    loadingMsg.classList.add('message', 'ai-msg');
    loadingMsg.id = loadingId;
    loadingMsg.innerHTML = '<div class="msg-content"><i class="fa-solid fa-sparkles fa-spin"></i> Reasoning with Gemini 1.5 Flash...</div>';
    chatWindow.appendChild(loadingMsg);
    chatWindow.scrollTop = chatWindow.scrollHeight;

    try {
        const response = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: question })
        });

        const data = await response.json();
        document.getElementById(loadingId)?.remove();

        if (response.ok) {
            renderAiMessage(data.answer, data.source_image, data.page, data.file_type);

            // Save AI Response to Firestore
            if (currentUser && currentSessionId) {
                await saveMessageToFirestore(currentUser.uid, currentSessionId, {
                    role: 'assistant',
                    content: data.answer,
                    sourceImage: data.source_image || null,
                    page: data.page !== undefined ? data.page : null,
                    fileType: data.file_type || null
                });
            }
        } else {
            throw new Error(data.detail || "Failed to generate answer");
        }
    } catch (error) {
        document.getElementById(loadingId)?.remove();
        addSystemMessage(`Error: ${error.message}`);
    } finally {
        chatInput.disabled = false;
        sendBtn.disabled = false;
        chatInput.focus();
    }
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});

// Helper Renderers
function renderUserMessage(text) {
    const msg = document.createElement('div');
    msg.classList.add('message', 'user-msg');
    msg.innerHTML = `<div class="msg-content">${escapeHTML(text)}</div>`;
    chatWindow.appendChild(msg);
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

function renderAiMessage(htmlContent, sourceImage, pageNum, fileType) {
    const msg = document.createElement('div');
    msg.classList.add('message', 'ai-msg');
    
    let fullHtml = `<div class="msg-content">${htmlContent}`;
    if (fileType === '.pdf' && sourceImage && pageNum !== null && pageNum !== undefined) {
        fullHtml += `
            <div class="source-image-wrapper">
                <div class="source-label"><i class="fa-solid fa-file-pdf"></i> Visual Grounding: Page ${pageNum + 1}</div>
                <img src="data:image/png;base64,${sourceImage}" alt="PDF Grounding Page Snippet" title="Click to view full image">
            </div>
        `;
    }
    fullHtml += `</div>`;

    msg.innerHTML = fullHtml;
    chatWindow.appendChild(msg);
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

function addSystemMessage(html) {
    const msg = document.createElement('div');
    msg.classList.add('message', 'system-msg');
    msg.innerHTML = `<div class="msg-content">${html}</div>`;
    chatWindow.appendChild(msg);
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

function escapeHTML(str) {
    return (str || '').replace(/[&<>'"]/g, 
        tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
}

// ==========================================================================
// THEME ENGINE (LIGHT & DARK MODE TOGGLE)
// ==========================================================================
const themeToggleBtn = document.getElementById('themeToggleBtn');
const themeIcon = document.getElementById('themeIcon');
const themeLabel = document.getElementById('themeLabel');

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('aneevarp_theme', theme);
    if (theme === 'dark') {
        if (themeIcon) {
            themeIcon.className = 'fa-solid fa-sun';
            themeIcon.style.color = '#F59E0B';
        }
        if (themeLabel) themeLabel.textContent = 'Light Mode';
    } else {
        if (themeIcon) {
            themeIcon.className = 'fa-solid fa-moon';
            themeIcon.style.color = '#476550';
        }
        if (themeLabel) themeLabel.textContent = 'Dark Mode';
    }
}

// Initialize theme (default: light to match landing page)
const savedTheme = localStorage.getItem('aneevarp_theme') || 'light';
applyTheme(savedTheme);

if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
    });
}

// ==========================================================================
// MOBILE WORKSPACE VIEW SWITCHER (< 768px devices)
// ==========================================================================
const viewBtnDocs = document.getElementById('viewBtnDocs');
const viewBtnChat = document.getElementById('viewBtnChat');

function setMobileView(view) {
    if (view === 'chat') {
        document.body.classList.add('mobile-view-chat');
        document.body.classList.remove('mobile-view-docs');
        if (viewBtnChat) viewBtnChat.classList.add('active');
        if (viewBtnDocs) viewBtnDocs.classList.remove('active');
    } else {
        document.body.classList.add('mobile-view-docs');
        document.body.classList.remove('mobile-view-chat');
        if (viewBtnDocs) viewBtnDocs.classList.add('active');
        if (viewBtnChat) viewBtnChat.classList.remove('active');
    }
}

if (viewBtnDocs) {
    viewBtnDocs.addEventListener('click', () => setMobileView('docs'));
}
if (viewBtnChat) {
    viewBtnChat.addEventListener('click', () => setMobileView('chat'));
}

// Default to Document view on small screens if no active document
if (window.innerWidth <= 768) {
    setMobileView('docs');
}

