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

setState("idle");
