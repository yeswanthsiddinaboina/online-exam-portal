// Automatically detect API base URL (works on localhost:5001 and in production e.g. https://your-app.onrender.com)
const API_BASE = (window.location.protocol.startsWith("http") && window.location.host) 
    ? `${window.location.origin}/api` 
    : "http://127.0.0.1:5001/api";

const isAdminPage = window.location.pathname.includes("/admin/");
const tokenKey = isAdminPage ? "admin_token" : "token";
const userKey = isAdminPage ? "admin_user" : "user";

console.log("APP_DEBUG: path=" + window.location.pathname + " | port=" + window.location.port + " | isAdminPage=" + isAdminPage + " | tokenKey=" + tokenKey);

let currentToken = localStorage.getItem(tokenKey) || null;
let currentUser = null;
try {
    const rawUser = localStorage.getItem(userKey);
    currentUser = (rawUser && rawUser !== "undefined") ? JSON.parse(rawUser) : null;
} catch (e) {
    currentUser = null;
}
let currentAttemptId = localStorage.getItem("attempt_id") || null;
let currentSessionToken = localStorage.getItem("session_token") || null;
let heartbeatTimer = null;
let examTimer = null;
let mediaStream = null;

// Global HTML sanitization helper to safely render user text, code snippets, and tags
function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>\'"]/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\'": "&#39;", '"': "&quot;"
    }[character]));
}

// Configure API request headers
function getHeaders(contentType = "application/json") {
    const headers = {};
    if (contentType) {
        headers["Content-Type"] = contentType;
    }
    if (currentToken) {
        headers["Authorization"] = `Bearer ${currentToken}`;
    }
    return headers;
}

// Role routing
const ADMIN_PORT = "5001";
const STUDENT_PORT = "5001";

function getRoleRedirectUrl(role, path) {
    const loc = window.location;
    // In production (standard 80/443 or Render where port is empty), stay on same origin
    if (!loc.port || loc.port === "80" || loc.port === "443") {
        return path;
    }
    // In local development:
    const targetPort = role === "admin" ? ADMIN_PORT : STUDENT_PORT;
    return `${loc.protocol}//${loc.hostname}:${targetPort}${path}`;
}

function redirectToLogin(dest = "") {
    if (isAdminPage) {
        const adminLogin = window.location.pathname.includes("/admin/") ? "login.html" : "/admin/login.html";
        window.location.href = `${adminLogin}?redirect=${dest}`;
    } else {
        window.location.href = `/login.html?role=student&redirect=${dest}`;
    }
}

// Redirects helper
function checkAuth(requiredRole = null) {
    if (!currentToken) {
        const dest = encodeURIComponent(window.location.pathname + window.location.search);
        redirectToLogin(dest);
        return;
    }
    if (requiredRole && currentUser && currentUser.role !== requiredRole) {
        if (currentUser.role === "admin") {
            window.location.href = getRoleRedirectUrl("admin", "/admin/dashboard.html");
        } else {
            window.location.href = getRoleRedirectUrl("student", "/dashboard.html");
        }
    }
}

// --- API CLIENT WRAPPER ---
const API = {
    async post(endpoint, body) {
        try {
            const res = await fetch(`${API_BASE}${endpoint}`, {
                method: "POST",
                headers: getHeaders(),
                body: JSON.stringify(body)
            });
            if (res.status === 401 && endpoint !== "/auth/login") {
                localStorage.removeItem(tokenKey);
                localStorage.removeItem(userKey);
                const dest = encodeURIComponent(window.location.pathname + window.location.search);
                redirectToLogin(dest);
                return { success: false, error_code: "UNAUTHORIZED", message: "Session expired." };
            }
            return await res.json();
        } catch (e) {
            console.error("API POST error:", e);
            return { success: false, error_code: "NETWORK_ERROR", message: "Network connectivity issue." };
        }
    },

    async get(endpoint) {
        try {
            const separator = endpoint.includes("?") ? "&" : "?";
            const url = `${API_BASE}${endpoint}${separator}_t=${Date.now()}`;
            const res = await fetch(url, {
                method: "GET",
                headers: getHeaders()
            });
            if (res.status === 401) {
                localStorage.removeItem(tokenKey);
                localStorage.removeItem(userKey);
                const dest = encodeURIComponent(window.location.pathname + window.location.search);
                redirectToLogin(dest);
                return { success: false, error_code: "UNAUTHORIZED", message: "Session expired." };
            }
            return await res.json();
        } catch (e) {
            console.error("API GET error:", e);
            return { success: false, error_code: "NETWORK_ERROR", message: "Network connectivity issue." };
        }
    },

    async delete(endpoint) {
        try {
            const res = await fetch(`${API_BASE}${endpoint}`, {
                method: "DELETE",
                headers: getHeaders()
            });
            if (res.status === 401) {
                localStorage.removeItem(tokenKey);
                localStorage.removeItem(userKey);
                const dest = encodeURIComponent(window.location.pathname + window.location.search);
                redirectToLogin(dest);
                return { success: false, error_code: "UNAUTHORIZED", message: "Session expired." };
            }
            return await res.json();
        } catch (e) {
            console.error("API DELETE error:", e);
            return { success: false, error_code: "NETWORK_ERROR", message: "Network connectivity issue." };
        }
    },

    async upload(endpoint, formData) {
        try {
            const res = await fetch(`${API_BASE}${endpoint}`, {
                method: "POST",
                headers: getHeaders(null), // Empty Content-Type for multipart boundaries
                body: formData
            });
            if (res.status === 401) {
                localStorage.removeItem(tokenKey);
                localStorage.removeItem(userKey);
                const dest = encodeURIComponent(window.location.pathname + window.location.search);
                redirectToLogin(dest);
                return { success: false, error_code: "UNAUTHORIZED", message: "Session expired." };
            }
            return await res.json();
        } catch (e) {
            console.error("API Upload error:", e);
            return { success: false, error_code: "NETWORK_ERROR", message: "Network upload failed." };
        }
    }
};

