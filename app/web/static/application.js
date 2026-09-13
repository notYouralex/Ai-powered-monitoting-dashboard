"use strict";

const API = Object.freeze({
  me: "/api/auth/me",
  login: "/api/auth/login",
  logout: "/api/auth/logout",
  executive: "/api/dashboard/executive",
  wazuh: "/api/dashboard/wazuh",
  zabbix: "/api/dashboard/zabbix",
  snipeIt: "/api/dashboard/snipe-it",
  snipeItActivity: "/api/dashboard/snipe-it/recent-activity",
  snipeItWarranty: "/api/dashboard/snipe-it/warranty-expiry",
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
    view: "wazuh",
  },
  "/app/zabbix": {
    activeRoute: "/app/zabbix",
    eyebrow: "Infrastructure",
    title: "Zabbix",
    description: "Infrastructure health, resource pressure, problems, and topology.",
    view: "zabbix",
  },
  "/app/snipe-it": {
    activeRoute: "/app/snipe-it",
    eyebrow: "Assets",
    title: "Snipe-IT",
    description: "Asset inventory, state, activity, and warranty information.",
    view: "snipeIt",
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
const wazuhDashboardView = document.getElementById("wazuh-dashboard-view");
const wazuhStatus = document.getElementById("wazuh-status");
const wazuhObservedAt = document.getElementById("wazuh-observed-at");
const wazuhWarnings = document.getElementById("wazuh-warnings");
const wazuhWarningList = document.getElementById("wazuh-warning-list");
const wazuhMetricAlertsTotal = document.getElementById("wazuh-metric-alerts-total");
const wazuhMetricAlertsCritical = document.getElementById("wazuh-metric-alerts-critical");
const wazuhMetricAlertsHigh = document.getElementById("wazuh-metric-alerts-high");
const wazuhMetricVulnerabilitiesTotal = document.getElementById("wazuh-metric-vulnerabilities-total");
const wazuhMetricVulnerabilitiesCritical = document.getElementById("wazuh-metric-vulnerabilities-critical");
const wazuhMetricVulnerabilitiesHigh = document.getElementById("wazuh-metric-vulnerabilities-high");
const wazuhAlertTrend = document.getElementById("wazuh-alert-trend");
const wazuhAlertSeverity = document.getElementById("wazuh-alert-severity");
const wazuhMitreTactics = document.getElementById("wazuh-mitre-tactics");
const wazuhTopAlertsBody = document.getElementById("wazuh-top-alerts-body");
const wazuhVulnerabilitySeverity = document.getElementById("wazuh-vulnerability-severity");
const wazuhTopAgents = document.getElementById("wazuh-top-agents");
const wazuhAgentStatus = document.getElementById("wazuh-agent-status");
const wazuhRecentAlertsBody = document.getElementById("wazuh-recent-alerts-body");
const wazuhRangeButtons = Array.from(document.querySelectorAll("[data-wazuh-range]"));
const zabbixDashboardView = document.getElementById("zabbix-dashboard-view");
const zabbixStatus = document.getElementById("zabbix-status");
const zabbixObservedAt = document.getElementById("zabbix-observed-at");
const zabbixWarnings = document.getElementById("zabbix-warnings");
const zabbixWarningList = document.getElementById("zabbix-warning-list");
const zabbixMetricHosts = document.getElementById("zabbix-metric-hosts");
const zabbixMetricProblems = document.getElementById("zabbix-metric-problems");
const zabbixMetricUnreachable = document.getElementById("zabbix-metric-unreachable");
const zabbixMetricCpu = document.getElementById("zabbix-metric-cpu");
const zabbixMetricCritical = document.getElementById("zabbix-metric-critical");
const zabbixAvailability = document.getElementById("zabbix-availability");
const zabbixProblemSeverity = document.getElementById("zabbix-problem-severity");
const zabbixActiveProblemsBody = document.getElementById("zabbix-active-problems-body");
const zabbixTopHostsBody = document.getElementById("zabbix-top-hosts-body");
const zabbixCpuLive = document.getElementById("zabbix-cpu-live");
const zabbixMemoryLive = document.getElementById("zabbix-memory-live");
const zabbixNetworkLatency = document.getElementById("zabbix-network-latency");
const zabbixNetworkBandwidth = document.getElementById("zabbix-network-bandwidth");
const zabbixTopology = document.getElementById("zabbix-topology");
const zabbixSystemInfoBody = document.getElementById("zabbix-system-info-body");
const snipeItDashboardView = document.getElementById("snipe-it-dashboard-view");
const snipeItStatus = document.getElementById("snipe-it-status");
const snipeItObservedAt = document.getElementById("snipe-it-observed-at");
const snipeItWarnings = document.getElementById("snipe-it-warnings");
const snipeItWarningList = document.getElementById("snipe-it-warning-list");
const snipeItMetricTotal = document.getElementById("snipe-it-metric-total");
const snipeItMetricAssigned = document.getElementById("snipe-it-metric-assigned");
const snipeItMetricUnassigned = document.getElementById("snipe-it-metric-unassigned");
const snipeItMetricDeployed = document.getElementById("snipe-it-metric-deployed");
const snipeItMetricAvailable = document.getElementById("snipe-it-metric-available");
const snipeItMetricMaintenance = document.getElementById("snipe-it-metric-maintenance");
const snipeItMetricRetired = document.getElementById("snipe-it-metric-retired");
const snipeItMetricMissingSerial = document.getElementById("snipe-it-metric-missing-serial");
const snipeItMetricMissingTag = document.getElementById("snipe-it-metric-missing-tag");
const snipeItMetricWarrantyExpired = document.getElementById("snipe-it-metric-warranty-expired");
const snipeItMetricWarrantySoon = document.getElementById("snipe-it-metric-warranty-soon");
const snipeItCategoryDistribution = document.getElementById("snipe-it-category-distribution");
const snipeItStatusDistribution = document.getElementById("snipe-it-status-distribution");
const snipeItCompanyDistribution = document.getElementById("snipe-it-company-distribution");
const snipeItLocationDistribution = document.getElementById("snipe-it-location-distribution");
const snipeItActivityStatus = document.getElementById("snipe-it-activity-status");
const snipeItRecentActivityBody = document.getElementById("snipe-it-recent-activity-body");
const snipeItWarrantyStatus = document.getElementById("snipe-it-warranty-status");
const snipeItWarrantyBody = document.getElementById("snipe-it-warranty-body");
const navigationLinks = Array.from(document.querySelectorAll(".primary-nav a"));

const SOURCE_NAMES = Object.freeze({
  wazuh: "Wazuh",
  zabbix: "Zabbix",
  snipe_it: "Snipe-IT",
  freshservice: "Freshservice",
});

const WAZUH_RANGE_HOURS = Object.freeze({
  "24h": 24,
  "7d": 24 * 7,
  "30d": 24 * 30,
});
let wazuhRange = "24h";

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

function renderNamedCountTable(tbody, rows, emptyMessage) {
  clearNode(tbody);
  if (!Array.isArray(rows) || rows.length === 0) {
    const row = document.createElement("tr");
    const cell = createTextElement("td", "muted table-empty", emptyMessage);
    cell.colSpan = 2;
    row.appendChild(cell);
    tbody.appendChild(row);
    return;
  }
  for (const item of rows) {
    const row = document.createElement("tr");
    row.appendChild(createTextElement("td", "", String(item.name || "Unknown")));
    row.appendChild(createTextElement("td", "table-number", formatCount(item.count)));
    tbody.appendChild(row);
  }
}

function renderWazuhWarnings(body) {
  const warnings = [];
  for (const value of [...(body.warnings || []), ...((body.health && body.health.warnings) || [])]) {
    if (typeof value === "string" && value && !warnings.includes(value)) {
      warnings.push(value);
    }
  }
  clearNode(wazuhWarningList);
  setHidden(wazuhWarnings, warnings.length === 0);
  for (const warning of warnings) {
    wazuhWarningList.appendChild(createTextElement("p", "warning-item", warning));
  }
}

function renderWazuhTrend(points) {
  clearNode(wazuhAlertTrend);
  if (!Array.isArray(points) || points.length === 0) {
    wazuhAlertTrend.appendChild(createTextElement("p", "muted empty-message", "No alert trend data available."));
    return;
  }
  for (const point of points.slice(-24)) {
    const row = document.createElement("div");
    row.className = "trend-row";
    row.appendChild(createTextElement("span", "trend-time", formatTimestamp(point.timestamp)));
    row.appendChild(createTextElement("strong", "trend-count", formatCount(point.count)));
    wazuhAlertTrend.appendChild(row);
  }
}

function renderWazuhRecentAlerts(alerts) {
  clearNode(wazuhRecentAlertsBody);
  if (!Array.isArray(alerts) || alerts.length === 0) {
    const row = document.createElement("tr");
    const cell = createTextElement("td", "muted table-empty", "No recent alerts in the selected range.");
    cell.colSpan = 5;
    row.appendChild(cell);
    wazuhRecentAlertsBody.appendChild(row);
    return;
  }
  for (const alert of alerts) {
    const row = document.createElement("tr");
    row.appendChild(createTextElement("td", "", formatTimestamp(alert.timestamp)));
    row.appendChild(createTextElement("td", "table-number", formatCount(alert.rule_level)));
    row.appendChild(createTextElement("td", "", String(alert.description || "Unknown alert")));
    row.appendChild(createTextElement("td", "", String(alert.agent_name || "Not reported")));
    row.appendChild(createTextElement("td", "", String(alert.rule_id || "Not reported")));
    wazuhRecentAlertsBody.appendChild(row);
  }
}

function renderWazuhDashboard(body) {
  if (!body || !body.summary || !body.health) {
    throw new Error("Wazuh response is incomplete");
  }
  const summary = body.summary;
  wazuhMetricAlertsTotal.textContent = formatCount(summary.alerts_total);
  wazuhMetricAlertsCritical.textContent = formatCount(summary.alerts_critical);
  wazuhMetricAlertsHigh.textContent = formatCount(summary.alerts_high);
  wazuhMetricVulnerabilitiesTotal.textContent = formatCount(summary.vulnerabilities_total);
  wazuhMetricVulnerabilitiesCritical.textContent = formatCount(summary.vulnerabilities_critical);
  wazuhMetricVulnerabilitiesHigh.textContent = formatCount(summary.vulnerabilities_high);

  renderWazuhTrend(body.alert_trend);
  renderDistribution(wazuhAlertSeverity, [
    { name: "Low", count: summary.alerts_low },
    { name: "Medium", count: summary.alerts_medium },
    { name: "High", count: summary.alerts_high },
    { name: "Critical", count: summary.alerts_critical },
  ]);
  renderDistribution(wazuhMitreTactics, body.mitre && body.mitre.tactics);
  renderNamedCountTable(wazuhTopAlertsBody, body.top_alerts, "No top alerts available.");
  renderDistribution(wazuhVulnerabilitySeverity, body.vulnerabilities && body.vulnerabilities.by_severity);
  renderDistribution(wazuhTopAgents, body.top_agents);
  renderDistribution(wazuhAgentStatus, [
    { name: "Active", count: summary.agents_active },
    { name: "Disconnected", count: summary.agents_disconnected },
    { name: "Pending", count: summary.agents_pending },
    { name: "Never Connected", count: summary.agents_never_connected },
    { name: "Unknown", count: summary.agents_unknown },
  ]);
  renderWazuhRecentAlerts(body.recent_alerts);
  renderWazuhWarnings(body);

  const freshness = body.is_stale ? "Stale" : "Fresh";
  wazuhObservedAt.textContent = `Observed ${formatTimestamp(body.observed_at)}`;
  wazuhStatus.textContent = `${formatStatus(body.health.status)} · ${freshness} · ${formatTimestamp(body.range_start)} to ${formatTimestamp(body.range_end)}`;
  shellStatus.textContent = `Wazuh ${formatStatus(body.health.status)}`;
}

function wazuhRangeUrl() {
  const hours = WAZUH_RANGE_HOURS[wazuhRange] || WAZUH_RANGE_HOURS["24h"];
  const end = new Date();
  const start = new Date(end.getTime() - (hours * 60 * 60 * 1000));
  const params = new URLSearchParams({ from: start.toISOString(), to: end.toISOString() });
  return `${API.wazuh}?${params.toString()}`;
}

async function loadWazuhDashboard() {
  wazuhStatus.textContent = "Loading Wazuh data...";
  wazuhObservedAt.textContent = "";
  shellStatus.textContent = "Loading Wazuh";
  try {
    const { response, body } = await requestJson(wazuhRangeUrl());
    if (response.status === 401) {
      return;
    }
    if (!response.ok) {
      wazuhStatus.textContent = errorMessage(body, "Wazuh dashboard data is unavailable.");
      shellStatus.textContent = "Wazuh unavailable";
      return;
    }
    renderWazuhDashboard(body);
  } catch (_error) {
    wazuhStatus.textContent = "Wazuh dashboard data is unavailable.";
    shellStatus.textContent = "Wazuh unavailable";
  }
}

function selectWazuhRange(range) {
  if (!Object.prototype.hasOwnProperty.call(WAZUH_RANGE_HOURS, range)) {
    return;
  }
  wazuhRange = range;
  for (const button of wazuhRangeButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.wazuhRange === range));
  }
  loadWazuhDashboard();
}

