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
const clockValue = document.getElementById("clock-value");
const dateValue = document.getElementById("date-value");
const activityLog = document.getElementById("activity-log");
const inputLevel = document.getElementById("input-level");

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

// --- barge-in: interrupt playback/generation the moment the user starts
// talking again, instead of forcing them to wait out the current reply
// (the pattern real voice-assistant pipelines like Pipecat call barge-in).

let currentChatAbortController = null;

function interruptSpeechAndChat() {
  if (ttsAudioEl && !ttsAudioEl.paused) {
    ttsAudioEl.pause();
    setState("idle");
  }
  if (currentChatAbortController) {
    currentChatAbortController.abort();
    currentChatAbortController = null;
  }
}

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

  const abortController = new AbortController();
  currentChatAbortController = abortController;

  try {
    const resp = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: conversation }),
      signal: abortController.signal,
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
            logActivity(event.name);
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
    // A deliberate barge-in (user pressed mic mid-reply) aborts this
    // fetch on purpose - that's not a real error, so don't show one.
    if (err.name !== "AbortError") {
      addLine("msg-error", `Connection error: ${err}`);
      setState("error");
      setTimeout(() => setState("idle"), 1500);
    }
  } finally {
    if (currentChatAbortController === abortController) {
      currentChatAbortController = null;
    }
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
  interruptSpeechAndChat();
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
      stopInputLevelMeter();
      const blob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || "audio/webm" });
      await transcribeAndSend(blob);
    };
    mediaRecorder.start();
    isRecording = true;
    micBtn.classList.add("recording");
    setState("listening");
    startInputLevelMeter(stream);
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

// Reads the mic's own input level while recording, purely for the level
// meter - this AudioContext graph is never connected to .destination, so
// (unlike the TTS-playback Web Audio bug from earlier) it can't affect
// what's actually heard, only what's visualized.
let inputAudioCtx = null;
let inputLevelRAF = null;
const inputLevelBars = inputLevel.querySelectorAll("span");

function startInputLevelMeter(stream) {
  if (!inputAudioCtx) inputAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const source = inputAudioCtx.createMediaStreamSource(stream);
  const analyser = inputAudioCtx.createAnalyser();
  analyser.fftSize = 64;
  const data = new Uint8Array(analyser.frequencyBinCount);
  source.connect(analyser);

  inputLevel.classList.add("active");
  const step = Math.floor(data.length / inputLevelBars.length);

  const tick = () => {
    analyser.getByteFrequencyData(data);
    inputLevelBars.forEach((bar, i) => {
      const v = data[i * step] / 255;
      bar.style.height = `${3 + v * 13}px`;
    });
    inputLevelRAF = requestAnimationFrame(tick);
  };
  tick();
}

function stopInputLevelMeter() {
  if (inputLevelRAF) cancelAnimationFrame(inputLevelRAF);
  inputLevelRAF = null;
  inputLevel.classList.remove("active");
  inputLevelBars.forEach((bar) => (bar.style.height = "3px"));
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

// --- voice: playback -----------------------------------------------------
// Deliberately NOT touching the Web Audio API (AudioContext/analyser) here
// at all - routing playback through it for a reactive HUD glow turned out
// to be the actual source of distorted audio (regular <audio>/<video>
// playback, e.g. a browser tab playing Instagram, never goes through Web
// Audio and was always clean). The HUD gets a plain animated pulse during
// speech instead of true amplitude-reactivity - a real trade of a nice-to-
// have for actually-working audio.

let ttsAudioEl = null;

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
    const blob = await resp.blob();

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

    if (ttsAudioEl) {
      ttsAudioEl.pause();
      URL.revokeObjectURL(ttsAudioEl.src);
    }
    ttsAudioEl = new Audio(URL.createObjectURL(blob));

    setState("speaking");
    await ttsAudioEl.play();

    ttsAudioEl.onended = () => {
      setState("idle");
    };
  } catch (err) {
    // Voice playback failing shouldn't break the text chat.
    console.error("speak failed", err);
  }
}

// --- HUD widgets: clock, system load, service status, activity log ------

