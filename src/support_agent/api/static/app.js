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

let conversationId;
let activeRequest;
let picker;

function syncControls() {
  message.disabled = send.disabled = Boolean(activeRequest || picker || !customer.value);
  for (const button of picker?.querySelectorAll("button") ?? []) {
    button.disabled = Boolean(activeRequest);
  }
}

function resetChat() {
  activeRequest?.abort();
  activeRequest = null;
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

async function run(endpoint, payload) {
  if (activeRequest) return;
  const request = new AbortController();
  activeRequest = request;
  status.textContent = "";
  syncControls();
  let bubble;
  let answer = "";
  let complete = false;
  try {
    const response = await fetch("/api/" + endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, customer_id: customer.value, ...payload }),
      signal: request.signal,
    });
    if (activeRequest !== request) return;
    if (!response.ok) {
      const error = await response.json();
      throw new Error(typeof error.detail === "string" ? error.detail : "Invalid request.");
    }
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
  if (!text || activeRequest || picker) return;
  addMessage("user", text);
  message.value = "";
  run("chat", { message: text });
});
customer.addEventListener("change", resetChat);
newChat.addEventListener("click", resetChat);
debug.addEventListener("change", () => { details.hidden = !debug.checked; });

async function loadCustomers() {
  try {
    const response = await fetch("/api/customers");
    if (!response.ok) throw new Error("Could not load demo customers.");
    for (const item of await response.json()) {
      customer.add(new Option(item.name + " (" + item.customer_id + ")", item.customer_id));
    }
    if (!customer.value) throw new Error("No demo customers found.");
    resetChat();
    customer.disabled = newChat.disabled = false;
  } catch (error) {
    status.textContent = error.message;
  }
}

loadCustomers();