// --- AUTHENTICATION ---
async function handleLogin(email, password, username = "", student_id = "") {
    const submitBtn = document.getElementById("btn-submit");
    const originalText = submitBtn ? submitBtn.innerText : "Enter Examination";
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerText = "Signing in...";
    }

    try {
        const res = await API.post("/auth/login", { 
            identifier: email, 
            email: email, 
            password: password, 
            username: username, 
            student_id: student_id 
        });

        if (res.success) {
            const targetTokenKey = res.role === "admin" ? "admin_token" : "token";
            const targetUserKey = res.role === "admin" ? "admin_user" : "user";
            localStorage.setItem(targetTokenKey, res.token);
            localStorage.setItem(targetUserKey, JSON.stringify(res.user));
            currentToken = res.token;
            currentUser = res.user;
            
            const urlParams = new URLSearchParams(window.location.search);
            const redirectUrl = urlParams.get("redirect");
            
            if (redirectUrl) {
                const decoded = decodeURIComponent(redirectUrl);
                if (decoded.startsWith("/")) {
                    window.location.href = getRoleRedirectUrl(res.role, decoded);
                } else {
                    window.location.href = decoded;
                }
            } else {
                if (res.role === "admin") {
                    window.location.href = getRoleRedirectUrl("admin", "/admin/dashboard.html");
                } else {
                    window.location.href = getRoleRedirectUrl("student", "/dashboard.html");
                }
            }
        } else {
            alert(res.message || "Login failed");
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerText = originalText;
            }
        }
    } catch (err) {
        console.error("Login error:", err);
        alert("An error occurred while communicating with the login server.");
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerText = originalText;
        }
    }
}

async function handleRegister(firstName, lastName, email, password, role) {
    const res = await API.post("/auth/register", {
        first_name: firstName,
        last_name: lastName,
        email: email,
        password: password,
        role: role
    });
    if (res.success) {
        alert("Registration successful. Please log in.");
        window.location.href = "/login.html";
    } else {
        alert(res.message || "Registration failed");
    }
}

function handleLogout() {
    const pageIsAdmin = window.location.pathname.includes("/admin/");
    if (pageIsAdmin) {
        localStorage.removeItem("admin_token");
        localStorage.removeItem("admin_user");
    } else {
        localStorage.removeItem("token");
        localStorage.removeItem("user");
        localStorage.removeItem("attempt_id");
        localStorage.removeItem("session_token");
        localStorage.removeItem("selected_exam_id");
    }
    
    // Notify the backend asynchronously to write audit logs
    API.post("/auth/logout", {}).catch(e => console.warn("Async logout notify error:", e));
    
    if (pageIsAdmin) {
        window.location.href = "/admin/login.html";
    } else {
        window.location.href = "/login.html?role=student";
    }
}

// --- SYSTEM CHECK MANAGER ---
class SystemPreCheck {
    static async checkConnectivity() {
        return navigator.onLine;
    }

    static async requestCamera() {
        try {
            mediaStream = await navigator.mediaDevices.getUserMedia({ 
                video: { width: 640, height: 480 },
                audio: false
            });
            return true;
        } catch (e) {
            console.error("Webcam access error:", e);
            return false;
        }
    }

    static releaseMedia() {
        if (mediaStream) {
            mediaStream.getTracks().forEach(track => track.stop());
            mediaStream = null;
        }
    }
}

// --- BIOMETRIC FACIAL LANDMARK COMPARATOR ---
class FaceBiometrics {
    // Key landmark indices for structural face shape:
    // Eye corners, eyebrows, nose bridge/tip, lips, chin, cheek contours
    static KEY_LANDMARK_INDICES = [
        33, 133, 159, 145,       // Left eye corners and eyelids
        263, 362, 386, 374,      // Right eye corners and eyelids
        70, 63, 105, 66, 107,    // Left eyebrow
        300, 293, 334, 296, 336, // Right eyebrow
        1, 2, 4, 5, 6, 168, 197, // Nose bridge and tip
        61, 291, 0, 17, 13, 14,  // Lips and mouth
        152, 148, 176,           // Chin
        234, 454, 127, 356       // Cheeks and jawline
    ];

    static normalize(landmarks) {
        if (!landmarks || landmarks.length < 264) return null;
        
        const leftEye = landmarks[33];
        const rightEye = landmarks[263];
        const nose = landmarks[4];
        if (!leftEye || !rightEye || !nose) return null;
        
        const cx = nose.x;
        const cy = nose.y;
        const cz = nose.z || 0;
        
        const dx = rightEye.x - leftEye.x;
        const dy = rightEye.y - leftEye.y;
        const dz = (rightEye.z || 0) - (leftEye.z || 0);
        const eyeDist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        
        if (eyeDist < 0.001) return null;
        
        return this.KEY_LANDMARK_INDICES.map(idx => {
            const pt = landmarks[idx] || landmarks[0];
            return {
                x: (pt.x - cx) / eyeDist,
                y: (pt.y - cy) / eyeDist,
                z: ((pt.z || 0) - cz) / eyeDist
            };
        });
    }

    static compare(profileA, profileB) {
        if (!profileA || !profileB || profileA.length === 0 || profileA.length !== profileB.length) {
            return 1.0;
        }
        
        let total = 0;
        for (let i = 0; i < profileA.length; i++) {
            const dx = profileA[i].x - profileB[i].x;
            const dy = profileA[i].y - profileB[i].y;
            const dz = profileA[i].z - profileB[i].z;
            total += Math.sqrt(dx * dx + dy * dy + dz * dz);
        }
        return total / profileA.length;
    }
}

