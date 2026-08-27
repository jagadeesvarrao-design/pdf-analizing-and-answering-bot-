// ZenDoc AI - Main Client Controller (Part of the Aneevarp Zen Suite)
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
let activeDocumentName = "ZenDoc AI Workspace";
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
        if (googleSignInBtn) googleSignInBtn.classList.add('hidden');
        if (userProfile) userProfile.classList.remove('hidden');
        if (userAvatar) userAvatar.src = user.photoURL || "https://lh3.googleusercontent.com/a/default-user=s96-c";
        if (dropdownUserName) dropdownUserName.textContent = user.displayName || "Google Cloud User";
        if (dropdownUserEmail) dropdownUserEmail.textContent = user.email || "user@googlecloud.apac";
        loadHistoryList();
    } else {
        if (googleSignInBtn) googleSignInBtn.classList.remove('hidden');
        if (userProfile) userProfile.classList.add('hidden');
        if (profileDropdown) profileDropdown.classList.add('hidden');
    }
});

if (googleSignInBtn) {
    googleSignInBtn.addEventListener('click', async () => {
        try {
            await loginWithGoogle();
        } catch (e) {
            alert("Google Sign-In failed: " + e.message);
        }
    });
}

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
// SUBSCRIPTION & QUOTA MANAGEMENT
// ==========================================================================
const activePlanLabel = document.getElementById('activePlanLabel');
const dropdownPlanStatus = document.getElementById('dropdownPlanStatus');
const activePlanBtn = document.getElementById('activePlanBtn');
const limitInfoText = document.getElementById('limitInfoText');
const quotaRemainingPill = document.getElementById('quotaRemainingPill');

const upgradePaywallModal = document.getElementById('upgradePaywallModal');
const closePaywallBtn = document.getElementById('closePaywallBtn');
const paywallReasonTitle = document.getElementById('paywallReasonTitle');
const paywallReasonDesc = document.getElementById('paywallReasonDesc');
const exportReportBtn = document.getElementById('exportReportBtn');

function getActivePlan() {
    try {
        const storedPlan = localStorage.getItem('zendoc_active_plan');
        if (storedPlan) {
            return JSON.parse(storedPlan);
        }
    } catch (e) {
        console.warn("Error reading stored plan:", e);
    }
    return { planId: 'free', title: 'Free Starter' };
}

function showPaywall(title, desc) {
    if (paywallReasonTitle) paywallReasonTitle.textContent = title;
    if (paywallReasonDesc) paywallReasonDesc.textContent = desc;
    if (upgradePaywallModal) upgradePaywallModal.classList.add('active');
}

if (closePaywallBtn) {
    closePaywallBtn.addEventListener('click', () => {
        if (upgradePaywallModal) upgradePaywallModal.classList.remove('active');
    });
}

if (upgradePaywallModal) {
    upgradePaywallModal.addEventListener('click', (e) => {
        if (e.target === upgradePaywallModal) upgradePaywallModal.classList.remove('active');
    });
}

// ==========================================================================
// TOAST & CUSTOM CONFIRMATION DIALOG HELPERS
// ==========================================================================
const toastBox = document.getElementById('toastBox');
const confirmActionModal = document.getElementById('confirmActionModal');
const confirmModalTitle = document.getElementById('confirmModalTitle');
const confirmModalSubtitle = document.getElementById('confirmModalSubtitle');
const confirmModalDesc = document.getElementById('confirmModalDesc');
const confirmModalIcon = document.getElementById('confirmModalIcon');
const confirmCancelBtn = document.getElementById('confirmCancelBtn');
const confirmProceedBtn = document.getElementById('confirmProceedBtn');
const closeConfirmModalBtn = document.getElementById('closeConfirmModalBtn');

let activeConfirmCallback = null;

