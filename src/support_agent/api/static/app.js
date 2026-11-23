"use strict";

const customer = document.querySelector("#customer");
const newChat = document.querySelector("#new-chat");
const messages = document.querySelector("#messages");
const composer = document.querySelector("#composer");
const message = document.querySelector("#message");
const send = document.querySelector("#send");
const debug = document.querySelector("#debug");
const details = document.querySelector("#details");
const status = document.querySelector("#status");
const memoriesList = document.querySelector("#memories-list");
const memoriesCount = document.querySelector("#memories-count");
const memoriesRefresh = document.querySelector("#memories-refresh");
const memoriesClear = document.querySelector("#memories-clear");

let conversationId;
let activeRequest;
let sessionRequest;
let sessionToken;
let picker;
let handoffStream;

function syncControls() {
  message.disabled = send.disabled = Boolean(activeRequest || picker || !sessionToken);
  memoriesRefresh.disabled = Boolean(!sessionToken);
  memoriesClear.disabled = Boolean(!sessionToken || !memoriesList.children.length);
  for (const button of picker?.querySelectorAll("button") ?? []) {
    button.disabled = Boolean(activeRequest || !sessionToken);
  }
}

async function loadMemories() {
  memoriesList.replaceChildren();
  memoriesCount.textContent = "0";
  if (!sessionToken) {
    syncControls();
    return;
  }
  try {
    const response = await fetch("/api/me/memories", {
      headers: { "Authorization": "Bearer " + sessionToken },
    });
    if (!response.ok) return;
    const items = await response.json();
    memoriesCount.textContent = String(items.length);
    for (const item of items) {
      const li = document.createElement("li");
      const day = String(item.created_at || "").slice(0, 10);
      const span = document.createElement("span");
      span.textContent = "[" + day + " · " + item.kind + "] " + item.content;
      const del = document.createElement("button");
      del.type = "button";
      del.textContent = "Delete";
      del.addEventListener("click", () => deleteMemory(item.id));
      li.append(span, del);
      memoriesList.append(li);
    }
  } finally {
    syncControls();
  }
}

async function deleteMemory(id) {
  if (!sessionToken) return;
  const response = await fetch("/api/me/memories/" + encodeURIComponent(id), {
    method: "DELETE",
    headers: { "Authorization": "Bearer " + sessionToken },
  });
  if (response.ok) await loadMemories();
}

async function clearAllMemories() {
  if (!sessionToken) return;
  const response = await fetch("/api/me/memories", {
    method: "DELETE",
    headers: { "Authorization": "Bearer " + sessionToken },
  });
  if (response.ok) await loadMemories();
}

async function listenForHumanReplies(convId) {
  if (!sessionToken || handoffStream) return;
  const controller = new AbortController();
  handoffStream = controller;
  try {
    const response = await fetch("/api/conversations/" + encodeURIComponent(convId) + "/events", {
      headers: { "Authorization": "Bearer " + sessionToken },
      signal: controller.signal,
    });
    if (!response.ok || !response.body) return;
    await readEvents(response.body, (event, data) => {
      if (handoffStream !== controller) return;
      if (event === "agent_reply") {
        addMessage("agent", "[Human agent " + data.agent_id + "] " + data.text);
      } else if (event === "handoff_resolved") {
        addMessage("badge", "Ticket resolved (" + data.label + ")" + (data.hand_back_to_ai ? " · AI assistant resumed" : ""));
      }
      messages.scrollTop = messages.scrollHeight;
    });
  } catch (_) {
    // Stream aborted on resetChat or closed cleanly on resolution.
  } finally {
    if (handoffStream === controller) handoffStream = null;
  }
}

function resetChat() {
  activeRequest?.abort();
  activeRequest = null;
  handoffStream?.abort();
  handoffStream = null;
  picker = null;
  conversationId = crypto.randomUUID();
  messages.replaceChildren();
  details.textContent = status.textContent = message.value = "";
  syncControls();
}

function addMessage(kind, text = "") {
  const bubble = document.createElement("div");
  bubble.className = kind;
  bubble.textContent = text;
  messages.append(bubble);
  return bubble;
}

function renderCitations(bubble, answer, citations) {
  const headings = new Map(citations.map(({ n, heading_path }) => [String(n), heading_path]));
  bubble.replaceChildren();
  for (const part of answer.split(/(\[\d+\])/)) {
    const heading = /^\[(\d+)\]$/.exec(part);
    if (heading && headings.has(heading[1])) {
      const chip = document.createElement("span");
      chip.className = "citation";
      chip.textContent = part;
      chip.tabIndex = 0;
      chip.title = headings.get(heading[1]);
      chip.setAttribute("aria-label", heading[0] + " " + chip.title);
      bubble.append(chip);
    } else {
      bubble.append(document.createTextNode(part));
    }
  }
}