// --- BROWSER LOCKDOWN ENFORCER ---
class SandboxEnforcer {
    static init(attemptId, token, onWarning, onTerminate) {
        this.attemptId = attemptId;
        this.token = token;
        this.onWarning = onWarning;
        this.onTerminate = onTerminate;
        this.lastTabSwitchTime = 0;
        this.active = true;
        
        // Retain bound method references so removeEventListener cleanly unregisters them
        this._boundVisibilityChange = this.handleVisibilityChange.bind(this);
        this._boundWindowBlur = this.handleWindowBlur.bind(this);
        this._boundFullscreenChange = this.handleFullscreenChange.bind(this);
        this._boundKeydown = this.blockShortcuts.bind(this);
        this._boundContextMenu = this.blockContextMenu.bind(this);
        
        document.addEventListener("visibilitychange", this._boundVisibilityChange);
        window.addEventListener("blur", this._boundWindowBlur);
        document.addEventListener("fullscreenchange", this._boundFullscreenChange);
        window.addEventListener("keydown", this._boundKeydown);
        document.addEventListener("contextmenu", this._boundContextMenu);
    }

    static pause() {
        this.active = false;
    }

    static resume() {
        this.active = true;
    }

    static destroy() {
        this.active = false;
        if (this._boundVisibilityChange) {
            document.removeEventListener("visibilitychange", this._boundVisibilityChange);
            window.removeEventListener("blur", this._boundWindowBlur);
            document.removeEventListener("fullscreenchange", this._boundFullscreenChange);
            window.removeEventListener("keydown", this._boundKeydown);
            document.removeEventListener("contextmenu", this._boundContextMenu);
        }
    }

    static handleVisibilityChange() {
        if (!this.active) return;
        if (document.visibilityState === "hidden") {
            this.reportTabSwitch();
        }
    }

    static handleWindowBlur() {
        if (!this.active) return;
        this.reportTabSwitch();
    }

    static reportTabSwitch() {
        if (!this.active) return;
        const now = Date.now();
        if (now - this.lastTabSwitchTime > 2000) { // 2 seconds debounce
            this.lastTabSwitchTime = now;
            this.reportInfrac("TAB_SWITCH");
        }
    }

    static handleFullscreenChange() {
        if (!this.active) return;
        if (!document.fullscreenElement) {
            this.reportInfrac("FULLSCREEN_EXIT");
        }
    }

    static blockShortcuts(e) {
        if (!this.active) return;
        // Block Escape, F5, Ctrl+R, F12, Alt+Tab, print shortcuts
        const blockedKeys = ["F5", "F12"];
        if (blockedKeys.includes(e.key) || (e.ctrlKey && ["r", "c", "v", "p"].includes(e.key.toLowerCase()))) {
            e.preventDefault();
            e.stopPropagation();
            return false;
        }
    }

    static blockContextMenu(e) {
        if (!this.active) return;
        e.preventDefault();
        return false;
    }

    static async reportInfrac(eventType) {
        if (!this.active) return;
        const res = await API.post("/proctor/events", {
            attempt_id: this.attemptId,
            session_token: this.token,
            event_type: eventType,
            confidence: 1.0
        });
        
        if (res.success) {
            // TEMPORARY OVERRIDE FOR TOMORROW'S EXAM: Set to false to re-enable
            const DISABLE_EXAM_TERMINATION = true;
            if (res.action === "TERMINATE" && !DISABLE_EXAM_TERMINATION) {
                this.onTerminate(res.message);
            } else if (res.action === "WARNING" || res.action === "TERMINATE") {
                this.onWarning(res.message, res.violation_log_id);
            }
        }
    }
}

// --- AI COMPUTER VISION ENFORCER ---
class AIProctorEngine {
    static init(videoElement, canvasElement, attemptId, token, onWarning, onTerminate) {
        this.video = videoElement;
        this.canvas = canvasElement;
        this.ctx = canvasElement.getContext("2d");
        this.attemptId = attemptId;
        this.token = token;
        this.onWarning = onWarning;
        this.onTerminate = onTerminate;
        this.running = false;
        this.faceMesh = null;
        this.cocoModel = null;
        this.latestPredictions = [];
        this.isProcessing = false;
        this.lastPhoneAlertTime = 0;
        this.lastMultiPersonAlertTime = 0;

        // Dedicated downscaled canvas for 10x faster MobileNet object & person detection
        this.detectCanvas = document.createElement("canvas");
        this.detectCanvas.width = 320;
        this.detectCanvas.height = 240;
        this.detectCtx = this.detectCanvas.getContext("2d", { willReadFrequently: true });
        
        // High-frequency frame sampling: Ultra-responsive 180ms interval (~5-6 FPS)
        this.sampleInterval = 180; 
        
        // Cooldown maps to prevent multiple rapid api calls in JS
        this.lastEventTimes = {};
    }

    static showDebug(msg) {
        const consoleEl = document.getElementById("proctor-debug-console");
        if (consoleEl) {
            consoleEl.innerHTML += `<div>[${new Date().toLocaleTimeString()}] ${msg}</div>`;
            consoleEl.scrollTop = consoleEl.scrollHeight;
        }
    }

