"use strict";

const API = Object.freeze({
  me: "/api/auth/me",
  login: "/api/auth/login",
  logout: "/api/auth/logout",
});

const PAGE_CONFIG = Object.freeze({
  "/app": {
    activeRoute: "/app/executive",
    eyebrow: "Overview",
    title: "Executive",
    description: "Unified monitoring starts with the Executive view.",
    message: "The application shell is ready. Executive dashboard data will be added in Phase 2.",
  },
  "/app/executive": {
    activeRoute: "/app/executive",
    eyebrow: "Overview",
    title: "Executive",
    description: "Cross-source health, alerts, service management, and asset posture.",
    message: "Executive dashboard data will be added in Phase 2 using the existing canonical API.",
  },
  "/app/wazuh": {
    activeRoute: "/app/wazuh",
    eyebrow: "Security",
    title: "Wazuh",
    description: "Security monitoring, agents, alerts, vulnerabilities, and related evidence.",
    message: "The Wazuh web dashboard will be migrated in its dedicated phase.",
  },
  "/app/zabbix": {
    activeRoute: "/app/zabbix",
    eyebrow: "Infrastructure",
    title: "Zabbix",
    description: "Infrastructure health, resource pressure, problems, and topology.",
    message: "The Zabbix web dashboard will be migrated in its dedicated phase.",
  },
  "/app/snipe-it": {
    activeRoute: "/app/snipe-it",
    eyebrow: "Assets",
    title: "Snipe-IT",
    description: "Asset inventory, state, activity, and warranty information.",
    message: "The Snipe-IT web dashboard will be migrated in its dedicated phase.",
  },
  "/app/freshservice": {
    activeRoute: "/app/freshservice",
    eyebrow: "Service Management",
    title: "Freshservice",
    description: "Ticket operations, priorities, overdue work, trends, and SLA reporting.",
    message: "The Freshservice web dashboard will be migrated in its dedicated phase.",
  },
  "/app/ai": {
    activeRoute: "/app/ai",
    eyebrow: "Read-only Assistant",
    title: "AI Investigation",
    description: "Local, bounded investigation guidance using normalized monitoring evidence.",
    message: "The existing AI Investigation remains available at /ai until it is migrated into this shell in Phase 7.",
    legacyAi: true,
  },
});

const loginView = document.getElementById("login-view");
const applicationView = document.getElementById("application-view");
const loginForm = document.getElementById("login-form");
const loginButton = document.getElementById("login-button");
const loginError = document.getElementById("login-error");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const sessionControls = document.getElementById("session-controls");
const currentUser = document.getElementById("current-user");
const logoutButton = document.getElementById("logout-button");
const pageEyebrow = document.getElementById("page-eyebrow");
const pageTitle = document.getElementById("page-title");
const pageDescription = document.getElementById("page-description");
const phaseMessage = document.getElementById("phase-message");
const legacyAiLink = document.getElementById("legacy-ai-link");
const navigationLinks = Array.from(document.querySelectorAll(".primary-nav a"));

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

  if (response.status === 401 && path !== API.login && path !== API.me) {
    showLogin("Your session expired. Sign in again to continue.");
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

function renderRoute() {
  const config = PAGE_CONFIG[window.location.pathname] || PAGE_CONFIG["/app"];
  pageEyebrow.textContent = config.eyebrow;
  pageTitle.textContent = config.title;
  pageDescription.textContent = config.description;
  phaseMessage.textContent = config.message;
  setHidden(legacyAiLink, !config.legacyAi);
  document.title = `${config.title} | AI-Powered Monitoring`;

  for (const link of navigationLinks) {
    if (link.getAttribute("href") === config.activeRoute) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }
}

function showLogin(message = "") {
  setHidden(loginView, false);
  setHidden(applicationView, true);
  setHidden(sessionControls, true);
  currentUser.textContent = "";
  loginError.textContent = message;
  setHidden(loginError, !message);
  usernameInput.focus();
}

function showApplication(user) {
  setHidden(loginView, true);
  setHidden(applicationView, false);
  setHidden(sessionControls, false);
  currentUser.textContent = user.username;
  loginError.textContent = "";
  setHidden(loginError, true);
  renderRoute();
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
      loginError.textContent = errorMessage(body, "Sign in failed.");
      setHidden(loginError, false);
      return;
    }

    showApplication(body);
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

async function initialize() {
  try {
    const { response, body } = await requestJson(API.me);
    if (response.status === 401) {
      showLogin();
      return;
    }
    if (!response.ok) {
      showLogin("The monitoring session could not be verified.");
      return;
    }
    showApplication(body);
  } catch (_error) {
    showLogin("The monitoring API is unavailable.");
  }
}

loginForm.addEventListener("submit", handleLogin);
logoutButton.addEventListener("click", handleLogout);
initialize();