function averageZabbixCpu(resourcePressure) {
  const values = (Array.isArray(resourcePressure) ? resourcePressure : [])
    .map((row) => row.cpu_used_percent)
    .filter((value) => typeof value === "number" && Number.isFinite(value));
  if (values.length === 0) {
    return null;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function renderZabbixWarnings(body) {
  const warnings = [];
  for (const value of [...(body.warnings || []), ...((body.health && body.health.warnings) || [])]) {
    if (typeof value === "string" && value && !warnings.includes(value)) {
      warnings.push(value);
    }
  }
  clearNode(zabbixWarningList);
  setHidden(zabbixWarnings, warnings.length === 0);
  for (const warning of warnings) {
    zabbixWarningList.appendChild(createTextElement("p", "warning-item", warning));
  }
}

function renderZabbixActiveProblems(problems) {
  clearNode(zabbixActiveProblemsBody);
  if (!Array.isArray(problems) || problems.length === 0) {
    const row = document.createElement("tr");
    const cell = createTextElement("td", "muted table-empty", "No active Zabbix problems reported.");
    cell.colSpan = 6;
    row.appendChild(cell);
    zabbixActiveProblemsBody.appendChild(row);
    return;
  }
  for (const problem of problems) {
    const row = document.createElement("tr");
    const hostNames = Array.isArray(problem.hosts)
      ? problem.hosts.map((host) => host.name || host.technical_name || host.host_id).join(", ")
      : "";
    row.appendChild(createTextElement("td", "", formatTimestamp(problem.started_at)));
    row.appendChild(createTextElement("td", "", formatStatus(problem.severity)));
    row.appendChild(createTextElement("td", "", String(problem.name || "Unnamed problem")));
    row.appendChild(createTextElement("td", "", hostNames || "Unmapped"));
    row.appendChild(createTextElement("td", "", problem.acknowledged ? "Yes" : "No"));
    row.appendChild(createTextElement("td", "", problem.suppressed ? "Yes" : "No"));
    zabbixActiveProblemsBody.appendChild(row);
  }
}

function renderZabbixTopHosts(hosts) {
  clearNode(zabbixTopHostsBody);
  if (!Array.isArray(hosts) || hosts.length === 0) {
    const row = document.createElement("tr");
    const cell = createTextElement("td", "muted table-empty", "No affected hosts are currently ranked.");
    cell.colSpan = 5;
    row.appendChild(cell);
    zabbixTopHostsBody.appendChild(row);
    return;
  }
  for (const host of hosts) {
    const row = document.createElement("tr");
    let peak = "Not reported";
    if (typeof host.peak_resource_percent === "number") {
      const resource = formatStatus(host.peak_resource || "resource");
      const filesystem = host.peak_filesystem ? ` ${host.peak_filesystem}` : "";
      peak = `${resource}${filesystem} · ${formatPercent(host.peak_resource_percent)}`;
    }
    row.appendChild(createTextElement("td", "", String(host.name || host.technical_name || host.host_id || "Unknown")));
    row.appendChild(createTextElement("td", "", formatStatus(host.highest_problem_severity)));
    row.appendChild(createTextElement("td", "table-number", formatCount(host.active_problem_count)));
    row.appendChild(createTextElement("td", "table-number", formatCount(host.unavailable_interface_count)));
    row.appendChild(createTextElement("td", "", peak));
    zabbixTopHostsBody.appendChild(row);
  }
}

function renderZabbixResourceLive(container, liveRows, trendRows, metric) {
  clearNode(container);
  const series = (Array.isArray(liveRows) ? liveRows : []).filter((row) => row.metric === metric);
  let rendered = 0;
  for (const item of series) {
    for (const point of (item.points || []).slice(-6)) {
      const row = document.createElement("div");
      row.className = "trend-row";
      row.appendChild(createTextElement("span", "trend-time", `${item.host_id} · ${formatTimestamp(point.observed_at)}`));
      row.appendChild(createTextElement("strong", "trend-count", formatPercent(point.used_percent)));
      container.appendChild(row);
      rendered += 1;
    }
  }
  if (rendered === 0) {
    const historical = (Array.isArray(trendRows) ? trendRows : []).filter((row) => row.metric === metric);
    for (const item of historical) {
      for (const point of (item.points || []).slice(-6)) {
        const row = document.createElement("div");
        row.className = "trend-row";
        row.appendChild(createTextElement("span", "trend-time", `${item.host_id} · ${formatTimestamp(point.observed_at)}`));
        row.appendChild(createTextElement("strong", "trend-count", formatPercent(point.average_used_percent)));
        container.appendChild(row);
        rendered += 1;
      }
    }
  }
  if (rendered === 0) {
    container.appendChild(createTextElement("p", "muted empty-message", `No ${metric} samples available.`));
  }
}

function formatBandwidth(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "Not available";
  }
  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toLocaleString(undefined, { maximumFractionDigits: 2 })} Gbps`;
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 2 })} Mbps`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toLocaleString(undefined, { maximumFractionDigits: 2 })} Kbps`;
  }
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} bps`;
}

