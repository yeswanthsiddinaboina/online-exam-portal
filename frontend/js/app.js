const API_BASE = "http://127.0.0.1:5001/api";

// Session helper variables
const isAdminPage = window.location.pathname.includes("/admin/");
const tokenKey = isAdminPage ? "admin_token" : "token";
const userKey = isAdminPage ? "admin_user" : "user";

let currentToken = localStorage.getItem(tokenKey) || null;
let currentUser = JSON.parse(localStorage.getItem(userKey)) || null;
let currentAttemptId = localStorage.getItem("attempt_id") || null;
let currentSessionToken = localStorage.getItem("session_token") || null;
let heartbeatTimer = null;
let examTimer = null;
let mediaStream = null;

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

// Redirects helper
function checkAuth(requiredRole = null) {
    if (!currentToken) {
        const dest = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `/login.html?redirect=${dest}`;
        return;
    }
    if (requiredRole && currentUser && currentUser.role !== requiredRole) {
        if (currentUser.role === "admin") {
            window.location.href = "/admin/dashboard.html";
        } else {
            window.location.href = "/dashboard.html";
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
                window.location.href = `/login.html?redirect=${dest}`;
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
                window.location.href = `/login.html?redirect=${dest}`;
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
                window.location.href = `/login.html?redirect=${dest}`;
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
                window.location.href = `/login.html?redirect=${dest}`;
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
    const res = await API.post("/auth/login", { email, password, username, student_id });
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
            window.location.href = decodeURIComponent(redirectUrl);
        } else {
            if (res.role === "admin") {
                window.location.href = "/admin/dashboard.html";
            } else {
                window.location.href = "/dashboard.html";
            }
        }
    } else {
        alert(res.message || "Login failed");
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
        window.location.href = "/login.html";
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

// --- BROWSER LOCKDOWN ENFORCER ---
class SandboxEnforcer {
    static init(attemptId, token, onWarning, onTerminate) {
        this.attemptId = attemptId;
        this.token = token;
        this.onWarning = onWarning;
        this.onTerminate = onTerminate;
        this.lastTabSwitchTime = 0;
        
        // Bind visibility API change
        document.addEventListener("visibilitychange", this.handleVisibilityChange.bind(this));
        
        // Bind blur / focus
        window.addEventListener("blur", this.handleWindowBlur.bind(this));
        
        // Bind Fullscreen state listener
        document.addEventListener("fullscreenchange", this.handleFullscreenChange.bind(this));
        
        // Block browser shortcut commands
        window.addEventListener("keydown", this.blockShortcuts.bind(this));
        
        // Block right-clicks context menu
        document.addEventListener("contextmenu", this.blockContextMenu.bind(this));
    }

    static destroy() {
        document.removeEventListener("visibilitychange", this.handleVisibilityChange);
        window.removeEventListener("blur", this.handleWindowBlur);
        document.removeEventListener("fullscreenchange", this.handleFullscreenChange);
        window.removeEventListener("keydown", this.blockShortcuts);
        document.removeEventListener("contextmenu", this.blockContextMenu);
    }

    static handleVisibilityChange() {
        if (document.visibilityState === "hidden") {
            this.reportTabSwitch();
        }
    }

    static handleWindowBlur() {
        this.reportTabSwitch();
    }

    static reportTabSwitch() {
        const now = Date.now();
        if (now - this.lastTabSwitchTime > 2000) { // 2 seconds debounce
            this.lastTabSwitchTime = now;
            this.reportInfrac("TAB_SWITCH");
        }
    }

    static handleFullscreenChange() {
        if (!document.fullscreenElement) {
            this.reportInfrac("FULLSCREEN_EXIT");
        }
    }

    static blockShortcuts(e) {
        // Block Escape, F5, Ctrl+R, F12, Alt+Tab, print shortcuts
        const blockedKeys = ["F5", "F12"];
        if (blockedKeys.includes(e.key) || (e.ctrlKey && ["r", "c", "v", "p"].includes(e.key.toLowerCase()))) {
            e.preventDefault();
            e.stopPropagation();
            return false;
        }
    }

    static blockContextMenu(e) {
        e.preventDefault();
        return false;
    }

    static async reportInfrac(eventType) {
        const res = await API.post("/proctor/events", {
            attempt_id: this.attemptId,
            session_token: this.token,
            event_type: eventType,
            confidence: 1.0
        });
        
        if (res.success) {
            if (res.action === "TERMINATE") {
                this.onTerminate(res.message);
            } else if (res.action === "WARNING") {
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
        
        // Frame sampling configs (run inference at 2 FPS to prevent processor load)
        this.sampleInterval = 500; 
        
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
        this.showDebug("Starting proctoring session...");
        
        if (typeof tf !== "undefined") {
            this.showDebug("TensorFlow.js loaded. Backend: " + tf.getBackend());
        } else {
            this.showDebug("TensorFlow.js NOT loaded in script context!");
        }

        // Load COCO-SSD object detection model for mobile phones if available
        if (typeof cocoSsd !== "undefined") {
            this.showDebug("Loading COCO-SSD model...");
            cocoSsd.load().then(model => {
                this.cocoModel = model;
                this.showDebug("COCO-SSD model loaded successfully.");
                const statusEl = document.getElementById("detection-model-status");
                if (statusEl) {
                    statusEl.innerText = "📱 Detector: Ready";
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
        
        // Load MediaPipe FaceMesh via script context if available
        if (typeof FaceMesh !== "undefined") {
            this.showDebug("Loading MediaPipe FaceMesh...");
            this.faceMesh = new FaceMesh({
                locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`
            });

            this.faceMesh.setOptions({
                maxNumFaces: 2,
                refineLandmarks: true,
                minDetectionConfidence: 0.5,
                minTrackingConfidence: 0.5
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
        
        try {
            // Run MediaPipe FaceMesh
            await this.faceMesh.send({ image: this.video });
            
            // Run COCO-SSD Object Detection for mobile phones
            if (this.cocoModel) {
                const predictions = await this.cocoModel.detect(this.video);
                
                // Show raw prediction classes in logs so candidate sees what model is seeing
                const visiblePredictions = predictions.filter(p => p.score >= 0.25);
                this.latestPredictions = visiblePredictions;
                
                if (visiblePredictions.length > 0) {
                    const detectedClasses = visiblePredictions.map(p => `${p.class} (${(p.score*100).toFixed(0)}%)`).join(", ");
                    this.showDebug("Seen: " + detectedClasses);
                }
                
                const illegalClasses = ["cell phone", "laptop", "remote"];
                const violation = visiblePredictions.find(p => illegalClasses.includes(p.class) && p.score >= 0.35); // Lowered threshold to 0.35
                if (violation) {
                    this.showDebug(`⚠️ Malpractice alert: ${violation.class} detected (${(violation.score*100).toFixed(0)}%)`);
                    this.triggerEvent("PHONE_DETECTED", violation.score);
                }
            }
        } catch (e) {
            this.showDebug("Inference error: " + e.message);
            console.error("MediaPipe/COCO-SSD Inference error:", e);
        }
        
        setTimeout(() => this.inferenceLoop(), this.sampleInterval);
    }

    static onResults(results) {
        // Sync canvas size to match video dimensions exactly
        if (this.canvas.width !== this.video.videoWidth || this.canvas.height !== this.video.videoHeight) {
            this.canvas.width = this.video.videoWidth || 400;
            this.canvas.height = this.video.videoHeight || 300;
        }

        // Clear overlay
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // Draw object detection bounding boxes first so they render even if face is absent
        if (this.latestPredictions && this.latestPredictions.length > 0) {
            this.latestPredictions.forEach(pred => {
                const [x, y, width, height] = pred.bbox;
                const isIllegal = ["cell phone", "laptop", "remote"].includes(pred.class);
                
                this.ctx.strokeStyle = isIllegal ? "#ef4444" : "#10b981";
                this.ctx.lineWidth = 2;
                this.ctx.strokeRect(x, y, width, height);
                
                this.ctx.fillStyle = isIllegal ? "#ef4444" : "#10b981";
                this.ctx.font = "12px sans-serif";
                const label = `${pred.class} (${(pred.score * 100).toFixed(0)}%)`;
                this.ctx.fillText(label, x, y > 15 ? y - 5 : y + 15);
            });
        }

        const faces = results.multiFaceLandmarks || [];
        
        // 1. Absence check
        if (faces.length === 0) {
            this.triggerEvent("FACE_ABSENT", 1.0);
            return;
        }

        // 2. Multiple person check
        if (faces.length > 1) {
            this.triggerEvent("MULTIPLE_PERSON", 1.0);
            return;
        }

        // 3. Head pose / Gaze tracking estimation
        // Landmarks: 4 (Nose Tip), 33 (Left Eye boundary), 263 (Right Eye boundary), 152 (Chin), 10 (Forehead)
        const landmarks = faces[0];
        const nose = landmarks[4];
        const leftEye = landmarks[33];
        const rightEye = landmarks[263];

        // Horizontal ratio: position of nose relative to eyes
        const eyeDistance = rightEye.x - leftEye.x;
        if (eyeDistance > 0) {
            const noseRelX = (nose.x - leftEye.x) / eyeDistance;
            
            // Looking too far right (ratio < 0.35) or too far left (ratio > 0.65)
            if (noseRelX < 0.35) {
                this.triggerEvent("HEAD_TURN", 0.85);
            } else if (noseRelX > 0.65) {
                this.triggerEvent("HEAD_TURN", 0.85);
            }
        }
        
        // Draw face points locally as user visual feedback
        this.drawFaceMesh(landmarks);
    }

    static drawFaceMesh(landmarks) {
        this.ctx.fillStyle = "rgba(99, 102, 241, 0.4)";
        landmarks.forEach(pt => {
            const x = pt.x * this.canvas.width;
            const y = pt.y * this.canvas.height;
            this.ctx.beginPath();
            this.ctx.arc(x, y, 1.5, 0, 2 * Math.PI);
            this.ctx.fill();
        });
    }

    static async triggerEvent(eventType, confidence) {
        const now = Date.now();
        // Cooldown in client to prevent spam (cooldown matches 10s server rule)
        if (this.lastEventTimes[eventType] && (now - this.lastEventTimes[eventType]) < 10000) {
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
            if (res.action === "TERMINATE") {
                this.onTerminate(res.message);
            } else if (res.action === "WARNING") {
                this.onWarning(res.message, res.violation_log_id);
                // Capture frame and upload as evidence
                this.captureAndUploadEvidence(eventType, res.violation_log_id);
            }
        }
    }

    static captureAndUploadEvidence(eventType, logId) {
        this.canvas.width = this.video.videoWidth;
        this.canvas.height = this.video.videoHeight;
        
        // Draw frame onto canvas
        const tempCtx = this.canvas.getContext("2d");
        tempCtx.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);
        
        // Convert to Blob
        this.canvas.toBlob(async (blob) => {
            const formData = new FormData();
            formData.append("file", blob, "screenshot.jpg");
            formData.append("attempt_id", this.attemptId);
            formData.append("session_token", this.token);
            formData.append("event_type", eventType);
            if (logId) {
                formData.append("violation_log_id", logId);
            }
            
            await API.upload("/proctor/evidence", formData);
        }, "image/jpeg", 0.7);
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

    // Locate nav links container
    const navLinks = document.querySelector(".nav-links");
    if (!navLinks) return;

    // Create dropdown wrapper element
    const notifDropdownWrapper = document.createElement("div");
    notifDropdownWrapper.className = "nav-item-dropdown";
    notifDropdownWrapper.style.position = "relative";
    notifDropdownWrapper.style.display = "inline-block";
    notifDropdownWrapper.innerHTML = `
        <a href="#" class="nav-link" id="notif-btn" onclick="toggleNotifDropdown(event)" style="position: relative; padding: 0.25rem 0.5rem; font-size: 1.15rem;">
            🔔<span id="notif-badge" style="display: none; position: absolute; top: -3px; right: -5px; background: var(--accent-danger); color: white; border-radius: 50%; width: 16px; height: 16px; font-size: 0.65rem; font-weight: bold; display: flex; align-items: center; justify-content: center; border: 1.5px solid white;">0</span>
        </a>
        <div id="notif-dropdown" class="glass-panel" style="display: none; position: absolute; right: 0; top: 35px; width: 320px; max-height: 400px; overflow-y: auto; z-index: 1000; padding: 1rem; border-color: var(--accent-primary); box-shadow: 0 8px 32px rgba(16,185,129,0.15);">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-glass); padding-bottom: 0.5rem; margin-bottom: 0.75rem;">
                <strong style="font-size: 0.9rem; color: var(--text-primary);">Notifications</strong>
                <a href="#" onclick="markAllNotifsAsRead(event)" style="font-size: 0.75rem; color: var(--accent-primary); text-decoration: none; font-weight: 600;">Mark All as Read</a>
            </div>
            <div id="notif-list" style="display: flex; flex-direction: column; gap: 0.75rem;">
                <p style="color: var(--text-secondary); font-size: 0.8rem; text-align: center; margin: 1rem 0;">No new notifications</p>
            </div>
        </div>
    `;

    // Insert notification button before Sign Out link in the navbar
    const signOutBtn = navLinks.querySelector("a[onclick='handleLogout()']");
    if (signOutBtn) {
        navLinks.insertBefore(notifDropdownWrapper, signOutBtn);
    } else {
        navLinks.appendChild(notifDropdownWrapper);
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
    
    // Automatically check for new notifications every 5 seconds without refreshing
    setInterval(loadNotifications, 5000);
}

function toggleNotifDropdown(e) {
    e.preventDefault();
    const dropdown = document.getElementById("notif-dropdown");
    if (dropdown) {
        dropdown.style.display = dropdown.style.display === "none" ? "block" : "none";
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
                notifListContainer.innerHTML = unreadList.map(n => `
                    <div class="notif-item" style="cursor: pointer; position: relative; border-bottom: 1px solid var(--border-glass); padding: 0.75rem;" onclick="window.location.href='${n.link}'">
                        <div class="notif-title">${n.title}</div>
                        <div class="notif-desc">${n.message}</div>
                        <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                            <button class="btn btn-primary" onclick="handleNotifAction(event, '${n.type}', ${n.raw_id}, 'approve')" style="padding: 0.2rem 0.5rem; font-size: 0.7rem; background: var(--accent-success); border-color: transparent; font-weight: 600; line-height: 1.2;">Approve</button>
                            <button class="btn btn-danger" onclick="handleNotifAction(event, '${n.type}', ${n.raw_id}, 'reject')" style="padding: 0.2rem 0.5rem; font-size: 0.7rem; font-weight: 600; line-height: 1.2;">Reject</button>
                        </div>
                    </div>
                `).join('');
            } else {
                notifListContainer.innerHTML = `<p style="color: var(--text-secondary); font-size: 0.8rem; text-align: center; margin: 1rem 0;">No new notifications</p>`;
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
    }
    
    if (!endpoint) return;
    
    // Confirm rejection
    if (action === "reject") {
        const confirmMsg = type === "registration" 
            ? "Are you sure you want to reject this student registration?"
            : "Are you sure you want to reject this exam access request?";
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

// Auto-run notification system on document load
document.addEventListener("DOMContentLoaded", initNotificationSystem);
// If page is already loaded, run immediately
if (document.readyState === "complete" || document.readyState === "interactive") {
    initNotificationSystem();
}