    static async start() {
        this.running = true;
        this.showDebug("Starting high-speed secure proctoring session...");
        
        if (typeof tf !== "undefined") {
            try {
                await tf.ready();
                this.showDebug("TensorFlow.js ready. Engine Backend: " + tf.getBackend());
            } catch (e) {
                this.showDebug("TensorFlow backend note: " + e.message);
            }
        }

        // Load COCO-SSD object detection model with fast mobile weights for real-time mobile & partial person detection
        if (typeof cocoSsd !== "undefined") {
            this.showDebug("Loading COCO-SSD high-speed detector...");
            cocoSsd.load({ base: 'lite_mobilenet_v2' }).catch(() => cocoSsd.load()).then(model => {
                this.cocoModel = model;
                this.showDebug("📱 High-speed detector active (Mobile Phone & Partial Person AI ready).");
                const statusEl = document.getElementById("detection-model-status");
                if (statusEl) {
                    statusEl.innerText = "📱 Detector: Active (High Speed)";
                    statusEl.style.color = "#10b981";
                }
            }).catch(err => {
                this.showDebug("COCO-SSD Load Error: " + err.message);
                const statusEl = document.getElementById("detection-model-status");
                if (statusEl) {
                    statusEl.innerText = "📱 Detector: Failed to Load";
                    statusEl.style.color = "#ef4444";
                }
            });
        } else {
            this.showDebug("COCO-SSD library NOT available!");
            const statusEl = document.getElementById("detection-model-status");
            if (statusEl) {
                statusEl.innerText = "📱 Detector: Library Unavailable";
                statusEl.style.color = "#ef4444";
            }
        }
        
        // Load verified candidate biometric profile for continuous exam face matching
        const storedProfile = localStorage.getItem("verified_face_profile");
        if (storedProfile) {
            try {
                this.verifiedProfile = JSON.parse(storedProfile);
                this.showDebug("Verified candidate profile loaded. Continuous identity matching active.");
            } catch (e) {
                this.verifiedProfile = null;
            }
        } else {
            this.showDebug("⚠️ No verified face profile found!");
        }

        // Load MediaPipe FaceMesh with enhanced sensitivity for partial and turned faces
        if (typeof FaceMesh !== "undefined") {
            this.showDebug("Loading MediaPipe FaceMesh (Enhanced Sensitivity)...");
            this.faceMesh = new FaceMesh({
                locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`
            });

            this.faceMesh.setOptions({
                maxNumFaces: 6, // Detect up to 6 faces (groups, passersby, partial faces)
                refineLandmarks: false, // Save massive CPU by skipping 3D iris
                minDetectionConfidence: 0.30, // Highly sensitive to partial / turned faces
                minTrackingConfidence: 0.30
            });

            this.faceMesh.onResults(this.onResults.bind(this));
            this.inferenceLoop();
        } else {
            this.showDebug("MediaPipe FaceMesh not loaded! Running basic video check fallback.");
            this.basicCameraAuditLoop();
        }
    }

    static stop() {
        this.running = false;
    }

    static async inferenceLoop() {
        if (!this.running) return;
        
        if (this.video && this.video.readyState >= 2 && !this.isProcessing) {
            this.isProcessing = true;
            try {
                // 1. Send frame to MediaPipe FaceMesh
                const facePromise = this.faceMesh ? this.faceMesh.send({ image: this.video }) : Promise.resolve();
                
                // 2. High-speed COCO-SSD Detection on downscaled 320x240 offscreen canvas
                let objectPromise = Promise.resolve();
                if (this.cocoModel && this.detectCtx) {
                    this.detectCtx.drawImage(this.video, 0, 0, 320, 240);
                    objectPromise = this.cocoModel.detect(this.detectCanvas, 10, 0.20);
                }

                const [, rawPredictions] = await Promise.all([facePromise, objectPromise]);
                
                if (rawPredictions && rawPredictions.length > 0) {
                    // Rescale bounding boxes back to display canvas dimensions
                    const scaleX = (this.canvas.width || 400) / 320;
                    const scaleY = (this.canvas.height || 300) / 240;
                    
                    this.latestPredictions = rawPredictions.map(p => ({
                        class: p.class.toLowerCase(),
                        score: p.score,
                        bbox: [
                            p.bbox[0] * scaleX,
                            p.bbox[1] * scaleY,
                            p.bbox[2] * scaleX,
                            p.bbox[3] * scaleY
                        ]
                    }));
                } else if (rawPredictions) {
                    this.latestPredictions = [];
                }

                // Process high-priority object checks immediately for 0ms delay:
                this.evaluateLiveDetections();

            } catch (e) {
                console.warn("AI proctoring frame error:", e);
            } finally {
                this.isProcessing = false;
            }
        }
        
        setTimeout(() => this.inferenceLoop(), this.sampleInterval);
    }

    static evaluateLiveDetections() {
        const predictions = this.latestPredictions || [];
        
        // A. MOBILE PHONE & PROHIBITED DEVICE DETECTION (Sensitive down to 0.25 confidence)
        const prohibitedClasses = [
            "cell phone", "phone", "mobile phone", "telephone",
            "remote", "laptop", "tablet", "book"
        ];
        
        const phoneViolation = predictions.find(p => 
            prohibitedClasses.includes(p.class) && p.score >= 0.25
        );

        // Instant hardware badge update in proctoring panel
        const phoneStatusEl = document.getElementById("dev-phone-status");
        if (phoneStatusEl) {
            if (phoneViolation) {
                phoneStatusEl.innerHTML = `
                    <span style="font-size: 1rem; color: #ef4444;">📱</span>
                    <div>
                        <span style="font-size: 0.68rem; color: #ef4444; display: block; line-height: 1.1; font-weight: 700;">PROHIBITED</span>
                        <strong style="color: #ef4444;">Phone Detected!</strong>
                    </div>
                `;
            } else {
                phoneStatusEl.innerHTML = `
                    <span style="font-size: 1rem;">📱</span>
                    <div>
                        <span style="font-size: 0.68rem; color: #6B7280; display: block; line-height: 1.1;">Phone</span>
                        <strong style="color: #111827;">No phone detected</strong>
                    </div>
                `;
            }
        }

        if (phoneViolation) {
            const now = Date.now();
            if (now - this.lastPhoneAlertTime > 3500) { // Rapid 3.5-second trigger
                this.lastPhoneAlertTime = now;
                this.showDebug(`🚨 Mobile phone detected (${(phoneViolation.score * 100).toFixed(0)}%)!`);
                this.triggerEvent("PHONE_DETECTED", Math.max(phoneViolation.score, 0.6));
            }
        }

        // B. MULTIPLE PERSON / PARTIAL PERSON DETECTION VIA COCO-SSD
        const personDetections = predictions.filter(p => p.class === "person" && p.score >= 0.25);
        if (personDetections.length > 1) {
            const now = Date.now();
            if (now - this.lastMultiPersonAlertTime > 3500) {
                this.lastMultiPersonAlertTime = now;
                this.showDebug(`⚠️ Second person / partial presence detected in frame (${personDetections.length} persons seen)!`);
                this.triggerEvent("MULTIPLE_PERSON", 0.95);
            }
        }
    }

    static onResults(results) {
        // Sync canvas size to match video dimensions exactly
        if (this.canvas.width !== this.video.videoWidth || this.canvas.height !== this.video.videoHeight) {
            this.canvas.width = this.video.videoWidth || 400;
            this.canvas.height = this.video.videoHeight || 300;
        }

        // Clear overlay
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        const faces = results.multiFaceLandmarks || [];
        const predictions = this.latestPredictions || [];
        
        // Identify all person bounding boxes
        const personDetections = predictions.filter(p => p.class === "person" && p.score >= 0.25);
        
        // Multi-Person flag check
        let isMultiPerson = false;
        let multiPersonReason = "";

        if (faces.length > 1) {
            isMultiPerson = true;
            multiPersonReason = `Multiple faces detected (${faces.length})`;
        } else if (personDetections.length > 1) {
            isMultiPerson = true;
            multiPersonReason = `Multiple persons / partial body detected (${personDetections.length})`;
        } else if (faces.length === 1 && personDetections.length === 1) {
            // Check if the single detected person box is completely separate from candidate's face
            // (e.g. someone standing behind or to the side while candidate's face is seen)
            const face = faces[0];
            const faceCenterX = ((face[4].x + face[152].x) / 2) * this.canvas.width;
            const faceCenterY = ((face[4].y + face[152].y) / 2) * this.canvas.height;
            const [px, py, pw, ph] = personDetections[0].bbox;
            
            const faceInsidePerson = (
                faceCenterX >= px - 40 &&
                faceCenterX <= (px + pw + 40) &&
                faceCenterY >= py - 40 &&
                faceCenterY <= (py + ph + 40)
            );
            
            if (!faceInsidePerson && personDetections[0].score >= 0.35) {
                isMultiPerson = true;
                multiPersonReason = "Unauthorized second person near candidate";
            }
        }

        // Update Top Face Verified Badge UI
        // TEMPORARY OVERRIDE FOR TOMORROW'S EXAM: Set to false to re-enable
        const DISABLE_MULTIPLE_PERSON = true;

        // Update Top Face Verified Badge UI
        const faceStatusPill = document.getElementById("face-verified-pill");
        const faceStatusText = document.getElementById("face-status-text");
        if (faceStatusPill && faceStatusText) {
            if (!DISABLE_MULTIPLE_PERSON && isMultiPerson) {
                faceStatusPill.style.background = "#FEE2E2";
                faceStatusPill.style.borderColor = "#EF4444";
                faceStatusPill.style.color = "#DC2626";
                faceStatusText.innerText = "⚠️ Multiple / Partial Person Detected!";
            } else if (faces.length === 0) {
                faceStatusPill.style.background = "#FEF3C7";
                faceStatusPill.style.borderColor = "#F59E0B";
                faceStatusPill.style.color = "#B45309";
                faceStatusText.innerText = "⚠️ Face Not Detected";
            } else {
                faceStatusPill.style.background = "#ECFDF5";
                faceStatusPill.style.borderColor = "rgba(16, 185, 129, 0.25)";
                faceStatusPill.style.color = "#047857";
                faceStatusText.innerText = "Face verified";
            }
        }

        // Draw Object & Person Bounding Boxes with distinct high-visibility styles
        predictions.forEach(pred => {
            const [x, y, width, height] = pred.bbox;
            const isProhibitedDevice = ["cell phone", "phone", "mobile phone", "telephone", "remote", "laptop", "tablet", "book"].includes(pred.class);
            const isPerson = pred.class === "person";
            
            if (isProhibitedDevice) {
                // Flashy red box with warning label for mobile devices
                this.ctx.strokeStyle = "#EF4444";
                this.ctx.lineWidth = 3;
                this.ctx.strokeRect(x, y, width, height);
                
                this.ctx.fillStyle = "rgba(239, 68, 68, 0.85)";
                this.ctx.fillRect(x, Math.max(0, y - 22), Math.max(140, width), 22);
                
                this.ctx.fillStyle = "#FFFFFF";
                this.ctx.font = "bold 11px sans-serif";
                this.ctx.fillText(`🚨 ${pred.class.toUpperCase()} ${(pred.score * 100).toFixed(0)}%`, x + 6, Math.max(15, y - 6));
            } else if (isPerson && isMultiPerson && !DISABLE_MULTIPLE_PERSON) {
                // Red box for second person / unauthorized presence
                this.ctx.strokeStyle = "#DC2626";
                this.ctx.lineWidth = 2.5;
                this.ctx.setLineDash([6, 4]);
                this.ctx.strokeRect(x, y, width, height);
                this.ctx.setLineDash([]);
                
                this.ctx.fillStyle = "rgba(220, 38, 38, 0.85)";
                this.ctx.fillRect(x, Math.max(0, y - 20), 160, 20);
                this.ctx.fillStyle = "#FFFFFF";
                this.ctx.font = "bold 11px sans-serif";
                this.ctx.fillText("⚠️ PERSON / PARTIAL PRESENCE", x + 4, Math.max(14, y - 5));
            }
        });

        // 1. Absence check
        if (faces.length === 0) {
            this.consecutiveMismatches = 0;
            this.triggerEvent("FACE_ABSENT", 1.0);
            return;
        }

        // 2. Multiple person check (Face or Body presence)
        if (!DISABLE_MULTIPLE_PERSON && isMultiPerson) {
            this.consecutiveMismatches = 0;
            const now = Date.now();
            if (now - this.lastMultiPersonAlertTime > 3500) {
                this.lastMultiPersonAlertTime = now;
                this.triggerEvent("MULTIPLE_PERSON", 0.95);
                this.showDebug(`⚠️ ${multiPersonReason}`);
            }
            return;
        }

        // 3. Face Biometric Identity Verification (Comparing against Step 1 & 2 verified candidate)
        // TEMPORARY OVERRIDE FOR TOMORROW'S EXAM: Set to false to re-enable
        const DISABLE_FACE_MISMATCH = true;
        const landmarks = faces[0];
        if (!DISABLE_FACE_MISMATCH && this.verifiedProfile) {
            const currentProfile = FaceBiometrics.normalize(landmarks);
            if (currentProfile) {
                const distance = FaceBiometrics.compare(this.verifiedProfile, currentProfile);
                
                if (distance >= 0.24) {
                    this.consecutiveMismatches = (this.consecutiveMismatches || 0) + 1;
                    this.showDebug(`⚠️ FACE MISMATCH: Distance=${distance.toFixed(3)} [${this.consecutiveMismatches}/2]`);
                    
                    if (this.consecutiveMismatches >= 2) {
                        this.triggerEvent("FACE_MISMATCH", 1.0);
                        this.ctx.fillStyle = "rgba(239, 68, 68, 0.9)";
                        this.ctx.font = "bold 13px sans-serif";
                        this.ctx.fillText("⚠️ IDENTITY MISMATCH", 10, 25);
                    }
                } else {
                    this.consecutiveMismatches = 0;
                }
            }
        }

        // 4. Head pose / Gaze tracking estimation
        // TEMPORARY OVERRIDE FOR TOMORROW'S EXAM: Only show head violation when head turns to 75 degrees or more from camera angle
        // Landmarks: 4 (Nose Tip), 33 (Left Eye boundary), 263 (Right Eye boundary), 152 (Chin), 10 (Forehead)
        const nose = landmarks[4];
        const leftEye = landmarks[33];
        const rightEye = landmarks[263];
        const chin = landmarks[152];
        const forehead = landmarks[10];

        // 75 degrees angle threshold from camera angle for tomorrow's exam
        const HEAD_TURN_ANGLE_THRESHOLD = 75;

        if (nose && leftEye && rightEye && chin && forehead) {
            const W = this.canvas.width || 640;
            const H = this.canvas.height || 480;

            const pLeft = { x: leftEye.x * W, y: leftEye.y * H, z: (leftEye.z || 0) * W };
            const pRight = { x: rightEye.x * W, y: rightEye.y * H, z: (rightEye.z || 0) * W };
            const pChin = { x: chin.x * W, y: chin.y * H, z: (chin.z || 0) * W };
            const pForehead = { x: forehead.x * W, y: forehead.y * H, z: (forehead.z || 0) * W };
            const pNose = { x: nose.x * W, y: nose.y * H, z: (nose.z || 0) * W };

            // Horizontal vector across the eyes
            const u = {
                x: pRight.x - pLeft.x,
                y: pRight.y - pLeft.y,
                z: pRight.z - pLeft.z
            };

            // Vertical vector down the face (Forehead to Chin)
            const v = {
                x: pChin.x - pForehead.x,
                y: pChin.y - pForehead.y,
                z: pChin.z - pForehead.z
            };

            // 3D Face normal vector via cross product (u x v)
            const Nx = u.y * v.z - u.z * v.y;
            const Ny = u.z * v.x - u.x * v.z;
            const Nz = u.x * v.y - u.y * v.x;
            const norm = Math.sqrt(Nx * Nx + Ny * Ny + Nz * Nz);

            let angle3D = 0;
            let yawDeg = 0;
            let pitchDeg = 0;

            if (norm > 0.0001) {
                const cosAngle = Math.min(1.0, Math.max(-1.0, Math.abs(Nz) / norm));
                angle3D = Math.acos(cosAngle) * (180 / Math.PI);
                yawDeg = Math.abs(Math.atan2(Nx, Math.abs(Nz))) * (180 / Math.PI);
                pitchDeg = Math.abs(Math.atan2(Ny, Math.abs(Nz))) * (180 / Math.PI);
            }

            // 2D horizontal projection ratio check (corroborating metric)
            const eyeDistX = pRight.x - pLeft.x;
            let angle2D = 0;
            if (eyeDistX > 0) {
                const noseRelX = (pNose.x - pLeft.x) / eyeDistX;
                // Center is ~0.50. Deviation ranges from 0.0 (facing camera) to 1.0 (~75°-90°)
                const deviation2D = Math.min(1.0, Math.abs(noseRelX - 0.5) * 2.0);
                angle2D = Math.asin(deviation2D) * (180 / Math.PI);
            }

            // The effective head turn angle from camera axis
            const measuredAngle = Math.max(angle3D, yawDeg, angle2D);

            // Trigger violation ONLY when head turns to 75 degrees or more from camera angle
            if (measuredAngle >= HEAD_TURN_ANGLE_THRESHOLD) {
                this.consecutiveHeadTurnFrames = (this.consecutiveHeadTurnFrames || 0) + 1;

                // Require 2 consecutive frames (~360ms) to ensure deliberate head turn and prevent sensor flutter
                if (this.consecutiveHeadTurnFrames >= 2) {
                    this.triggerEvent("HEAD_TURN", 0.85);

                    // On-screen proctoring status
                    this.ctx.fillStyle = "rgba(239, 68, 68, 0.9)";
                    this.ctx.font = "bold 13px sans-serif";
                    this.ctx.fillText("⚠️ HEAD TURNED", 10, 45);
                }
            } else {
                this.consecutiveHeadTurnFrames = 0;
            }
        }
        
        // Draw face points locally as user visual feedback
        this.drawFaceMesh(landmarks);
    }

    static drawFaceMesh(landmarks) {
        this.ctx.fillStyle = "rgba(16, 185, 129, 0.45)";
        landmarks.forEach(pt => {
            const x = pt.x * this.canvas.width;
            const y = pt.y * this.canvas.height;
            this.ctx.beginPath();
            this.ctx.arc(x, y, 1.5, 0, 2 * Math.PI);
            this.ctx.fill();
        });
    }

    static async triggerEvent(eventType, confidence) {
        if (!this.running) return;
        const now = Date.now();
        
        // Rapid response cooldown:
        // Mobile phone & multi-person: 3.5 seconds cooldown
        // Head turn & absence: 4.5 seconds cooldown
        const cooldownMs = (eventType === "PHONE_DETECTED" || eventType === "MULTIPLE_PERSON") ? 3500 : 4500;
        if (this.lastEventTimes[eventType] && (now - this.lastEventTimes[eventType]) < cooldownMs) {
            return;
        }
        
        this.lastEventTimes[eventType] = now;
        
        // Submit event
        const res = await API.post("/proctor/events", {
            attempt_id: this.attemptId,
            session_token: this.token,
            event_type: eventType,
            confidence: confidence
        });

        if (res.success) {
            // TEMPORARY OVERRIDE FOR TOMORROW'S EXAM: Set to false to re-enable
            const DISABLE_EXAM_TERMINATION = true;
            if (res.action === "TERMINATE" && !DISABLE_EXAM_TERMINATION) {
                this.onTerminate(res.message);
            } else if (res.action === "WARNING" || res.action === "TERMINATE") {
                this.onWarning(res.message, res.violation_log_id);
                // Capture frame and upload as evidence
                this.captureAndUploadEvidence(eventType, res.violation_log_id);
            }
        }
    }

    static captureAndUploadEvidence(eventType, logId) {
        // Use an offscreen canvas to avoid flickering the live display canvas
        const offscreen = document.createElement("canvas");
        offscreen.width = this.video.videoWidth || 640;
        offscreen.height = this.video.videoHeight || 480;
        const oCtx = offscreen.getContext("2d");
        oCtx.drawImage(this.video, 0, 0, offscreen.width, offscreen.height);
        
        offscreen.toBlob(async (blob) => {
            if (!blob) return;
            const formData = new FormData();
            formData.append("file", blob, "screenshot.jpg");
            formData.append("attempt_id", this.attemptId);
            formData.append("session_token", this.token);
            formData.append("event_type", eventType);
            if (logId) {
                formData.append("violation_log_id", logId);
            }
            
            await API.upload("/proctor/evidence", formData);
        }, "image/jpeg", 0.75);
    }

    static basicCameraAuditLoop() {
        if (!this.running) return;
        
        // In case MediaPipe fails, run basic periodic audits checking if stream stops
        if (mediaStream && !mediaStream.getVideoTracks()[0].enabled) {
            this.triggerEvent("CAMERA_FAILURE", 1.0);
        }
        
        setTimeout(() => this.basicCameraAuditLoop(), 3000);
    }
}

// --- NOTIFICATION DROPDOWN SYSTEM ---
let notificationsCache = [];

async function initNotificationSystem() {
    if (!isAdminPage || !currentToken) return;

    // Inject Notification dropdown styling
    const style = document.createElement("style");
    style.innerHTML = `
        .notif-item {
            padding: 0.75rem;
            border-radius: 6px;
            background: rgba(255,255,255,0.03);
            border: 1px solid var(--border-glass);
            cursor: pointer;
            transition: all 0.2s;
            text-align: left;
            text-decoration: none;
            display: block;
        }
        .notif-item:hover {
            background: rgba(16, 185, 129, 0.05);
            border-color: var(--accent-primary);
        }
        .notif-title {
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--text-primary);
            margin-bottom: 0.25rem;
        }
        .notif-desc {
            font-size: 0.8rem;
            color: var(--text-secondary);
            line-height: 1.3;
        }
    `;
    document.head.appendChild(style);

    // Check if notif-btn and notif-dropdown already exist in the HTML
    let notifBtn = document.getElementById("notif-btn");
    let notifDropdown = document.getElementById("notif-dropdown");

    if (!notifBtn || !notifDropdown) {
        // Locate modern top actions container or legacy nav links
        const topActions = document.querySelector(".admin-top-actions") || document.querySelector(".nav-links");
        if (!topActions) return;

        // Check if there is a placeholder bell div in topActions
        const existingBell = topActions.querySelector('div[title="Notifications"]') || Array.from(topActions.children).find(el => el.innerText && el.innerText.includes("🔔"));

        // Create dropdown wrapper element
        const notifDropdownWrapper = document.createElement("div");
        notifDropdownWrapper.className = "notification-bell-wrapper";
        notifDropdownWrapper.innerHTML = `
            <div id="notif-btn" class="notification-bell-btn" onclick="toggleNotifDropdown(event)" title="Notifications">
                🔔<span id="notif-badge" class="notification-badge" style="display: none;">0</span>
            </div>
            <div id="notif-dropdown" class="notification-dropdown" style="display: none;">
                <div class="notification-dropdown-header">
                    <h4><span>🔔</span> Notifications</h4>
                    <a href="#" onclick="markAllNotifsAsRead(event)" style="font-size: 0.75rem; color: var(--primary-green); text-decoration: none; font-weight: 700;">Mark All as Read</a>
                </div>
                <div id="notif-list" class="notification-list">
                    <p style="color: var(--text-secondary); font-size: 0.8rem; text-align: center; margin: 1.5rem 0;">Loading notifications...</p>
                </div>
            </div>
        `;

        if (existingBell) {
            existingBell.replaceWith(notifDropdownWrapper);
        } else {
            const avatar = topActions.querySelector(".admin-avatar");
            if (avatar) {
                topActions.insertBefore(notifDropdownWrapper, avatar);
            } else {
                topActions.appendChild(notifDropdownWrapper);
            }
        }
    }

    // Close dropdown on click outside
    document.addEventListener("click", function(e) {
        const dropdown = document.getElementById("notif-dropdown");
        const btn = document.getElementById("notif-btn");
        if (dropdown && btn && !dropdown.contains(e.target) && !btn.contains(e.target)) {
            dropdown.style.display = "none";
        }
    });

    // Load initial notifications feed
    await loadNotifications();
    
    // Automatically check for new notifications every 10 seconds
    setInterval(loadNotifications, 10000);
}

function toggleNotifDropdown(e) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    const dropdown = document.getElementById("notif-dropdown");
    if (dropdown) {
        const isHidden = dropdown.style.display === "none" || !dropdown.style.display;
        dropdown.style.display = isHidden ? "flex" : "none";
        if (isHidden) {
            loadNotifications();
        }
    }
}

async function loadNotifications() {
    const res = await API.get("/admin/notifications");
    if (res.success) {
        notificationsCache = res.notifications || [];
        
        // Retrieve read list from localStorage
        const readList = JSON.parse(localStorage.getItem("read_notifications") || "[]");
        
        // Filter out read notifications
        const unreadList = notificationsCache.filter(n => !readList.includes(n.id));
        
        // Update badge indicator
        const badge = document.getElementById("notif-badge");
        if (badge) {
            if (unreadList.length > 0) {
                badge.innerText = unreadList.length;
                badge.style.display = "flex";
            } else {
                badge.style.display = "none";
            }
        }
        
        // Populate list
        const notifListContainer = document.getElementById("notif-list");
        if (notifListContainer) {
            if (unreadList.length > 0) {
                notifListContainer.innerHTML = unreadList.map(n => {
                    let icon = "🔔";
                    if (n.type === "registration") icon = "🎓";
                    else if (n.type === "access") icon = "🔑";
                    else if (n.type === "password_reset") icon = "🔒";

                    return `
                        <div class="notification-item" onclick="window.location.href='${n.link}'">
                            <div class="notification-item-icon">${icon}</div>
                            <div class="notification-item-content">
                                <div class="notification-item-title">${escapeHtml(n.title)}</div>
                                <div class="notification-item-msg">${escapeHtml(n.message)}</div>
                                <div style="display: flex; gap: 0.4rem; margin-top: 0.35rem;">
                                    <button class="btn btn-primary" onclick="handleNotifAction(event, '${n.type}', ${n.raw_id}, 'approve')" style="padding: 0.22rem 0.6rem; font-size: 0.72rem; font-weight: 700; line-height: 1.2;">Approve</button>
                                    <button class="btn btn-danger" onclick="handleNotifAction(event, '${n.type}', ${n.raw_id}, 'reject')" style="padding: 0.22rem 0.6rem; font-size: 0.72rem; font-weight: 700; line-height: 1.2;">Reject</button>
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
            } else {
                notifListContainer.innerHTML = `<div style="text-align: center; padding: 2rem 1rem; color: var(--text-secondary);"><div style="font-size: 2rem; margin-bottom: 0.35rem;">🎉</div><strong style="display: block; font-size: 0.9rem; color: var(--forest-dark);">All caught up!</strong><span style="font-size: 0.78rem;">No pending notifications.</span></div>`;
            }
        }
    }
}