function renderZabbixNetwork(container, rows, metricMode) {
  clearNode(container);
  const series = (Array.isArray(rows) ? rows : []).filter((row) =>
    metricMode === "latency" ? row.metric === "latency" : row.metric !== "latency"
  );
  let rendered = 0;
  for (const item of series) {
    for (const point of (item.points || []).slice(-4)) {
      const row = document.createElement("div");
      row.className = "trend-row";
      const interfaceLabel = item.interface ? ` · ${item.interface}` : "";
      const direction = item.metric === "latency" ? "" : ` · ${formatStatus(item.metric)}`;
      row.appendChild(createTextElement("span", "trend-time", `${item.host_id}${interfaceLabel}${direction} · ${formatTimestamp(point.observed_at)}`));
      const value = item.metric === "latency"
        ? `${Number(point.value).toLocaleString(undefined, { maximumFractionDigits: 2 })} ms`
        : formatBandwidth(point.value);
      row.appendChild(createTextElement("strong", "trend-count", value));
      container.appendChild(row);
      rendered += 1;
    }
  }
  if (rendered === 0) {
    container.appendChild(createTextElement("p", "muted empty-message", `No network ${metricMode} data available.`));
  }
}

const SVG_NAMESPACE = "http:" + "//www.w3.org/2000/svg";