function showPicker(orders) {
  picker = addMessage("picker");
  const prompt = document.createElement("p");
  prompt.textContent = "Which order is this about?";
  picker.append(prompt);
  for (const order of orders) {
    const label = [
      order.order_id, order.order_date, order.status,
      order.total + " " + order.currency, order.item_names.join(", "),
    ].join(" · ");
    addChoice(order.order_id, label);
  }
  addChoice("none", "None of these");
  syncControls();
}

function addChoice(value, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", () => run("resume", { value }));
  picker.append(button);
}

async function readEvents(body, handle) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let separator;
      while ((separator = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, separator.index).split(/\r?\n/);
        buffer = buffer.slice(separator.index + separator[0].length);
        const event = frame.find((line) => line.startsWith("event: "));
        const data = frame.filter((line) => line.startsWith("data: "));
        if (event && data.length) {
          handle(event.slice(7), JSON.parse(data.map((line) => line.slice(6)).join("\n")));
        }
      }
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}

async function requestError(response) {
  const error = await response.json().catch(() => ({}));
  return new Error(typeof error.detail === "string" ? error.detail : "Invalid request.");
}

async function issueSession(customerId, signal) {
  const response = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customer_id: customerId }),
    signal,
  });
  if (!response.ok) throw await requestError(response);
  return (await response.json()).token;
}

async function selectCustomer() {
  sessionRequest?.abort();
  sessionToken = null;
  resetChat();
  if (!customer.value) return;
  const request = new AbortController();
  sessionRequest = request;
  try {
    const token = await issueSession(customer.value, request.signal);
    if (sessionRequest === request) {
      sessionToken = token;
      await loadMemories();
    }
  } catch (error) {
    if (sessionRequest === request) status.textContent = error.message;
  } finally {
    if (sessionRequest === request) {
      sessionRequest = null;
      syncControls();
    }
  }
}

async function run(endpoint, payload) {
  if (activeRequest || !sessionToken) return;
  const request = new AbortController();
  activeRequest = request;
  status.textContent = "";
  syncControls();
  let bubble;
  let answer = "";
  let complete = false;
  try {
    const body = JSON.stringify({ conversation_id: conversationId, ...payload });
    const sendTurn = (token) => fetch("/api/" + endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
      body,
      signal: request.signal,
    });
    let response = await sendTurn(sessionToken);
    if (activeRequest !== request) return;
    if (response.status === 401) {
      const token = await issueSession(customer.value, request.signal);
      if (activeRequest !== request) return;
      sessionToken = token;
      response = await sendTurn(token);
    }
    if (activeRequest !== request) return;
    if (!response.ok) throw await requestError(response);
    if (endpoint === "resume") {
      picker.remove();
      picker = null;
    }
    await readEvents(response.body, (event, data) => {
      if (activeRequest !== request) return;
      if (event === "meta") {
        addMessage("badge", "Path " + data.path + " · " + data.intent.replaceAll("_", " "));
      } else if (event === "token") {
        bubble ??= addMessage("agent");
        answer += data.text;
        bubble.textContent = answer;
      } else if (event === "citations" && bubble) {
        renderCitations(bubble, answer, data);
      } else if (event === "interrupt" && data.type === "order_picker") {
        showPicker(data.orders);
      } else if (event === "error") {
        addMessage("error", "The request failed (" + data.error_type + ").");
      } else if (event === "handoff") {
        addMessage("handoff", "Transferred to a human agent — reason: " + data.reason + "\n" + data.message);
        complete = true;
        listenForHumanReplies(conversationId);
      } else if (event === "done") {
        details.textContent = JSON.stringify({ gate: data.gate, trace: data.trace }, null, 2);
        complete = true;
      }
      messages.scrollTop = messages.scrollHeight;
    });
    if (!complete) throw new Error("The chat stream closed early.");
  } catch (error) {
    if (activeRequest === request) status.textContent = error.message;
  } finally {
    if (activeRequest === request) {
      activeRequest = null;
      syncControls();
      if (!message.disabled) message.focus();
    }
  }
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = message.value.trim();
  if (!text || activeRequest || picker || !sessionToken) return;
  addMessage("user", text);
  message.value = "";
  run("chat", { message: text });
});
customer.addEventListener("change", selectCustomer);
newChat.addEventListener("click", () => sessionToken ? resetChat() : selectCustomer());
debug.addEventListener("change", () => { details.hidden = !debug.checked; });
memoriesRefresh.addEventListener("click", loadMemories);
memoriesClear.addEventListener("click", clearAllMemories);

async function loadCustomers() {
  try {
    const response = await fetch("/api/customers");
    if (!response.ok) throw new Error("Could not load demo customers.");
    for (const item of await response.json()) {
      customer.add(new Option(item.name + " (" + item.customer_id + ")", item.customer_id));
    }
    if (!customer.value) throw new Error("No demo customers found.");
    customer.disabled = newChat.disabled = false;
    await selectCustomer();
  } catch (error) {
    status.textContent = error.message;
  }
}

loadCustomers();