async function handleNotifAction(event, type, rawId, action) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    
    let endpoint = "";
    if (type === "registration") {
        endpoint = `/admin/registrations/${rawId}/${action}`;
    } else if (type === "access") {
        endpoint = `/admin/access/${rawId}/${action}`;
    } else if (type === "password_reset") {
        endpoint = `/admin/password-resets/${rawId}/${action}`;
    }
    
    if (!endpoint) return;
    
    // Confirm rejection
    if (action === "reject") {
        let confirmMsg = "Are you sure you want to reject this request?";
        if (type === "registration") confirmMsg = "Are you sure you want to reject this student registration?";
        else if (type === "access") confirmMsg = "Are you sure you want to reject this exam access request?";
        else if (type === "password_reset") confirmMsg = "Are you sure you want to reject this password reset request?";
        if (!confirm(confirmMsg)) return;
    }
    
    const res = await API.post(endpoint, {});
    if (res.success) {
        alert(res.message || `Successfully completed action.`);
        // Reload notifications
        await loadNotifications();
        
        // Also reload the page-level reports if we are currently on registrations/results page to keep tables synced!
        if (window.location.pathname.includes("registrations.html")) {
            if (typeof loadRegistrations === "function") loadRegistrations();
        } else if (window.location.pathname.includes("results.html")) {
            const selector = document.getElementById("exam-selector");
            if (selector && typeof loadReports === "function") loadReports(selector.value);
        }
    } else {
        alert(res.message || `Failed to perform action.`);
    }
}

function markAllNotifsAsRead(e) {
    e.preventDefault();
    const readList = JSON.parse(localStorage.getItem("read_notifications") || "[]");
    
    // Add all current notification IDs to read list
    notificationsCache.forEach(n => {
        if (!readList.includes(n.id)) {
            readList.push(n.id);
        }
    });
    
    localStorage.setItem("read_notifications", JSON.stringify(readList));
    
    // Refresh view
    const badge = document.getElementById("notif-badge");
    if (badge) badge.style.display = "none";
    
    const notifListContainer = document.getElementById("notif-list");
    if (notifListContainer) {
        notifListContainer.innerHTML = `<p style="color: var(--text-secondary); font-size: 0.8rem; text-align: center; margin: 1rem 0;">No new notifications</p>`;
    }
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\'": "&#39;", '"': "&quot;"
    }[character]));
}

// Auto-run notification system on document load
document.addEventListener("DOMContentLoaded", initNotificationSystem);
// If page is already loaded, run immediately
if (document.readyState === "complete" || document.readyState === "interactive") {
    initNotificationSystem();
}
