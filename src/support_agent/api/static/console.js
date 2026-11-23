"use strict";

const agentIdInput = document.querySelector("#agent-id");
const tokenInput = document.querySelector("#agent-token");
const statusFilter = document.querySelector("#status-filter");
const refreshBtn = document.querySelector("#refresh");
const queueList = document.querySelector("#queue-list");
const detailPanel = document.querySelector("#detail-panel");
const consoleStatus = document.querySelector("#console-status");

const LABELS = [
  "kb_gap",
  "retrieval_miss",
  "gate_too_strict",
  "correct_handoff",
  "policy_exception",
  "abuse",
];

let selectedId = null;

function authHeaders() {
  return {
    "Content-Type": "application/json",
    "Authorization": "Bearer " + tokenInput.value.trim(),
  };
}

async function api(path, options = {}) {
  const res = await fetch(path, { ...options, headers: authHeaders() });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed (" + res.status + ")");
  return data;
}

async function loadQueue() {
  consoleStatus.textContent = "";
  const status = statusFilter.value;
  const qs = status ? "?status=" + encodeURIComponent(status) : "";
  try {
    const items = await api("/api/agent/handoffs" + qs);
    queueList.replaceChildren();
    if (!items.length) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "No handoffs in this view.";
      queueList.append(li);
      return;
    }
    for (const item of items) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "queue-item" + (item.id === selectedId ? " active" : "");
      btn.textContent =
        "[" + item.priority.toUpperCase() + "] " + item.reason + " · " + item.customer_id + " (" + item.status + ")";
      btn.addEventListener("click", () => selectItem(item.id));
      li.append(btn);
      queueList.append(li);
    }
  } catch (err) {
    consoleStatus.textContent = err.message;
  }
}

async function selectItem(id) {
  selectedId = id;
  try {
    const item = await api("/api/agent/handoffs/" + encodeURIComponent(id));
    renderDetail(item);
    await loadQueue();
  } catch (err) {
    consoleStatus.textContent = err.message;
  }
}

function renderDetail(item) {
  const p = item.payload || {};
  detailPanel.replaceChildren();

  const header = document.createElement("div");
  header.className = "detail-header";
  header.innerHTML =
    "<h2>" + item.id + " · " + item.reason + " (" + item.status + ")</h2>" +
    "<p>Customer: <strong>" + item.customer_id + "</strong> · Conversation: <code>" + item.conversation_id + "</code> · Priority: <strong>" + item.priority + "</strong></p>";
  detailPanel.append(header);

  if (item.status === "open") {
    const claimBtn = document.createElement("button");
    claimBtn.type = "button";
    claimBtn.textContent = "Claim ticket";
    claimBtn.addEventListener("click", async () => {
      try {
        await api("/api/agent/handoffs/" + encodeURIComponent(item.id) + "/claim", {
          method: "POST",
          body: JSON.stringify({ agent_id: agentIdInput.value.trim() }),
        });
        await selectItem(item.id);
      } catch (err) {
        consoleStatus.textContent = err.message;
      }
    });
    detailPanel.append(claimBtn);
  }

  const snap = document.createElement("pre");
  snap.className = "snapshot";
  snap.textContent = JSON.stringify(
    {
      rewritten_query: p.rewritten_query,
      intent: p.intent,
      gate: p.gate,
      pinned_facts: p.pinned_facts,
      guardrail_flags: p.guardrail_flags,
      retrieval_snapshot: (p.retrieval_snapshot || []).map((c) => ({
        heading: c.heading_path,
        rerank_score: c.rerank_score,
        text: (c.text || "").slice(0, 180),
      })),
      conversation: (p.conversation || []).map((m) => ({
        type: m.type,
        content: m.content,
      })),
      human_thread: p.human_thread || [],
    },
    null,
    2
  );
  detailPanel.append(snap);

  if (item.status === "claimed") {
    const replyForm = document.createElement("form");
    replyForm.className = "action-box";
    const replyInput = document.createElement("textarea");
    replyInput.rows = 3;
    replyInput.placeholder = "Write a reply to the customer...";
    const replyBtn = document.createElement("button");
    replyBtn.type = "submit";
    replyBtn.textContent = "Send reply to customer";
    replyForm.append(replyInput, replyBtn);
    replyForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!replyInput.value.trim()) return;
      try {
        await api("/api/agent/handoffs/" + encodeURIComponent(item.id) + "/reply", {
          method: "POST",
          body: JSON.stringify({
            agent_id: agentIdInput.value.trim(),
            message: replyInput.value.trim(),
          }),
        });
        replyInput.value = "";
        await selectItem(item.id);
      } catch (err) {
        consoleStatus.textContent = err.message;
      }
    });
    detailPanel.append(replyForm);

    const resolveForm = document.createElement("form");
    resolveForm.className = "action-box";
    const labelSelect = document.createElement("select");
    for (const lbl of LABELS) labelSelect.add(new Option(lbl, lbl));
    const noteInput = document.createElement("input");
    noteInput.type = "text";
    noteInput.placeholder = "Resolution note / answer points";
    const handBack = document.createElement("input");
    handBack.type = "checkbox";
    handBack.checked = true;
    const handBackLbl = document.createElement("label");
    handBackLbl.append(handBack, document.createTextNode(" Hand back to AI"));
    const resolveBtn = document.createElement("button");
    resolveBtn.type = "submit";
    resolveBtn.textContent = "Resolve with label";
    resolveForm.append(labelSelect, noteInput, handBackLbl, resolveBtn);
    resolveForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api("/api/agent/handoffs/" + encodeURIComponent(item.id) + "/resolve", {
          method: "POST",
          body: JSON.stringify({
            agent_id: agentIdInput.value.trim(),
            label: labelSelect.value,
            note: noteInput.value.trim(),
            hand_back_to_ai: handBack.checked,
          }),
        });
        await selectItem(item.id);
      } catch (err) {
        consoleStatus.textContent = err.message;
      }
    });
    detailPanel.append(resolveForm);
  }
}

refreshBtn.addEventListener("click", loadQueue);
statusFilter.addEventListener("change", loadQueue);
loadQueue();