function createSvgElement(tagName, attributes = {}, text = "") {
  const element = document.createElementNS(SVG_NAMESPACE, tagName);
  for (const [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, String(value));
  }
  if (text) {
    element.textContent = text;
  }
  return element;
}

function renderZabbixSystemInfo(topologyMaps) {
  clearNode(zabbixSystemInfoBody);
  const topology = Array.isArray(topologyMaps) ? topologyMaps[0] : null;
  const nodes = topology && Array.isArray(topology.nodes) ? topology.nodes : [];
  if (nodes.length === 0) {
    const row = document.createElement("tr");
    const cell = createTextElement("td", "muted table-empty", "No topology node information available.");
    cell.colSpan = 3;
    row.appendChild(cell);
    zabbixSystemInfoBody.appendChild(row);
    return;
  }
  for (const node of nodes) {
    const row = document.createElement("tr");
    row.appendChild(createTextElement("td", "", String(node.title || node.host_id || "Unknown")));
    row.appendChild(createTextElement("td", "", formatStatus(node.status)));
    row.appendChild(createTextElement("td", "table-number", formatCount(node.active_problem_count)));
    zabbixSystemInfoBody.appendChild(row);
  }
}

function renderZabbixTopology(topologyMaps) {
  clearNode(zabbixTopology);
  const topology = Array.isArray(topologyMaps) ? topologyMaps[0] : null;
  if (!topology || !Array.isArray(topology.nodes) || topology.nodes.length === 0) {
    zabbixTopology.appendChild(createTextElement("p", "muted empty-message", "No topology map is currently available."));
    return;
  }

  const width = Number(topology.width) || 1000;
  const height = Number(topology.height) || 600;
  const svg = createSvgElement("svg", {
    class: "topology-canvas",
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": `${topology.name || "Zabbix topology"}. ${topology.nodes.length} nodes and ${(topology.edges || []).length} connections.`,
    preserveAspectRatio: "xMidYMid meet",
  });
  const nodesById = new Map(topology.nodes.map((node) => [String(node.node_id), node]));

  for (const edge of topology.edges || []) {
    const source = nodesById.get(String(edge.source));
    const target = nodesById.get(String(edge.target));
    if (!source || !target) {
      continue;
    }
    const state = source.status === "unavailable" || target.status === "unavailable" ? "unavailable" : "available";
    const line = createSvgElement("line", {
      class: "topology-edge",
      x1: source.x,
      y1: source.y,
      x2: target.x,
      y2: target.y,
      "data-status": state,
    });
    line.appendChild(createSvgElement("title", {}, `${edge.label || "Connection"}: ${source.title} to ${target.title}; endpoint state ${state}.`));
    svg.appendChild(line);
  }

  for (const node of topology.nodes) {
    const group = createSvgElement("g", { class: "topology-node", transform: `translate(${node.x} ${node.y})` });
    group.appendChild(createSvgElement("title", {}, `${node.title}; ${formatStatus(node.status)}; ${formatCount(node.active_problem_count)} active problems.`));
    const nodeState = node.status === "available" && node.active_problem_count > 0 ? "available_problem" : node.status;
    group.appendChild(createSvgElement("circle", { r: 25, "data-status": nodeState }));
    group.appendChild(createSvgElement("text", { class: "topology-node-label", x: 0, y: 43, "text-anchor": "middle" }, String(node.title || node.host_id)));
    group.appendChild(createSvgElement("text", { class: "topology-node-state", x: 0, y: 60, "text-anchor": "middle" }, `${formatStatus(node.status)} · ${formatCount(node.active_problem_count)} problems`));
    svg.appendChild(group);
  }
  zabbixTopology.appendChild(svg);
}

