"use strict";

const API = Object.freeze({
  me: "/api/auth/me",
  login: "/api/auth/login",
  logout: "/api/auth/logout",
  query: "/api/ai/query",
});

const loginView = document.getElementById("login-view");
const chatView = document.getElementById("chat-view");
const loginForm = document.getElementById("login-form");
const loginButton = document.getElementById("login-button");
const loginError = document.getElementById("login-error");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const sessionControls = document.getElementById("session-controls");
const currentUser = document.getElementById("current-user");
const logoutButton = document.getElementById("logout-button");
const chatForm = document.getElementById("chat-form");
const questionInput = document.getElementById("question");
const sendButton = document.getElementById("send-button");
const requestStatus = document.getElementById("request-status");
const characterCount = document.getElementById("character-count");
const conversation = document.getElementById("conversation");

let requestInFlight = false;

function setHidden(element, hidden) {
  element.hidden = hidden;
}

async function requestJson(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
  });

  let body = null;
  if (response.status !== 204) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      body = await response.json();
    }
  }

  return { response, body };
}

function errorMessage(body, fallback) {
  if (body && typeof body.detail === "string") {
    return body.detail;
  }
  if (body && body.error && typeof body.error.message === "string") {
    return body.error.message;
  }
  return fallback;
}

function showLogin(message = "") {
  setHidden(loginView, false);
  setHidden(chatView, true);
  setHidden(sessionControls, true);
  currentUser.textContent = "";
  loginError.textContent = message;
  setHidden(loginError, !message);
  requestStatus.textContent = "Ready";
  requestInFlight = false;
  sendButton.disabled = false;
  usernameInput.focus();
}