function showToast(message, type = 'success') {
    if (!toastBox) return;
    const toast = document.createElement('div');
    toast.className = `toast-item ${type}`;
    const icon = type === 'success' ? 'fa-circle-check' : 'fa-circle-exclamation';
    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;
    toastBox.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(15px)';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function showConfirmDialog({ title, subtitle, desc, icon = 'fa-triangle-exclamation', onConfirm }) {
    if (!confirmActionModal) return;
    if (confirmModalTitle) confirmModalTitle.innerHTML = `<i class="fa-solid fa-shield-halved"></i> ${title}`;
    if (confirmModalSubtitle) confirmModalSubtitle.textContent = subtitle;
    if (confirmModalDesc) confirmModalDesc.textContent = desc;
    if (confirmModalIcon) confirmModalIcon.innerHTML = `<i class="fa-solid ${icon}"></i>`;
    activeConfirmCallback = onConfirm;
    confirmActionModal.classList.add('active');
}

if (confirmCancelBtn) {
    confirmCancelBtn.addEventListener('click', () => {
        if (confirmActionModal) confirmActionModal.classList.remove('active');
        activeConfirmCallback = null;
    });
}

if (closeConfirmModalBtn) {
    closeConfirmModalBtn.addEventListener('click', () => {
        if (confirmActionModal) confirmActionModal.classList.remove('active');
        activeConfirmCallback = null;
    });
}

if (confirmProceedBtn) {
    confirmProceedBtn.addEventListener('click', () => {
        if (confirmActionModal) confirmActionModal.classList.remove('active');
        if (typeof activeConfirmCallback === 'function') {
            activeConfirmCallback();
        }
        activeConfirmCallback = null;
    });
}

async function fetchAndRenderQuota() {
    const plan = getActivePlan();
    if (activePlanLabel) activePlanLabel.textContent = plan.title;
    if (dropdownPlanStatus) dropdownPlanStatus.textContent = `Plan: ${plan.title}`;
    
    if (plan.planId !== 'free' && activePlanBtn) {
        activePlanBtn.style.background = 'rgba(245, 158, 11, 0.2)';
        activePlanBtn.style.borderColor = '#F59E0B';
        activePlanBtn.style.color = '#F59E0B';
    }

    try {
        const headers = {
            'X-User-Plan': plan.planId,
            'X-User-Id': currentUser ? currentUser.uid : 'anon_device'
        };
        const res = await fetch(`${API_BASE}/api/user/quota`, { headers });
        if (res.ok) {
            const data = await res.json();
            const q = data.quota;
            if (quotaRemainingPill) {
                if (q.remaining_today === 'Unlimited') {
                    quotaRemainingPill.textContent = '👑 Unlimited';
                    quotaRemainingPill.style.background = 'rgba(245, 158, 11, 0.2)';
                    quotaRemainingPill.style.color = '#F59E0B';
                } else {
                    quotaRemainingPill.textContent = `${q.remaining_today}/${q.max_daily} Left`;
                }
            }
            if (limitInfoText) {
                limitInfoText.innerHTML = `<i class="fa-solid fa-file-lines"></i> Max ${q.max_pages_per_doc} Pgs • ${q.max_file_size_mb}MB`;
            }
        }
    } catch (e) {
        console.warn("Could not fetch user quota:", e);
    }
}