function renderZabbixDashboard(body) {
  if (!body || !body.summary || !body.health) {
    throw new Error("Zabbix response is incomplete");
  }
  const summary = body.summary;
  zabbixMetricHosts.textContent = formatCount(summary.hosts_enabled);
  zabbixMetricProblems.textContent = formatCount(summary.problems_total);
  zabbixMetricUnreachable.textContent = formatCount(summary.interfaces_unavailable);
  zabbixMetricCpu.textContent = formatPercent(averageZabbixCpu(body.resource_pressure));
  zabbixMetricCritical.textContent = formatCount(summary.problems_disaster);

  renderDistribution(zabbixAvailability, [
    { name: "Hosts Enabled", count: summary.hosts_enabled },
    { name: "Hosts Disabled", count: summary.hosts_disabled },
    { name: "Hosts in Maintenance", count: summary.hosts_in_maintenance },
    { name: "Interfaces Available", count: summary.interfaces_available },
    { name: "Interfaces Unavailable", count: summary.interfaces_unavailable },
    { name: "Interfaces Unknown", count: summary.interfaces_unknown },
  ]);
  renderDistribution(zabbixProblemSeverity, [
    { name: "Not Classified", count: summary.problems_not_classified },
    { name: "Information", count: summary.problems_information },
    { name: "Warning", count: summary.problems_warning },
    { name: "Average", count: summary.problems_average },
    { name: "High", count: summary.problems_high },
    { name: "Disaster", count: summary.problems_disaster },
    { name: "Unknown", count: summary.problems_unknown },
  ]);
  renderZabbixActiveProblems(body.active_problems);
  renderZabbixTopHosts(body.top_affected_hosts);
  renderZabbixResourceLive(zabbixCpuLive, body.resource_live, body.resource_trends, "cpu");
  renderZabbixResourceLive(zabbixMemoryLive, body.resource_live, body.resource_trends, "memory");
  renderZabbixNetwork(zabbixNetworkLatency, body.network_live, "latency");
  renderZabbixNetwork(zabbixNetworkBandwidth, body.network_live, "bandwidth");
  renderZabbixTopology(body.topology_maps);
  renderZabbixSystemInfo(body.topology_maps);
  renderZabbixWarnings(body);

  const freshness = body.is_stale ? "Stale" : "Fresh";
  zabbixObservedAt.textContent = `Observed ${formatTimestamp(body.observed_at)}`;
  zabbixStatus.textContent = `${formatStatus(body.health.status)} · ${freshness}`;
  shellStatus.textContent = `Zabbix ${formatStatus(body.health.status)}`;
}

