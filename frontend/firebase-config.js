// Firebase Configuration & Service Layer for Aneevalp DocAI
// Built for Google Cloud Gen AI Ideathon

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import { 
    getAuth, 
    GoogleAuthProvider, 
    signInWithPopup, 
    signOut, 
    onAuthStateChanged 
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import { 
    getFirestore, 
    collection, 
    doc, 
    setDoc, 
    getDocs, 
    addDoc, 
    deleteDoc,
    query, 
    orderBy, 
    serverTimestamp 
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";

// Default or Injected Firebase Config
const defaultFirebaseConfig = {
    apiKey: "AIzaSyDemoKeyForGoogleCloudGenAIIdeathon",
    authDomain: "aneevalp-docai.firebaseapp.com",
    projectId: "aneevalp-docai",
    storageBucket: "aneevalp-docai.appspot.com",
    messagingSenderId: "123456789012",
    appId: "1:123456789012:web:abcdef1234567890"
};

const firebaseConfig = window.__FIREBASE_CONFIG__ || defaultFirebaseConfig;

let app;
let auth;
let db;
let googleProvider;
let isFirebaseAvailable = false;

try {
    app = initializeApp(firebaseConfig);
    auth = getAuth(app);
    db = getFirestore(app);
    googleProvider = new GoogleAuthProvider();
    googleProvider.setCustomParameters({ prompt: 'select_account' });
    isFirebaseAvailable = true;
    console.log("Aneevalp DocAI: Firebase initialized successfully.");
} catch (err) {
    console.warn("Aneevalp DocAI: Firebase running in demo-ready mode.", err.message);
}

// Google Sign-In
export async function loginWithGoogle() {
    if (!isFirebaseAvailable || !auth || firebaseConfig.apiKey.startsWith("AIzaSyDemoKey")) {
        // Fallback realistic demo user if live project key not yet configured
        const mockUser = {
            uid: "google-apac-judge-01",
            displayName: "Google Cloud Judge",
            email: "judge@googlecloud.apac",
            photoURL: "https://lh3.googleusercontent.com/a/default-user=s96-c"
        };
        localStorage.setItem("aneevalp_auth_user", JSON.stringify(mockUser));
        return mockUser;
    }
    try {
        const result = await signInWithPopup(auth, googleProvider);
        localStorage.setItem("aneevalp_auth_user", JSON.stringify({
            uid: result.user.uid,
            displayName: result.user.displayName,
            email: result.user.email,
            photoURL: result.user.photoURL
        }));
        return result.user;
    } catch (error) {
        console.error("Google Sign-In Error:", error);
        throw error;
    }
}

// Logout
export async function logoutUser() {
    localStorage.removeItem("aneevalp_auth_user");
    if (auth && isFirebaseAvailable) {
        try {
            await signOut(auth);
        } catch (e) {
            console.warn(e);
        }
    }
}

// Get Cached Auth User
export function getCachedUser() {
    const cached = localStorage.getItem("aneevalp_auth_user");
    return cached ? JSON.parse(cached) : null;
}

// Listen to Auth State
export function onUserAuthStateChanged(callback) {
    if (!auth || !isFirebaseAvailable || firebaseConfig.apiKey.startsWith("AIzaSyDemoKey")) {
        const cached = getCachedUser();
        callback(cached);
        return () => {};
    }
    return onAuthStateChanged(auth, (user) => {
        if (user) {
            localStorage.setItem("aneevalp_auth_user", JSON.stringify({
                uid: user.uid,
                displayName: user.displayName,
                email: user.email,
                photoURL: user.photoURL
            }));
        } else {
            localStorage.removeItem("aneevalp_auth_user");
        }
        callback(user);
    });
}

// Save or Update Session in Firestore
export async function saveSessionToFirestore(userId, sessionId, sessionData) {
    if (!userId) return;
    
    // Save to Local Storage for instant offline cache
    const key = `aneevalp_sessions_${userId}`;
    let list = JSON.parse(localStorage.getItem(key) || "[]");
    const existingIndex = list.findIndex(s => s.id === sessionId);
    const newEntry = { id: sessionId, ...sessionData, updatedAt: new Date().toISOString() };
    if (existingIndex >= 0) {
        list[existingIndex] = { ...list[existingIndex], ...newEntry };
    } else {
        list.unshift(newEntry);
    }
    localStorage.setItem(key, JSON.stringify(list));

    if (db && isFirebaseAvailable && !firebaseConfig.apiKey.startsWith("AIzaSyDemoKey")) {
        try {
            const sessionRef = doc(db, "users", userId, "sessions", sessionId);
            await setDoc(sessionRef, {
                ...sessionData,
                updatedAt: serverTimestamp()
            }, { merge: true });
        } catch (e) {
            console.warn("Firestore Save Session:", e);
        }
    }
}

// Save Message in Firestore
export async function saveMessageToFirestore(userId, sessionId, message) {
    if (!userId) return;
    
    // Cache locally
    const msgKey = `aneevalp_msgs_${sessionId}`;
    let msgs = JSON.parse(localStorage.getItem(msgKey) || "[]");
    msgs.push({ ...message, createdAt: new Date().toISOString() });
    localStorage.setItem(msgKey, JSON.stringify(msgs));

    if (db && isFirebaseAvailable && !firebaseConfig.apiKey.startsWith("AIzaSyDemoKey")) {
        try {
            const messagesCol = collection(db, "users", userId, "sessions", sessionId, "messages");
            await addDoc(messagesCol, {
                ...message,
                createdAt: serverTimestamp()
            });
        } catch (e) {
            console.warn("Firestore Save Message:", e);
        }
    }
}

// Get User's Past Sessions
export async function fetchUserSessions(userId) {
    if (!userId) return [];
    
    if (db && isFirebaseAvailable && !firebaseConfig.apiKey.startsWith("AIzaSyDemoKey")) {
        try {
            const sessionsRef = collection(db, "users", userId, "sessions");
            const q = query(sessionsRef, orderBy("updatedAt", "desc"));
            const snapshot = await getDocs(q);
            const sessions = [];
            snapshot.forEach(docSnap => {
                sessions.push({ id: docSnap.id, ...docSnap.data() });
            });
            if (sessions.length > 0) return sessions;
        } catch (e) {
            console.warn("Firestore fetch error, reading local cache:", e);
        }
    }
    
    const local = localStorage.getItem(`aneevalp_sessions_${userId}`);
    return local ? JSON.parse(local) : [];
}

// Fetch Messages for a specific session
export async function fetchSessionMessages(userId, sessionId) {
    if (!userId || !sessionId) return [];
    
    if (db && isFirebaseAvailable && !firebaseConfig.apiKey.startsWith("AIzaSyDemoKey")) {
        try {
            const messagesRef = collection(db, "users", userId, "sessions", sessionId, "messages");
            const q = query(messagesRef, orderBy("createdAt", "asc"));
            const snapshot = await getDocs(q);
            const messages = [];
            snapshot.forEach(docSnap => {
                messages.push({ id: docSnap.id, ...docSnap.data() });
            });
            if (messages.length > 0) return messages;
        } catch (e) {
            console.warn("Firestore messages fetch error, reading local cache:", e);
        }
    }
    
    const localMsgs = localStorage.getItem(`aneevalp_msgs_${sessionId}`);
    return localMsgs ? JSON.parse(localMsgs) : [];
}

// Delete Session
export async function deleteSessionFromFirestore(userId, sessionId) {
    if (!userId || !sessionId) return;
    
    const key = `aneevalp_sessions_${userId}`;
    const list = JSON.parse(localStorage.getItem(key) || "[]").filter(s => s.id !== sessionId);
    localStorage.setItem(key, JSON.stringify(list));
    localStorage.removeItem(`aneevalp_msgs_${sessionId}`);

    if (db && isFirebaseAvailable && !firebaseConfig.apiKey.startsWith("AIzaSyDemoKey")) {
        try {
            const sessionRef = doc(db, "users", userId, "sessions", sessionId);
            await deleteDoc(sessionRef);
        } catch (e) {
            console.warn("Firestore Delete Session:", e);
        }
    }
}
