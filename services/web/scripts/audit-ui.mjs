import { chromium } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const baseURL = process.env.AAP_UI_URL ?? "http://localhost:5173";
const edge =
  process.env.PLAYWRIGHT_BROWSER_PATH ??
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

// Every route, not every navigation entry. A ledger install does not link to Clients or
// Accreditations, and they are in here on purpose: `inv_existing_urls_survive` says a
// capability flag removes a link and never a route, and the way that regresses is
// somebody deleting the route to match the sidebar.
const staticRoutes = [
  "/",
  "/agents",
  "/discovery",
  "/runs",
  "/cost",
  "/tools",
  "/releases",
  "/evidence",
  "/graph",
  "/customers",
  "/engagements",
  "/accreditations",
  "/findings",
  "/policy",
  "/model-routing",
  "/control",
  "/platform-keys",
  "/assurance",
  "/sla",
  "/router",
  "/router/routes",
  "/router/simulate",
  "/router/compile",
  "/observe",
  "/observe/executions",
  "/observe/traces",
  "/observe/sessions",
  "/observe/analytics",
  "/observe/live",
  "/prompt",
  "/prompt/playground",
  "/evaluate",
  "/admin",
  "/admin/people",
  "/admin/access",
  "/admin/connections",
  "/admin/mcp",
  "/admin/audit",
  "/profile",
];

const safeControl =
  /overview|tools|access|client|graph|tree|swimlane|waterfall|details|activity|sessions|traces|executions|analytics|datasets|experiments|evaluators|scores|online rules|annotation|release gates|refresh/i;

async function api(path) {
  const response = await fetch(`${baseURL}${path}`);
  if (!response.ok) return null;
  return response.json();
}

function items(value) {
  if (Array.isArray(value)) return value;
  return value?.items ?? value?.value ?? [];
}

function firstId(value, ...names) {
  const row = items(value)[0];
  if (!row) return null;
  for (const name of names) {
    if (row[name]) return row[name];
    if (row.server?.[name]) return row.server[name];
  }
  return null;
}

async function dynamicRoutes() {
  const routes = [];
  const [
    agents,
    runs,
    releases,
    customers,
    engagements,
    accreditations,
    projects,
    servers,
  ] = await Promise.all([
    api("/v1/agents?limit=1"),
    api("/v1/operations/runs?days=30&limit=1"),
    api("/v1/releases?limit=1"),
    api("/v1/customers?limit=1"),
    api("/v1/engagements?limit=1"),
    api("/v1/accreditations?limit=1"),
    api("/v1/workload-credentials/projects?limit=1"),
    api("/v1/mcp/servers?limit=1&offset=0"),
  ]);

  const agentId = firstId(agents, "id");
  if (agentId) {
    routes.push(`/agents/${agentId}`);
    const versions = await api(`/v1/agents/${agentId}/versions?limit=1`);
    const versionId = firstId(versions, "id");
    if (versionId) routes.push(`/agents/${agentId}/versions/${versionId}`);
  }
  const runId = firstId(runs, "id");
  if (runId) routes.push(`/runs/${runId}`);
  const releaseId = firstId(releases, "id");
  if (releaseId) routes.push(`/releases/${releaseId}`);
  const customerId = firstId(customers, "id");
  if (customerId) routes.push(`/customers/${customerId}`);
  const engagementId = firstId(engagements, "id");
  if (engagementId) routes.push(`/engagements/${engagementId}`);
  const accreditationId = firstId(accreditations, "id");
  if (accreditationId) routes.push(`/accreditations/${accreditationId}`);
  const serverId = firstId(servers, "id");
  if (serverId) routes.push(`/admin/mcp/${serverId}`);

  const projectId = firstId(projects, "id");
  if (projectId) {
    const [executions, traces, sessions] = await Promise.all([
      api(`/v1/observe/projects/${projectId}/executions?limit=1&offset=0`),
      api(`/v1/observe/projects/${projectId}/traces?limit=1&offset=0`),
      api(`/v1/observe/projects/${projectId}/sessions?limit=1&offset=0`),
    ]);
    const executionId = firstId(executions, "execution_id", "id");
    const traceId = firstId(traces, "trace_id", "id");
    const sessionId = firstId(sessions, "session_id", "id");
    if (executionId) routes.push(`/observe/executions/${encodeURIComponent(executionId)}`);
    if (traceId) routes.push(`/observe/traces/${encodeURIComponent(traceId)}`);
    if (sessionId) routes.push(`/observe/sessions/${encodeURIComponent(sessionId)}`);
  }
  return routes;
}