async function loadZabbixDashboard() {
  zabbixStatus.textContent = "Loading Zabbix data...";
  zabbixObservedAt.textContent = "";
  shellStatus.textContent = "Loading Zabbix";
  try {
    const { response, body } = await requestJson(API.zabbix);
    if (response.status === 401) {
      return;
    }
    if (!response.ok) {
      zabbixStatus.textContent = errorMessage(body, "Zabbix dashboard data is unavailable.");
      shellStatus.textContent = "Zabbix unavailable";
      return;
    }
    renderZabbixDashboard(body);
  } catch (_error) {
    zabbixStatus.textContent = "Zabbix dashboard data is unavailable.";
    shellStatus.textContent = "Zabbix unavailable";
  }
}

function renderSnipeItWarnings(body) {
  const warnings = [];
  for (const value of [...(body.warnings || []), ...((body.health && body.health.warnings) || [])]) {
    if (typeof value === "string" && value && !warnings.includes(value)) {
      warnings.push(value);
    }
  }
  clearNode(snipeItWarningList);
  setHidden(snipeItWarnings, warnings.length === 0);
  for (const warning of warnings) {
    snipeItWarningList.appendChild(createTextElement("p", "warning-item", warning));
  }
}

function renderSnipeItRecentActivity(activity) {
  clearNode(snipeItRecentActivityBody);
  if (!Array.isArray(activity) || activity.length === 0) {
    const row = document.createElement("tr");
    const cell = createTextElement("td", "muted table-empty", "No recent asset activity reported.");
    cell.colSpan = 5;
    row.appendChild(cell);
    snipeItRecentActivityBody.appendChild(row);
    snipeItActivityStatus.textContent = "No recent activity reported.";
    return;
  }

  for (const item of activity) {
    const row = document.createElement("tr");
    row.appendChild(createTextElement("td", "", String(item.action || "Unknown")));
    row.appendChild(createTextElement("td", "", String(item.asset || "Not reported")));
    row.appendChild(createTextElement("td", "", String(item.performed_by || "Not reported")));
    row.appendChild(createTextElement("td", "", String(item.target || "Not reported")));
    row.appendChild(createTextElement("td", "", String(item.occurred_at || "Not reported")));
    snipeItRecentActivityBody.appendChild(row);
  }
  snipeItActivityStatus.textContent = `${formatCount(activity.length)} recent records.`;
}

