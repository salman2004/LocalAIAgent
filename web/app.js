// Web UI for the local assistant. Talks to assistant_core over the same
// SSE protocol cli/tui.py uses (/chat/stream, /chat/confirm) - same
// origin, so no CORS is involved at all.

const transcript = document.getElementById("transcript");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const hud = document.getElementById("hud");
const statusBadge = document.getElementById("status-badge");
const confirmOverlay = document.getElementById("confirm-overlay");
const confirmTitle = document.getElementById("confirm-title");
const confirmPreview = document.getElementById("confirm-preview");
const confirmApproveBtn = document.getElementById("confirm-approve");
const confirmDenyBtn = document.getElementById("confirm-deny");
const micBtn = document.getElementById("mic-btn");

let conversation = [];

function setState(state) {
  hud.dataset.state = state;
  statusBadge.dataset.state = state;
  statusBadge.textContent = state;
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function addLine(className, text) {
  const el = document.createElement("div");
  el.className = className;
  el.textContent = text;
  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;
  return el;
}

function scrollToBottom() {
  transcript.scrollTop = transcript.scrollHeight;
}

// --- confirmation modal -----------------------------------------------
// Approve/Deny only fires the POST; the actual outcome (and the
// transcript line for it) is driven by the confirm_resolved SSE event,
// not by this click - the server is the source of truth for what
// actually happened.
let pendingConfirmId = null;

function showConfirm(id, tool, preview) {
  pendingConfirmId = id;
  confirmTitle.textContent = `Allow ${tool}?`;
  confirmPreview.textContent = preview;
  confirmOverlay.classList.remove("hidden");
  confirmDenyBtn.focus();
}

function hideConfirm() {
  confirmOverlay.classList.add("hidden");
  pendingConfirmId = null;
}

async function resolveConfirm(approved) {
  if (!pendingConfirmId) return;
  const id = pendingConfirmId;
  hideConfirm();
  try {
    await fetch("/chat/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, approved }),
    });
  } catch (err) {
    addLine("msg-error", `Failed to send confirmation: ${err}`);
  }
}

confirmApproveBtn.addEventListener("click", () => resolveConfirm(true));
confirmDenyBtn.addEventListener("click", () => resolveConfirm(false));
document.addEventListener("keydown", (e) => {
  if (confirmOverlay.classList.contains("hidden")) return;
  if (e.key === "Escape") resolveConfirm(false);
  if (e.key === "y" || e.key === "Y") resolveConfirm(true);
  if (e.key === "n" || e.key === "N") resolveConfirm(false);
});

// --- SSE stream handling ------------------------------------------------

async function sendMessage(text) {
  conversation.push({ role: "user", content: text });
  addLine("msg-user", text);
  setState("thinking");

  let reasoningDetails = null;
  let reasoningText = null;
  let answerEl = null;
  let answerAcc = "";

  const collapseReasoning = () => {
    if (reasoningDetails) reasoningDetails.open = false;
  };

  try {
    const resp = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: conversation }),
    });
    if (!resp.ok || !resp.body) {
      addLine("msg-error", `Request failed: HTTP ${resp.status}`);
      setState("idle");
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sepIndex;
      while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, sepIndex).trim();
        buffer = buffer.slice(sepIndex + 2);
        if (!rawEvent.startsWith("data:")) continue;
        const payload = rawEvent.slice("data:".length).trim();
        if (!payload) continue;

        let event;
        try {
          event = JSON.parse(payload);
        } catch {
          continue;
        }

        switch (event.type) {
          case "thinking": {
            if (!reasoningDetails) {
              reasoningDetails = document.createElement("details");
              reasoningDetails.className = "reasoning";
              reasoningDetails.open = true;
              const summary = document.createElement("summary");
              summary.textContent = "thinking";
              reasoningText = document.createElement("div");
              reasoningDetails.appendChild(summary);
              reasoningDetails.appendChild(reasoningText);
              transcript.appendChild(reasoningDetails);
            }
            reasoningText.textContent += event.content;
            scrollToBottom();
            break;
          }
          case "delta": {
            if (!answerEl) {
              answerEl = document.createElement("div");
              answerEl.className = "msg-assistant";
              transcript.appendChild(answerEl);
            }
            answerAcc += event.content;
            answerEl.textContent = answerAcc;
            scrollToBottom();
            break;
          }
          case "tool_start": {
            setState("thinking");
            statusBadge.textContent = `using ${event.name}...`;
            addLine("tool-line", `${event.name}...`);
            break;
          }
          case "tool_end": {
            setState("thinking");
            break;
          }
          case "confirm_request": {
            setState("listening");
            statusBadge.textContent = "waiting for your approval...";
            showConfirm(event.id, event.tool, event.preview);
            break;
          }
          case "confirm_resolved": {
            addLine("tool-line", `${event.approved ? "approved" : "denied"}: ${event.tool ?? ""}`.trim());
            setState("thinking");
            break;
          }
          case "done": {
            conversation = event.messages;
            collapseReasoning();
            setState("idle");
            if (answerAcc.trim()) speakText(answerAcc);
            break;
          }
          case "error": {
            addLine("msg-error", event.message);
            collapseReasoning();
            setState("error");
            setTimeout(() => setState("idle"), 1500);
            break;
          }
        }
      }
    }
  } catch (err) {
    addLine("msg-error", `Connection error: ${err}`);
    setState("error");
    setTimeout(() => setState("idle"), 1500);
  }
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendMessage(text);
});