function showChat(user) {
  setHidden(loginView, true);
  setHidden(chatView, false);
  setHidden(sessionControls, false);
  currentUser.textContent = user.username;
  loginError.textContent = "";
  setHidden(loginError, true);
  questionInput.focus();
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

function appendMessage(role, text, extraClass = "") {
  const roleClass = role === "You" ? "user-message" : "assistant-message";
  const article = createElement("article", `message ${roleClass} ${extraClass}`.trim());
  article.append(createElement("div", "message-label", role));
  article.append(createElement("p", "", text));
  conversation.append(article);
  article.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return article;
}

function appendListSection(parent, title, items, className = "") {
  if (!Array.isArray(items) || items.length === 0) {
    return;
  }

  const section = createElement("section", `response-section ${className}`.trim());
  section.append(createElement("h3", "", title));
  const list = createElement("ul", "");
  for (const item of items) {
    list.append(createElement("li", "", String(item)));
  }
  section.append(list);
  parent.append(section);
}

function appendTextSection(parent, title, text) {
  if (!text) {
    return;
  }

  const section = createElement("section", "response-section");
  section.append(createElement("h3", "", title));
  section.append(createElement("p", "", String(text)));
  parent.append(section);
}

function formatTime(value) {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function humanSource(value) {
  if (!value) {
    return null;
  }
  const names = {
    wazuh: "Wazuh",
    zabbix: "Zabbix",
    snipe_it: "Snipe-IT",
    freshservice: "Freshservice",
  };
  return names[value] || value;
}

function appendMeta(parent, label, className = "") {
  if (!label) {
    return;
  }
  parent.append(createElement("span", `meta-pill ${className}`.trim(), label));
}

function renderInvestigation(result) {
  const analysis = result.analysis || {};
  const classification = result.classification || {};
  const article = createElement("article", "message assistant-message");
  article.append(createElement("div", "message-label", "Monitoring AI"));

  const meta = createElement("div", "response-meta");
  appendMeta(meta, classification.scope ? `Scope: ${classification.scope}` : null);
  appendMeta(meta, humanSource(classification.source));
  if (result.device && result.device.canonical_name) {
    appendMeta(meta, `Device: ${result.device.canonical_name}`);
  }
  if (analysis.confidence) {
    appendMeta(
      meta,
      `Confidence: ${analysis.confidence}`,
      `confidence-${analysis.confidence}`,
    );
  }
  appendMeta(meta, `${formatTime(result.range_start)} – ${formatTime(result.range_end)}`);
  article.append(meta);

  article.append(createElement("p", "", analysis.summary || "No summary was returned."));
  appendTextSection(article, "Most likely explanation", analysis.likely_explanation);
  appendTextSection(article, "Operational impact", analysis.operational_impact);
  appendListSection(article, "Contributing factors", analysis.contributing_factors);
  appendListSection(article, "Supporting evidence", analysis.evidence);
  appendListSection(article, "Recommended investigation", analysis.recommended_investigation);

  const warnings = [];
  for (const value of [...(analysis.warnings || []), ...(result.source_warnings || [])]) {
    if (!warnings.includes(value)) {
      warnings.push(value);
    }
  }
  appendListSection(article, "Data limitations and warnings", warnings, "warning-section");

  conversation.append(article);
  article.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function setRequestBusy(busy) {
  requestInFlight = busy;
  sendButton.disabled = busy;
  questionInput.disabled = busy;
  requestStatus.textContent = busy ? "Analyzing monitoring evidence..." : "Ready";
}

async function handleLogin(event) {
  event.preventDefault();
  loginButton.disabled = true;
  loginError.textContent = "";
  setHidden(loginError, true);

  const username = usernameInput.value.trim();
  const password = passwordInput.value;

  try {
    const { response, body } = await requestJson(API.login, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    passwordInput.value = "";

    if (!response.ok) {
      const message = errorMessage(body, "Sign in failed.");
      loginError.textContent = message;
      setHidden(loginError, false);
      return;
    }

    showChat(body);
  } catch (_error) {
    passwordInput.value = "";
    loginError.textContent = "The monitoring API is unavailable.";
    setHidden(loginError, false);
  } finally {
    loginButton.disabled = false;
  }
}

async function handleLogout() {
  logoutButton.disabled = true;
  try {
    await requestJson(API.logout, { method: "POST" });
  } finally {
    logoutButton.disabled = false;
    showLogin();
  }
}

async function handleQuestion(event) {
  event.preventDefault();
  if (requestInFlight) {
    return;
  }

  const question = questionInput.value.trim();
  if (!question) {
    return;
  }

  appendMessage("You", question);
  questionInput.value = "";
  characterCount.textContent = "0";
  setRequestBusy(true);

  const loading = appendMessage("Monitoring AI", "Reviewing bounded evidence", "loading-message");
  loading.querySelector("p").classList.add("loading-dots");

  try {
    const { response, body } = await requestJson(API.query, {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    loading.remove();

    if (response.status === 401) {
      showLogin("Your session expired. Sign in again to continue.");
      return;
    }
    if (!response.ok) {
      appendMessage(
        "Monitoring AI",
        errorMessage(body, "The investigation could not be completed."),
        "error-message",
      );
      return;
    }

    renderInvestigation(body);
  } catch (_error) {
    loading.remove();
    appendMessage(
      "Monitoring AI",
      "The monitoring API could not be reached. No investigation result was produced.",
      "error-message",
    );
  } finally {
    setRequestBusy(false);
    if (!chatView.hidden) {
      questionInput.focus();
    }
  }
}

async function initialize() {
  try {
    const { response, body } = await requestJson(API.me);
    if (response.ok) {
      showChat(body);
      return;
    }
  } catch (_error) {
    showLogin("The monitoring API is unavailable.");
    return;
  }
  showLogin();
}

loginForm.addEventListener("submit", handleLogin);
logoutButton.addEventListener("click", handleLogout);
chatForm.addEventListener("submit", handleQuestion);
questionInput.addEventListener("input", () => {
  characterCount.textContent = String(questionInput.value.length);
});
questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

for (const button of document.querySelectorAll(".suggestion")) {
  button.addEventListener("click", () => {
    questionInput.value = button.textContent.trim();
    characterCount.textContent = String(questionInput.value.length);
    questionInput.focus();
  });
}

initialize();