function renderSnipeItWarranty(items) {
  clearNode(snipeItWarrantyBody);
  if (!Array.isArray(items) || items.length === 0) {
    const row = document.createElement("tr");
    const cell = createTextElement("td", "muted table-empty", "No warranties expire within the next 90 days.");
    cell.colSpan = 5;
    row.appendChild(cell);
    snipeItWarrantyBody.appendChild(row);
    snipeItWarrantyStatus.textContent = "No upcoming warranty expiries reported.";
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");
    row.appendChild(createTextElement("td", "", String(item.asset_tag || "Not reported")));
    row.appendChild(createTextElement("td", "", String(item.serial || "Not reported")));
    row.appendChild(createTextElement("td", "", String(item.category || "Not reported")));
    row.appendChild(createTextElement("td", "", String(item.location || "Not reported")));
    row.appendChild(createTextElement("td", "", String(item.warranty_expires || "Not reported")));
    snipeItWarrantyBody.appendChild(row);
  }
  snipeItWarrantyStatus.textContent = `${formatCount(items.length)} assets expiring within 90 days.`;
}

function renderSnipeItDashboard(body) {
  if (!body || !body.summary || !body.health) {
    throw new Error("Snipe-IT response is incomplete");
  }

  const summary = body.summary;
  snipeItMetricTotal.textContent = formatCount(summary.assets_total);
  snipeItMetricAssigned.textContent = formatCount(summary.assets_assigned);
  snipeItMetricUnassigned.textContent = formatCount(summary.assets_unassigned);
  snipeItMetricDeployed.textContent = formatCount(summary.assets_deployed);
  snipeItMetricAvailable.textContent = formatCount(summary.assets_available);
  snipeItMetricMaintenance.textContent = formatCount(summary.assets_maintenance);
  snipeItMetricRetired.textContent = formatCount(summary.assets_retired);
  snipeItMetricMissingSerial.textContent = formatCount(summary.assets_missing_serial);
  snipeItMetricMissingTag.textContent = formatCount(summary.assets_missing_asset_tag);
  snipeItMetricWarrantyExpired.textContent = formatCount(summary.warranty_expired);
  snipeItMetricWarrantySoon.textContent = formatCount(summary.warranty_expiring_soon);

  renderDistribution(snipeItCategoryDistribution, body.category_distribution);
  renderDistribution(snipeItStatusDistribution, body.status_distribution);
  renderDistribution(snipeItCompanyDistribution, body.company_distribution);
  renderDistribution(snipeItLocationDistribution, body.location_distribution);
  renderSnipeItWarnings(body);

  const freshness = body.is_stale ? "Stale" : "Fresh";
  const lastSuccess = formatTimestamp(body.health.last_success_at);
  snipeItObservedAt.textContent = `Observed ${formatTimestamp(body.observed_at)}`;
  snipeItStatus.textContent = `${formatStatus(body.health.status)} · ${freshness} · Last successful sync ${lastSuccess}`;
  shellStatus.textContent = `Snipe-IT ${formatStatus(body.health.status)}`;
}