fetchAndRenderQuota();

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
        showToast('Please select at least one PDF, DOCX, or TXT document.', 'error');
        return;
    }

    const plan = getActivePlan();

    // Multi-document check for Free tier
    if (fileInput.files.length > 1 && plan.planId === 'free') {
        showPaywall(
            "Multi-Document RAG (ZenDoc Pro)",
            "You selected multiple files. Cross-document comparative intelligence is a ZenDoc Pro feature. Upgrade to analyze up to 5 documents simultaneously."
        );
        return;
    }

    if (!currentUser) {
        // Trigger Google Sign In
        try {
            await loginWithGoogle();
        } catch (e) {
            showToast("Please sign in with Google to index and save documents.", "error");
            return;
        }
    }

    isProcessing = true;
    processBtn.disabled = true;
    statusIndicator.classList.remove('status-hidden');
    statusText.textContent = "Extracting & Vectorizing with Gemini 2.5 Flash...";

    const formData = new FormData();
    for (let i = 0; i < fileInput.files.length; i++) {
        formData.append('files', fileInput.files[i]);
    }

    const firstFileName = fileInput.files[0].name;

    try {
        const response = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            headers: {
                'X-User-Plan': plan.planId,
                'X-User-Id': currentUser ? currentUser.uid : 'anon_device'
            },
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            statusIndicator.classList.add('status-hidden');
            uploadSection.classList.add('hidden');
            successSection.classList.remove('hidden');
            successDocName.textContent = `Indexed: ${firstFileName} ${fileInput.files.length > 1 ? `(+${fileInput.files.length - 1} more)` : ''}`;

            // Initialize Session
            currentSessionId = `session_${Date.now()}`;
            activeDocumentName = firstFileName;
            activeDocTitle.textContent = activeDocumentName;

            // Update Quota display
            fetchAndRenderQuota();

            // Save to Firestore
            if (currentUser) {
                await saveSessionToFirestore(currentUser.uid, currentSessionId, {
                    fileName: firstFileName,
                    fileCount: fileInput.files.length,
                    createdAt: new Date().toISOString()
                });
                loadHistoryList();
            }

            // Enable Chat & Render Workspace
            chatInput.disabled = false;
            sendBtn.disabled = false;
            chatInput.placeholder = `Ask any question about ${firstFileName}...`;
            renderIndexedWorkspace(firstFileName);

            if (window.innerWidth <= 768) {
                setMobileView('chat');
            }
            showToast(`Document "${firstFileName}" indexed successfully!`, "success");
        } else if (response.status === 402 || response.status === 413) {
            const errDetail = typeof data.detail === 'object' ? data.detail : { message: data.detail };
            showPaywall(
                errDetail.code ? errDetail.code.replace(/_/g, ' ') : "Plan Limit Reached",
                errDetail.message || "Your active plan limit was reached. Upgrade to continue."
            );
        } else {
            const errMessage = typeof data.detail === 'string' ? data.detail : (data.detail?.message || "Document extraction failed");
            showToast(errMessage, 'error');
        }
    } catch (error) {
        console.error("Upload error:", error);
        showToast(error.message, 'error');
    } finally {
        statusIndicator.classList.add('status-hidden');
        processBtn.disabled = false;
        isProcessing = false;
    }
});