// --- voice: mic input ---------------------------------------------------

let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;
// When the mic is released after using a Bluetooth headset, Windows/Android
// often takes a moment to switch it back from the low-quality call profile
// (HFP/HSP, used to carry the mic) to the high-quality one (A2DP, output
// only) - if TTS starts playing before that switch finishes, it comes out
// distorted. This tracks when the mic was last released so speakText() can
// wait out the rest of a minimum gap before playing, without ever delaying
// playback when the mic wasn't used at all (typed messages).
let lastMicReleaseTime = null;
const BLUETOOTH_PROFILE_SWITCH_DELAY_MS = 1200;

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    recordedChunks = [];
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) recordedChunks.push(e.data);
    };
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      lastMicReleaseTime = Date.now();
      const blob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || "audio/webm" });
      await transcribeAndSend(blob);
    };
    mediaRecorder.start();
    isRecording = true;
    micBtn.classList.add("recording");
    setState("listening");
  } catch (err) {
    addLine("msg-error", `Microphone access failed: ${err}`);
  }
}

function stopRecording() {
  if (mediaRecorder && isRecording) {
    mediaRecorder.stop();
    isRecording = false;
    micBtn.classList.remove("recording");
  }
}

micBtn.addEventListener("click", () => {
  if (isRecording) stopRecording();
  else startRecording();
});

async function transcribeAndSend(blob) {
  setState("thinking");
  const form = new FormData();
  form.append("file", blob, "clip.webm");
  try {
    const resp = await fetch("/voice/transcribe", { method: "POST", body: form });
    if (!resp.ok) {
      addLine("msg-error", `Transcription failed: HTTP ${resp.status}`);
      setState("idle");
      return;
    }
    const data = await resp.json();
    const text = (data.text || "").trim();
    if (!text) {
      addLine("msg-error", "Didn't catch that - no speech detected.");
      setState("idle");
      return;
    }
    await sendMessage(text);
  } catch (err) {
    addLine("msg-error", `Transcription failed: ${err}`);
    setState("idle");
  }
}

// --- voice: playback, HUD reacts to real audio amplitude ----------------

let audioCtx = null;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function speakText(text) {
  try {
    const resp = await fetch("/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!resp.ok) return;
    const arrayBuf = await resp.arrayBuffer();

    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const audioBuffer = await audioCtx.decodeAudioData(arrayBuf);

    // Give a Bluetooth headset time to switch back from its low-quality
    // call profile (used while the mic was open) to its high-quality
    // output-only one, so this doesn't come out distorted. Only waits the
    // remainder of the gap - the transcribe+chat round trip already ate
    // into it, and this is skipped entirely if the mic was never used.
    if (lastMicReleaseTime !== null) {
      const elapsed = Date.now() - lastMicReleaseTime;
      const remaining = BLUETOOTH_PROFILE_SWITCH_DELAY_MS - elapsed;
      if (remaining > 0) await sleep(remaining);
    }

    const source = audioCtx.createBufferSource();
    source.buffer = audioBuffer;
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    source.connect(analyser);
    analyser.connect(audioCtx.destination);

    setState("speaking");
    source.start();

    const tick = () => {
      if (hud.dataset.state !== "speaking") return;
      analyser.getByteFrequencyData(dataArray);
      const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
      hud.style.setProperty("--ring-glow", Math.min(1, avg / 100).toFixed(3));
      requestAnimationFrame(tick);
    };
    tick();

    source.onended = () => {
      hud.style.setProperty("--ring-glow", "0");
      setState("idle");
    };
  } catch (err) {
    // Voice playback failing shouldn't break the text chat.
    console.error("speak failed", err);
  }
}

setState("idle");