async function loadSnipeItDashboard() {
  snipeItStatus.textContent = "Loading Snipe-IT data...";
  snipeItObservedAt.textContent = "";
  shellStatus.textContent = "Loading Snipe-IT";
  try {
    const { response, body } = await requestJson(API.snipeIt);
    if (response.status === 401) {
      return;
    }
    if (!response.ok) {
      snipeItStatus.textContent = errorMessage(body, "Snipe-IT dashboard data is unavailable.");
      shellStatus.textContent = "Snipe-IT unavailable";
      return;
    }
    renderSnipeItDashboard(body);
  } catch (_error) {
    snipeItStatus.textContent = "Snipe-IT dashboard data is unavailable.";
    shellStatus.textContent = "Snipe-IT unavailable";
  }
}

async function loadSnipeItRecentActivity() {
  snipeItActivityStatus.textContent = "Loading recent activity...";
  try {
    const { response, body } = await requestJson(API.snipeItActivity);
    if (response.status === 401) {
      return;
    }
    if (!response.ok) {
      snipeItActivityStatus.textContent = errorMessage(body, "Recent activity is unavailable.");
      return;
    }
    renderSnipeItRecentActivity(body && body.activity);
  } catch (_error) {
    snipeItActivityStatus.textContent = "Recent activity is unavailable.";
  }
}

async function loadSnipeItWarranty() {
  snipeItWarrantyStatus.textContent = "Loading warranty data...";
  try {
    const { response, body } = await requestJson(API.snipeItWarranty);
    if (response.status === 401) {
      return;
    }
    if (!response.ok) {
      snipeItWarrantyStatus.textContent = errorMessage(body, "Warranty data is unavailable.");
      return;
    }
    renderSnipeItWarranty(body && body.warranty_expiry);
  } catch (_error) {
    snipeItWarrantyStatus.textContent = "Warranty data is unavailable.";
  }
}

function loadSnipeItPage() {
  loadSnipeItDashboard();
  loadSnipeItRecentActivity();
  loadSnipeItWarranty();
}

function renderRoute() {
  const config = PAGE_CONFIG[window.location.pathname] || PAGE_CONFIG["/app"];
  const isExecutive = config.view === "executive";
  const isWazuh = config.view === "wazuh";
  const isZabbix = config.view === "zabbix";
  const isSnipeIt = config.view === "snipeIt";
  pageEyebrow.textContent = config.eyebrow;
  pageTitle.textContent = config.title;
  pageDescription.textContent = config.description;
  phaseMessage.textContent = config.message || "";
  setHidden(executiveDashboardView, !isExecutive);
  setHidden(wazuhDashboardView, !isWazuh);
  setHidden(zabbixDashboardView, !isZabbix);
  setHidden(snipeItDashboardView, !isSnipeIt);
  setHidden(phaseCard, isExecutive || isWazuh || isZabbix || isSnipeIt);
  setHidden(legacyAiLink, !config.legacyAi);
  if (isExecutive) {
    shellStatus.textContent = "Loading Executive";
  } else if (isWazuh) {
    shellStatus.textContent = "Loading Wazuh";
  } else if (isZabbix) {
    shellStatus.textContent = "Loading Zabbix";
  } else if (isSnipeIt) {
    shellStatus.textContent = "Loading Snipe-IT";
  } else {
    shellStatus.textContent = "Application shell ready";
  }
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
  } else if (config.view === "wazuh") {
    loadWazuhDashboard();
  } else if (config.view === "zabbix") {
    loadZabbixDashboard();
  } else if (config.view === "snipeIt") {
    loadSnipeItPage();
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
for (const button of wazuhRangeButtons) {
  button.addEventListener("click", () => selectWazuhRange(button.dataset.wazuhRange));
}
initialize();