// ==========================================================================
// 4. EXECUTIVE DOSSIER EXPORT (Pro Feature)
// ==========================================================================
if (exportReportBtn) {
    exportReportBtn.addEventListener('click', async () => {
        const plan = getActivePlan();
        if (plan.planId === 'free') {
            showPaywall(
                "Executive Report Export (ZenDoc Pro)",
                "Exporting verified intelligence dossiers to PDF / Markdown is a ZenDoc Pro feature. Upgrade to export your research summaries instantly."
            );
            return;
        }

        // Collect all chat messages
        const msgNodes = chatWindow.querySelectorAll('.message');
        if (msgNodes.length === 0) {
            showToast("No conversation history to export yet. Ask questions first!", "error");
            return;
        }

        const messagesToExport = [];
        msgNodes.forEach(node => {
            const isUser = node.classList.contains('user-msg');
            const isAi = node.classList.contains('ai-msg');
            const textContent = node.querySelector('.msg-content')?.innerText || "";
            const pageBadge = node.querySelector('.receipt-page-badge')?.innerText || "";

            if (isUser) {
                messagesToExport.push({ type: "user", text: textContent });
            } else if (isAi) {
                messagesToExport.push({ type: "ai", text: textContent, page: pageBadge });
            }
        });

        try {
            exportReportBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Exporting...`;
            exportReportBtn.disabled = true;

            const res = await fetch(`${API_BASE}/api/export/report`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-Plan': plan.planId,
                    'X-User-Id': currentUser ? currentUser.uid : 'anon_device'
                },
                body: JSON.stringify({
                    document_name: activeDocumentName,
                    messages: messagesToExport
                })
            });

            if (res.ok) {
                const data = await res.json();
                const blob = new Blob([data.content], { type: 'text/markdown;charset=utf-8;' });
                const downloadUrl = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = data.filename || 'ZenDoc_Intelligence_Dossier.md';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(downloadUrl);
                showToast("Executive Dossier downloaded successfully!", "success");
            } else {
                const errData = await res.json();
                showPaywall("Export Locked", errData.detail?.message || "Upgrade to ZenDoc Pro to export reports.");
            }
        } catch (e) {
            showToast("Export error: " + e.message, "error");
        } finally {
            exportReportBtn.innerHTML = `<i class="fa-solid fa-file-export"></i> <span>Export Report</span>`;
            exportReportBtn.disabled = false;
        }
    });
}

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

function renderIndexedWorkspace(docName) {
    chatWindow.innerHTML = `
        <div class="workspace-hero-card" id="workspaceHero">
            <div class="hero-status-pill">
                <span class="pulse-dot"></span>
                <span>Document Grounding Active</span>
            </div>
            <div class="hero-doc-badge">
                <i class="fa-solid fa-file-pdf hero-doc-icon"></i>
                <div class="hero-doc-details">
                    <div class="hero-doc-title">${escapeHTML(docName)}</div>
                    <div class="hero-doc-meta">
                        <span><i class="fa-solid fa-layer-group"></i> FAISS In-Memory Vectors</span>
                        <span>•</span>
                        <span><i class="fa-solid fa-wand-magic-sparkles"></i> Gemini 2.5 Flash</span>
                    </div>
                </div>
            </div>
            <div class="hero-doc-prompt-heading"><i class="fa-solid fa-lightbulb"></i> Choose a starter prompt or ask a question below:</div>
            <div class="hero-prompts-grid">
                <button class="hero-prompt-card prompt-chip" data-prompt="Summarize this document in 5 key executive takeaways.">
                    <div class="prompt-icon-box"><i class="fa-solid fa-list-check"></i></div>
                    <div class="prompt-card-text">
                        <div class="prompt-card-title">Executive Summary</div>
                        <div class="prompt-card-desc">5 key takeaways & conclusions</div>
                    </div>
                    <i class="fa-solid fa-arrow-right prompt-arrow"></i>
                </button>
                <button class="hero-prompt-card prompt-chip" data-prompt="Extract all numerical data, statistics, and financial metrics from this document.">
                    <div class="prompt-icon-box"><i class="fa-solid fa-chart-column"></i></div>
                    <div class="prompt-card-text">
                        <div class="prompt-card-title">Data & Metrics</div>
                        <div class="prompt-card-desc">Financial statistics, numbers & KPIs</div>
                    </div>
                    <i class="fa-solid fa-arrow-right prompt-arrow"></i>
                </button>
                <button class="hero-prompt-card prompt-chip" data-prompt="What are the critical action items, risks, and recommendations outlined in this document?">
                    <div class="prompt-icon-box"><i class="fa-solid fa-triangle-exclamation"></i></div>
                    <div class="prompt-card-text">
                        <div class="prompt-card-title">Risks & Action Items</div>
                        <div class="prompt-card-desc">Liabilities, obligations & next steps</div>
                    </div>
                    <i class="fa-solid fa-arrow-right prompt-arrow"></i>
                </button>
                <button class="hero-prompt-card prompt-chip" data-prompt="List the main entities, organizations, and defined terms mentioned in this document.">
                    <div class="prompt-icon-box"><i class="fa-solid fa-tags"></i></div>
                    <div class="prompt-card-text">
                        <div class="prompt-card-title">Entities & Terms</div>
                        <div class="prompt-card-desc">Organizations, definitions & stakeholders</div>
                    </div>
                    <i class="fa-solid fa-arrow-right prompt-arrow"></i>
                </button>
            </div>
        </div>
    `;
}

function renderWelcomeState(customMessage = null) {
    chatWindow.innerHTML = `
        <div class="workspace-hero-card">
            <div class="hero-status-pill" style="background: rgba(71,101,80,0.12); color: var(--primary); border-color: rgba(71,101,80,0.25);">
                <i class="fa-solid fa-wand-magic-sparkles"></i>
                <span>Enterprise Document Intelligence</span>
            </div>
            <div class="hero-doc-badge">
                <i class="fa-solid fa-file-arrow-up hero-doc-icon"></i>
                <div class="hero-doc-details">
                    <div class="hero-doc-title">Ready for Ingestion</div>
                    <div class="hero-doc-meta">
                        <span>${customMessage || 'Upload any PDF, Word document, or Text file on the left.'}</span>
                    </div>
                </div>
            </div>
            <div class="hero-doc-prompt-heading"><i class="fa-solid fa-sparkles"></i> Example Reasoning Workflows:</div>
            <div class="hero-prompts-grid">
                <div class="hero-prompt-card" style="cursor:default; opacity:0.85;">
                    <div class="prompt-icon-box"><i class="fa-solid fa-list-check"></i></div>
                    <div class="prompt-card-text">
                        <div class="prompt-card-title">Executive Summaries</div>
                        <div class="prompt-card-desc">Auto-extract key findings & synthesis</div>
                    </div>
                </div>
                <div class="hero-prompt-card" style="cursor:default; opacity:0.85;">
                    <div class="prompt-icon-box"><i class="fa-solid fa-chart-column"></i></div>
                    <div class="prompt-card-text">
                        <div class="prompt-card-title">Financial Table Extraction</div>
                        <div class="prompt-card-desc">Balance sheets, P&L & numerical stats</div>
                    </div>
                </div>
                <div class="hero-prompt-card" style="cursor:default; opacity:0.85;">
                    <div class="prompt-icon-box"><i class="fa-solid fa-triangle-exclamation"></i></div>
                    <div class="prompt-card-text">
                        <div class="prompt-card-title">Audit & Risk Analysis</div>
                        <div class="prompt-card-desc">Contractual liabilities & action items</div>
                    </div>
                </div>
                <div class="hero-prompt-card" style="cursor:default; opacity:0.85;">
                    <div class="prompt-icon-box"><i class="fa-solid fa-file-invoice"></i></div>
                    <div class="prompt-card-text">
                        <div class="prompt-card-title">Visual Proof Grounding</div>
                        <div class="prompt-card-desc">Every answer cited with original page crops</div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function resetChatUI() {
    currentSessionId = null;
    activeDocumentName = "ZenDoc AI Workspace";
    activeDocTitle.textContent = activeDocumentName;
    chatInput.disabled = true;
    sendBtn.disabled = true;
    renderWelcomeState("Upload a document on the left to start a new reasoning session.");
    resetUploadUI();
}

const purgeDataBtn = document.getElementById('purgeDataBtn');
const purgeExplainModal = document.getElementById('purgeExplainModal');
const closePurgeModalBtn = document.getElementById('closePurgeModalBtn');
const cancelPurgeBtn = document.getElementById('cancelPurgeBtn');
const confirmPurgeBtn = document.getElementById('confirmPurgeBtn');

if (purgeDataBtn && purgeExplainModal) {
    purgeDataBtn.addEventListener('click', () => {
        purgeExplainModal.classList.add('active');
    });
}

if (closePurgeModalBtn) {
    closePurgeModalBtn.addEventListener('click', () => {
        if (purgeExplainModal) purgeExplainModal.classList.remove('active');
    });
}

if (cancelPurgeBtn) {
    cancelPurgeBtn.addEventListener('click', () => {
        if (purgeExplainModal) purgeExplainModal.classList.remove('active');
    });
}

if (purgeExplainModal) {
    purgeExplainModal.addEventListener('click', (e) => {
        if (e.target === purgeExplainModal) purgeExplainModal.classList.remove('active');
    });
}

if (confirmPurgeBtn) {
    confirmPurgeBtn.addEventListener('click', async () => {
        if (purgeExplainModal) purgeExplainModal.classList.remove('active');
        try {
            confirmPurgeBtn.disabled = true;
            await fetch(`${API_BASE}/api/session/clear`, { method: 'POST' });
        } catch (e) {
            console.warn("Backend session purge error:", e);
        }
        if (currentUser && currentSessionId) {
            try {
                await deleteSessionFromFirestore(currentUser.uid, currentSessionId);
                loadHistoryList();
            } catch (e) {
                console.warn(e);
            }
        }
        resetChatUI();
        confirmPurgeBtn.disabled = false;
        showToast("All document vectors, temporary files, and session history permanently erased.", "success");
    });
}

newChatBtn.addEventListener('click', () => {
    showConfirmDialog({
        title: "Clear Conversation",
        subtitle: "Start a Fresh Conversation?",
        desc: "The current chat messages will be cleared from your view.",
        icon: "fa-trash-can",
        onConfirm: () => {
            resetChatUI();
            showToast("Conversation cleared.");
        }
    });
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

    isProcessing = true;
    chatInput.value = '';
    chatInput.disabled = true;
    sendBtn.disabled = true;

    // Render User Message
    renderUserMessage(question);
    
    // Save User Msg to Firestore
    if (currentUser && currentSessionId) {
        await saveMessageToFirestore(currentUser.uid, currentSessionId, {
            sender: "user",
            text: question
        });
    }

    // Render Loading Shimmer
    const loadingMsgId = `loading_${Date.now()}`;
    const loadingDiv = document.createElement('div');
    loadingDiv.id = loadingMsgId;
    loadingDiv.classList.add('message', 'ai-msg');
    loadingDiv.innerHTML = `
        <div class="ai-statutory-label"><i class="fa-solid fa-microchip fa-spin"></i> Synthesizing Answer with Gemini 2.5 Flash...</div>
        <div class="msg-content shimmer-box">
            <div class="shimmer-line line-1"></div>
            <div class="shimmer-line line-2"></div>
            <div class="shimmer-line line-3"></div>
        </div>
    `;
    chatWindow.appendChild(loadingDiv);
    chatWindow.scrollTop = chatWindow.scrollHeight;

    try {
        const response = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: question })
        });

        const data = await response.json();
        
        // Remove loading shimmer
        const loadElem = document.getElementById(loadingMsgId);
        if (loadElem) loadElem.remove();

        if (response.ok && data.status === 'success') {
            renderAiMessage(data.answer, data.source_image, data.page, data.file_type);

            // Save AI Msg to Firestore
            if (currentUser && currentSessionId) {
                await saveMessageToFirestore(currentUser.uid, currentSessionId, {
                    sender: "ai",
                    text: data.answer,
                    sourceImage: data.source_image,
                    page: data.page,
                    fileType: data.file_type
                });
            }
        } else {
            throw new Error(data.message || data.detail || "Query reasoning failed");
        }
    } catch (error) {
        const loadElem = document.getElementById(loadingMsgId);
        if (loadElem) loadElem.remove();

        renderAiMessage(`
            <div class="error-bubble">
                <i class="fa-solid fa-triangle-exclamation"></i>
                <span>${escapeHTML(error.message)}</span>
            </div>
        `, null, null, null);
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
    
    let fullHtml = `
        <div class="ai-statutory-label">
            <i class="fa-solid fa-wand-magic-sparkles"></i> AI-Synthesized (Gemini 2.5 Flash) • Grounded in Context
        </div>
        <div class="msg-content">${htmlContent}
    `;
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
// VISUAL GROUNDING IMAGE LIGHTBOX
// ==========================================================================
const imageLightboxModal = document.getElementById('imageLightboxModal');
const lightboxImg = document.getElementById('lightboxImg');
const lightboxCaption = document.getElementById('lightboxCaption');
const closeLightboxBtn = document.getElementById('closeLightboxBtn');

document.addEventListener('click', (e) => {
    const cropImg = e.target.closest('.source-image-wrapper img');
    if (cropImg && imageLightboxModal && lightboxImg) {
        lightboxImg.src = cropImg.src;
        const label = cropImg.closest('.source-image-wrapper')?.querySelector('.source-label')?.innerText || "Visual Grounding Citation";
        if (lightboxCaption) lightboxCaption.textContent = label;
        imageLightboxModal.classList.add('active');
    }
});

if (closeLightboxBtn) {
    closeLightboxBtn.addEventListener('click', () => {
        if (imageLightboxModal) imageLightboxModal.classList.remove('active');
    });
}

if (imageLightboxModal) {
    imageLightboxModal.addEventListener('click', (e) => {
        if (e.target === imageLightboxModal) imageLightboxModal.classList.remove('active');
    });
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