async function auditRoute(page, route) {
  const badResponses = [];
  const failedRequests = [];
  const consoleErrors = [];
  const pageErrors = [];
  const responseListener = (response) => {
    if (response.status() >= 400) {
      badResponses.push({ status: response.status(), url: response.url() });
    }
  };
  const consoleListener = (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  };
  const errorListener = (error) => pageErrors.push(error.message);
  const failedRequestListener = (request) => {
    failedRequests.push({
      url: request.url(),
      error: request.failure()?.errorText ?? "request failed",
    });
  };
  page.on("response", responseListener);
  page.on("requestfailed", failedRequestListener);
  page.on("console", consoleListener);
  page.on("pageerror", errorListener);

  let navigationError = null;
  try {
    await page.goto(`${baseURL}${route}`, {
      waitUntil: "domcontentloaded",
      timeout: 10_000,
    });
    await page.waitForTimeout(250);
  } catch (error) {
    navigationError = error.message;
  }

  const body = await page.locator("body").innerText().catch(() => "");
  const visibleError = body
    .split("\n")
    .find((line) =>
      /something went wrong|could not load|unknown organisation|forbidden|failed to load|internal server error/i.test(
        line,
      ),
    );
  const shouldExerciseControls =
    route === "/evaluate" ||
    route.startsWith("/admin/mcp/") ||
    /^\/observe\/(executions|traces|sessions)\//.test(route);
  const buttons = shouldExerciseControls
    ? await page
        .locator("main button:visible")
        .evaluateAll((nodes) =>
          nodes.map((node) => ({
            text: (node.textContent ?? "").trim().replace(/\s+/g, " "),
            disabled: node.disabled,
          })),
        )
        .catch(() => [])
    : [];

  const clicked = [];
  const skipped = [];
  for (const button of buttons.slice(0, 8)) {
    if (!button.text || button.disabled || !safeControl.test(button.text)) {
      skipped.push(button.text);
      continue;
    }
    const candidate = page
      .locator("main button:visible")
      .filter({ hasText: button.text })
      .first();
    try {
      await candidate.click({ timeout: 2_000 });
      clicked.push(button.text);
      await page.waitForTimeout(50);
      await page.keyboard.press("Escape");
      if (new URL(page.url()).pathname !== route) {
        await page.goto(`${baseURL}${route}`, {
          waitUntil: "domcontentloaded",
          timeout: 10_000,
        });
      }
    } catch {
      skipped.push(button.text);
    }
  }

  page.off("response", responseListener);
  page.off("requestfailed", failedRequestListener);
  page.off("console", consoleListener);
  page.off("pageerror", errorListener);
  return {
    route,
    finalPath: new URL(page.url()).pathname,
    title: await page.locator("h1").first().innerText().catch(() => ""),
    navigationError,
    visibleError: visibleError ?? null,
    badResponses,
    failedRequests,
    consoleErrors,
    pageErrors,
    clicked: [...new Set(clicked)],
    skipped: [...new Set(skipped.filter(Boolean))],
  };
}

const browser = await chromium.launch({ headless: true, executablePath: edge });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
await context.addInitScript(() => {
  sessionStorage.setItem(
    "aap-oidc-session",
    JSON.stringify({
      accessToken: "dev.local",
      expiresAt: Date.now() + 60 * 60 * 1000,
      profile: {
        sub: "dev:local",
        email: "developer@localhost",
        name: "Local developer",
        preferredUsername: "developer@localhost",
        tenantId: "dev-tenant",
      },
      source: "dev",
    }),
  );
});
const page = await context.newPage();
page.setDefaultTimeout(3_000);

await page.goto(`${baseURL}/`, { waitUntil: "domcontentloaded" });
await page.waitForURL((url) => url.pathname === "/", { timeout: 10_000 });
await page.waitForTimeout(200);

const requestedRoutes = process.env.AAP_UI_ROUTES
  ?.split(",")
  .map((route) => route.trim())
  .filter(Boolean);
const routes = requestedRoutes?.length
  ? requestedRoutes
  : [...new Set([...staticRoutes, ...(await dynamicRoutes())])];
const results = [];
for (const route of routes) {
  process.stdout.write(`AUDIT ${route}\n`);
  results.push(await auditRoute(page, route));
}

const summary = {
  generatedAt: new Date().toISOString(),
  baseURL,
  routeCount: results.length,
  failedRoutes: results.filter(
    (result) =>
      result.navigationError ||
      result.visibleError ||
      result.badResponses.length ||
      result.failedRequests.length ||
      result.consoleErrors.length ||
      result.pageErrors.length,
  ).length,
  results,
};

await writeFile("ui-audit-report.json", `${JSON.stringify(summary, null, 2)}\n`);
await browser.close();

console.log(
  JSON.stringify(
    {
      routeCount: summary.routeCount,
      failedRoutes: summary.failedRoutes,
      failures: results
        .filter(
          (result) =>
            result.navigationError ||
            result.visibleError ||
            result.badResponses.length ||
            result.failedRequests.length ||
            result.consoleErrors.length ||
            result.pageErrors.length,
        )
        .map(({ route, visibleError, badResponses, failedRequests, consoleErrors, pageErrors }) => ({
          route,
          visibleError,
          badResponses,
          failedRequests,
          consoleErrors,
          pageErrors,
        })),
    },
    null,
    2,
  ),
);
