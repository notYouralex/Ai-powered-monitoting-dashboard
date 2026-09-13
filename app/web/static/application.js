"use strict";

const API = Object.freeze({
  me: "/api/auth/me",
  login: "/api/auth/login",
  logout: "/api/auth/logout",
  executive: "/api/dashboard/executive",
});

const PAGE_CONFIG = Object.freeze({
  "/app": {
    activeRoute: "/app/executive",
    eyebrow: "Overview",
    title: "Executive",
    description: "Cross-source health, alerts, service management, and asset posture.",
    view: "executive",
  },
  "/app/executive": {
    activeRoute: "/app/executive",
    eyebrow: "Overview",
    title: "Executive",
    description: "Cross-source health, alerts, service management, and asset posture.",
    view: "executive",
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
const shellStatus = document.getElementById("shell-status");
const phaseCard = document.getElementById("phase-card");
const phaseMessage = document.getElementById("phase-message");
const legacyAiLink = document.getElementById("legacy-ai-link");
const executiveDashboardView = document.getElementById("executive-dashboard-view");
const executiveStatus = document.getElementById("executive-status");
const executiveObservedAt = document.getElementById("executive-observed-at");
const metricOverallHealth = document.getElementById("metric-overall-health");
const metricSecurityAlerts = document.getElementById("metric-security-alerts");
const metricOpenTickets = document.getElementById("metric-open-tickets");
const metricOverdueTickets = document.getElementById("metric-overdue-tickets");
const metricSlaCompliance = document.getElementById("metric-sla-compliance");
const metricAssets = document.getElementById("metric-assets");
const executiveAlertDistribution = document.getElementById("executive-alert-distribution");
const executiveTicketDistribution = document.getElementById("executive-ticket-distribution");
const executiveSourceHealthBody = document.getElementById("executive-source-health-body");
const executiveAttentionBody = document.getElementById("executive-attention-body");
const navigationLinks = Array.from(document.querySelectorAll(".primary-nav a"));

const SOURCE_NAMES = Object.freeze({
  wazuh: "Wazuh",
  zabbix: "Zabbix",
  snipe_it: "Snipe-IT",
  freshservice: "Freshservice",
});

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

function clearNode(element) {
  while (element.firstChild) {
    element.removeChild(element.firstChild);
  }
}

function createTextElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  element.textContent = text;
  return element;
}

function formatCount(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString()
    : "—";
}

function formatPercent(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "Not available";
  }
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
}

function formatTimestamp(value) {
  if (!value) {
    return "Not available";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Not available";
  }
  return date.toLocaleString();
}

function formatStatus(status) {
  if (typeof status !== "string" || !status) {
    return "Unknown";
  }
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function renderDistribution(container, rows) {
  clearNode(container);
  if (!Array.isArray(rows) || rows.length === 0) {
    container.appendChild(createTextElement("p", "muted empty-message", "No data available."));
    return;
  }

  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "distribution-row";
    item.appendChild(createTextElement("span", "distribution-name", String(row.name || "Unknown")));
    item.appendChild(createTextElement("strong", "distribution-count", formatCount(row.count)));
    container.appendChild(item);
  }
}

function renderSourceHealth(sources) {
  clearNode(executiveSourceHealthBody);
  if (!Array.isArray(sources) || sources.length === 0) {
    const row = document.createElement("tr");
    const cell = createTextElement("td", "muted table-empty", "No source health data available.");
    cell.colSpan = 4;
    row.appendChild(cell);
    executiveSourceHealthBody.appendChild(row);
    return;
  }

  for (const source of sources) {
    const health = source.health || {};
    const row = document.createElement("tr");
    row.appendChild(createTextElement("td", "", formatTimestamp(health.last_success_at)));
    row.appendChild(createTextElement("td", "", SOURCE_NAMES[source.source] || String(source.source || "Unknown")));
    row.appendChild(createTextElement("td", "", source.is_stale ? "Stale" : "Fresh"));

    const statusCell = document.createElement("td");
    const status = createTextElement("span", "health-badge", formatStatus(health.status));
    status.dataset.status = typeof health.status === "string" ? health.status : "unknown";
    statusCell.appendChild(status);
    row.appendChild(statusCell);
    executiveSourceHealthBody.appendChild(row);
  }
}

function renderAttention(items) {
  clearNode(executiveAttentionBody);
  if (!Array.isArray(items) || items.length === 0) {
    const row = document.createElement("tr");
    const cell = createTextElement("td", "muted table-empty", "No attention items reported.");
    cell.colSpan = 3;
    row.appendChild(cell);
    executiveAttentionBody.appendChild(row);
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");
    row.appendChild(createTextElement("td", "", String(item.source || "Unknown")));
    row.appendChild(createTextElement("td", "", String(item.issue || "Unspecified issue")));
    row.appendChild(createTextElement("td", "table-number", formatCount(item.count)));
    executiveAttentionBody.appendChild(row);
  }
}

function renderExecutiveDashboard(body) {
  if (!body || !body.summary) {
    throw new Error("Executive response is incomplete");
  }

  const summary = body.summary;
  metricOverallHealth.textContent = formatPercent(summary.overall_health_percent);
  metricSecurityAlerts.textContent = formatCount(summary.security_alerts);
  metricOpenTickets.textContent = formatCount(summary.tickets_open);
  metricOverdueTickets.textContent = formatCount(summary.overdue_open);
  metricSlaCompliance.textContent = formatPercent(summary.resolution_sla_compliance_percent);
  metricAssets.textContent = formatCount(summary.assets_total);

  renderDistribution(executiveAlertDistribution, body.alert_category_distribution);
  renderDistribution(executiveTicketDistribution, body.ticket_status_distribution);
  renderSourceHealth(body.sources);
  renderAttention(body.attention_required);

  executiveObservedAt.textContent = `Observed ${formatTimestamp(body.observed_at)}`;
  executiveStatus.textContent = `Showing the canonical Executive view for ${formatTimestamp(body.range_start)} to ${formatTimestamp(body.range_end)}.`;
  shellStatus.textContent = "Executive data loaded";
}

async function loadExecutiveDashboard() {
  executiveStatus.textContent = "Loading Executive data...";
  executiveObservedAt.textContent = "";
  shellStatus.textContent = "Loading Executive";

  try {
    const { response, body } = await requestJson(API.executive);
    if (response.status === 401) {
      return;
    }
    if (!response.ok) {
      executiveStatus.textContent = errorMessage(body, "Executive dashboard data is unavailable.");
      shellStatus.textContent = "Executive unavailable";
      return;
    }
    renderExecutiveDashboard(body);
  } catch (_error) {
    executiveStatus.textContent = "Executive dashboard data is unavailable.";
    shellStatus.textContent = "Executive unavailable";
  }
}

function renderRoute() {
  const config = PAGE_CONFIG[window.location.pathname] || PAGE_CONFIG["/app"];
  const isExecutive = config.view === "executive";
  pageEyebrow.textContent = config.eyebrow;
  pageTitle.textContent = config.title;
  pageDescription.textContent = config.description;
  phaseMessage.textContent = config.message || "";
  setHidden(executiveDashboardView, !isExecutive);
  setHidden(phaseCard, isExecutive);
  setHidden(legacyAiLink, !config.legacyAi);
  shellStatus.textContent = isExecutive ? "Loading Executive" : "Application shell ready";
  document.title = `${config.title} | AI-Powered Monitoring`;

  for (const link of navigationLinks) {
    if (link.getAttribute("href") === config.activeRoute) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }

  return config;
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
  const config = renderRoute();
  if (config.view === "executive") {
    loadExecutiveDashboard();
  }
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
