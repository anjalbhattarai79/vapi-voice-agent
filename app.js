// ===== VAPI SDK (ES module import) =====
import VapiModule from "https://cdn.jsdelivr.net/npm/@vapi-ai/web@2.5.2/+esm";
import { VAPI_PUBLIC_KEY, ASSISTANT_ID } from "./config.js";

// Handle both default export shapes: { default: class } or class directly
const Vapi = VapiModule?.default ?? VapiModule;

// ===== DOM Elements =====
const micButton = document.getElementById("micButton");
const micIcon = document.getElementById("micIcon");
const stopIcon = document.getElementById("stopIcon");
const statusBadge = document.getElementById("statusBadge");
const statusText = statusBadge.querySelector(".status-text");
const transcriptPlaceholder = document.getElementById("transcriptPlaceholder");
const transcriptMessages = document.getElementById("transcriptMessages");
const micHint = document.getElementById("micHint");
const dotCanvas = document.getElementById("dotCanvas");
const ctx = dotCanvas.getContext("2d");

// ===== State =====
let isCallActive = false;
let currentUserMsg = null;
let currentAiMsg = null;

// ===== Dot Visualizer State =====
const DOT_COUNT = 24;
const BASE_RADIUS = 80;       // Circle radius for dots
const BASE_DOT_SIZE = 3;      // Dot size at rest
const MAX_DOT_GROW = 7;       // Extra size at full volume
let currentVolume = 0;
let targetVolume = 0;
let dotPhase = 0;
let animFrameId = null;

// ===== Initialize VAPI =====
let vapi;
try {
  vapi = new Vapi(VAPI_PUBLIC_KEY);
  console.log("[Sama] VAPI SDK initialized successfully");
} catch (err) {
  console.error("[Sama] Failed to initialize VAPI SDK:", err);
  console.log("[Sama] VapiModule:", VapiModule);
  console.log("[Sama] Vapi:", Vapi);
}

// ===== Helpers =====
function setStatus(state, text) {
  statusBadge.className = "status-badge " + state;
  statusText.textContent = text;
}

function showTranscript() {
  transcriptPlaceholder.style.display = "none";
  transcriptMessages.classList.add("visible");
}

function addMessage(role, text, isPartial = false) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  if (isPartial) div.classList.add("active");

  const label = document.createElement("span");
  label.className = "label";
  label.textContent = role === "user" ? "You" : "Assistant";

  const content = document.createElement("span");
  content.className = "content";
  content.textContent = text;

  div.appendChild(label);
  div.appendChild(content);
  transcriptMessages.appendChild(div);
  transcriptMessages.scrollTop = transcriptMessages.scrollHeight;

  return div;
}

function updateMessage(el, text, finalize = false) {
  if (!el) return;
  const content = el.querySelector(".content");
  if (content) content.textContent = text;
  if (finalize) el.classList.remove("active");
  transcriptMessages.scrollTop = transcriptMessages.scrollHeight;
}

// ===== Mic Button Click =====
micButton.addEventListener("click", async () => {
  if (!vapi) {
    setStatus("error", "SDK Error");
    micHint.textContent = "VAPI SDK failed to load. Check console.";
    return;
  }

  if (isCallActive) {
    // Stop call
    vapi.stop();
  } else {
    // Start call
    try {
      setStatus("connecting", "Connecting…");
      micHint.textContent = "Connecting…";
      console.log("[Sama] Starting VAPI call with assistant:", ASSISTANT_ID);
      const callResult = await vapi.start(ASSISTANT_ID);
      console.log("[Sama] Call started:", callResult);
    } catch (err) {
      console.error("[Sama] VAPI start error:", err);
      setStatus("error", "Error");
      micHint.textContent = "Failed to connect. Try again.";
    }
  }
});

// ===== VAPI Event Listeners =====

vapi.on("call-start", () => {
  isCallActive = true;
  document.body.classList.add("active");

  micIcon.classList.add("hidden");
  stopIcon.classList.remove("hidden");

  setStatus("connected", "Connected");
  micHint.textContent = "Listening… Tap to end";
  showTranscript();
});

vapi.on("call-end", () => {
  isCallActive = false;
  document.body.classList.remove("active", "speaking");

  micIcon.classList.remove("hidden");
  stopIcon.classList.add("hidden");

  setStatus("", "Ready");
  micHint.textContent = "Click to start";

  // Finalize any open messages
  if (currentUserMsg) {
    currentUserMsg.classList.remove("active");
    currentUserMsg = null;
  }
  if (currentAiMsg) {
    currentAiMsg.classList.remove("active");
    currentAiMsg = null;
  }
});