function updateClock() {
  const now = new Date();
  clockValue.textContent = now.toLocaleTimeString([], { hour12: false });
  dateValue.textContent = now
    .toLocaleDateString([], { weekday: "short", day: "2-digit", month: "short", year: "numeric" })
    .toUpperCase();
}
updateClock();
setInterval(updateClock, 1000);

function setBar(barEl, valEl, percent) {
  if (percent === null || percent === undefined || Number.isNaN(percent)) {
    valEl.textContent = "--%";
    barEl.style.width = "0%";
    barEl.classList.remove("warn", "danger");
    return;
  }
  const pct = Math.max(0, Math.min(100, percent));
  barEl.style.width = `${pct}%`;
  valEl.textContent = `${Math.round(pct)}%`;
  barEl.classList.toggle("warn", pct >= 70 && pct < 90);
  barEl.classList.toggle("danger", pct >= 90);
}

function setServiceDot(id, up) {
  const dot = document.getElementById(id);
  if (!dot) return;
  dot.classList.toggle("up", up === true);
  dot.classList.toggle("down", up === false);
}

async function pollSystemStatus() {
  try {
    const resp = await fetch("/system/status");
    if (!resp.ok) return;
    const data = await resp.json();
    setBar(document.getElementById("cpu-bar"), document.getElementById("cpu-val"), data.cpu_percent);
    setBar(document.getElementById("ram-bar"), document.getElementById("ram-val"), data.ram_percent);
    setBar(document.getElementById("gpu-bar"), document.getElementById("gpu-val"), data.gpu_percent);
    setServiceDot("svc-llm", data.services?.llm);
    setServiceDot("svc-embedding", data.services?.embedding);
    setServiceDot("svc-stt", data.services?.stt);
  } catch {
    // A missed poll isn't worth surfacing as an error - just try again next tick.
  }
}
pollSystemStatus();
setInterval(pollSystemStatus, 2500);

async function pollWeather() {
  try {
    const resp = await fetch("/widgets/weather");
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data) return;
    document.getElementById("weather-temp").innerHTML = `${Math.round(data.temperature_c)}&deg;C`;
    document.getElementById("weather-condition").textContent = data.condition;
    document.getElementById("weather-location").textContent = data.location;
  } catch {
    // Skip a failed poll silently - it'll retry on the next interval.
  }
}
pollWeather();
setInterval(pollWeather, 5 * 60 * 1000);

async function pollStocks() {
  try {
    const resp = await fetch("/widgets/stocks");
    if (!resp.ok) return;
    const rows = await resp.json();
    const body = document.getElementById("stocks-body");
    body.innerHTML = "";
    rows.forEach((row) => {
      const el = document.createElement("div");
      el.className = "stock-row";
      if (row.price === null) {
        el.innerHTML = `<span class="stock-symbol">${row.symbol}</span><span class="stock-price">--</span>`;
      } else {
        const up = row.change_percent >= 0;
        el.innerHTML = `
          <span class="stock-symbol">${row.symbol}</span>
          <span class="stock-price">${row.price.toFixed(2)}</span>
          <span class="stock-change ${up ? "up" : "down"}">${up ? "+" : ""}${row.change_percent.toFixed(2)}%</span>
        `;
      }
      body.appendChild(el);
    });
  } catch {
    // Skip a failed poll silently - it'll retry on the next interval.
  }
}
pollStocks();
setInterval(pollStocks, 60 * 1000);

async function pollNews() {
  try {
    const resp = await fetch("/widgets/news");
    if (!resp.ok) return;
    const items = await resp.json();
    const body = document.getElementById("news-body");
    body.innerHTML = "";
    items.slice(0, 6).forEach((item) => {
      const el = document.createElement("div");
      el.className = "news-item";
      const a = document.createElement("a");
      a.href = item.link;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = item.title;
      el.appendChild(a);
      body.appendChild(el);
    });
  } catch {
    // Skip a failed poll silently - it'll retry on the next interval.
  }
}
pollNews();
setInterval(pollNews, 10 * 60 * 1000);

function logActivity(label) {
  const entry = document.createElement("div");
  entry.className = "log-entry";
  entry.dataset.time = new Date().toLocaleTimeString([], { hour12: false });
  entry.textContent = label;
  activityLog.prepend(entry);
  while (activityLog.children.length > 30) {
    activityLog.removeChild(activityLog.lastChild);
  }
}

setState("idle");