vapi.on("speech-start", () => {
  document.body.classList.add("speaking");
});

vapi.on("speech-end", () => {
  document.body.classList.remove("speaking");
});

vapi.on("message", (msg) => {
  // Handle transcription messages
  if (msg.type === "transcript") {
    const role = msg.role; // "user" or "assistant"
    const text = msg.transcript;
    const isFinal = msg.transcriptType === "final";

    if (role === "user") {
      if (!currentUserMsg) {
        currentUserMsg = addMessage("user", text, true);
      } else {
        updateMessage(currentUserMsg, text);
      }

      if (isFinal) {
        updateMessage(currentUserMsg, text, true);
        currentUserMsg = null;
      }
    }

    if (role === "assistant") {
      if (!currentAiMsg) {
        currentAiMsg = addMessage("assistant", text, true);
      } else {
        updateMessage(currentAiMsg, text);
      }

      if (isFinal) {
        updateMessage(currentAiMsg, text, true);
        currentAiMsg = null;
      }
    }
  }

  // Handle conversation updates (function calls, etc.)
  if (msg.type === "conversation-update") {
    // Could add visual indicators for function calls here
  }
});

vapi.on("volume-level", (level) => {
  targetVolume = Math.min(1, level);
});

vapi.on("error", (err) => {
  console.error("VAPI error:", err);
  setStatus("error", "Error");
  micHint.textContent = "Something went wrong. Try again.";
});

// ===== Dot Circle Visualizer =====
function resizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const rect = dotCanvas.getBoundingClientRect();
  dotCanvas.width = rect.width * dpr;
  dotCanvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
}
resizeCanvas();
window.addEventListener("resize", resizeCanvas);

function drawDots(time) {
  const w = dotCanvas.getBoundingClientRect().width;
  const h = dotCanvas.getBoundingClientRect().height;
  ctx.clearRect(0, 0, w, h);

  // Smooth interpolation towards target
  currentVolume += (targetVolume - currentVolume) * 0.18;
  dotPhase += 0.025;

  const cx = w / 2;
  const cy = h / 2;
  const scale = Math.min(w, h) / 220;
  const radius = BASE_RADIUS * scale;

  // Idle breathing when call is active but volume is low
  const idleBreath = isCallActive ? (Math.sin(dotPhase * 0.8) * 0.5 + 0.5) * 0.12 : 0;
  const effectiveVol = Math.max(currentVolume, idleBreath);

  for (let i = 0; i < DOT_COUNT; i++) {
    const angle = (i / DOT_COUNT) * Math.PI * 2 - Math.PI / 2;

    // Each dot gets a unique wave offset
    const wave1 = Math.sin(dotPhase * 2 + i * 0.55) * 0.5 + 0.5;
    const wave2 = Math.sin(dotPhase * 3.3 + i * 0.9) * 0.5 + 0.5;
    const wave = (wave1 + wave2) / 2;

    // Volume drives the amplitude
    const vol = effectiveVol;
    const radiusOffset = wave * vol * 18 * scale;
    const r = radius + radiusOffset;

    const dotSize = (BASE_DOT_SIZE + wave * vol * MAX_DOT_GROW) * scale;
    const opacity = 0.35 + wave * vol * 0.65;

    const x = cx + Math.cos(angle) * r;
    const y = cy + Math.sin(angle) * r;

    // Color: blend accent purple → indigo based on wave
    const red = Math.round(167 - wave * 68);   // 167 → 99
    const green = Math.round(139 - wave * 37);  // 139 → 102
    const blue = Math.round(250 - wave * 9);    // 250 → 241

    ctx.beginPath();
    ctx.arc(x, y, dotSize, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${red}, ${green}, ${blue}, ${opacity})`;
    ctx.fill();

    // Glow effect when volume is high
    if (vol > 0.15) {
      ctx.beginPath();
      ctx.arc(x, y, dotSize + 3 * vol * scale, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${red}, ${green}, ${blue}, ${opacity * 0.15})`;
      ctx.fill();
    }
  }

  // Slowly decay target if no new input
  targetVolume *= 0.92;

  animFrameId = requestAnimationFrame(drawDots);
}

// Start animation loop
animsStart();
function animsStart() {
  if (!animFrameId) animFrameId = requestAnimationFrame(drawDots);
}

function animsStop() {
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
  // Clear canvas
  const w = dotCanvas.getBoundingClientRect().width;
  const h = dotCanvas.getBoundingClientRect().height;
  ctx.clearRect(0, 0, w, h);
  currentVolume = 0;
  targetVolume = 0;
}
