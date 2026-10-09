/**
 * Generates the Excalidraw design sketches in this folder.
 *
 *   node design/diagrams/build.mjs
 *
 * The diagrams are generated rather than hand-drawn so that a change to the
 * architecture is a small diff in this file instead of a manual redraw, and so
 * every box in every sketch keeps the same size, spacing and colour language.
 *
 * Open the .excalidraw files with excalidraw.com, the Excalidraw VS Code
 * extension, or Obsidian's Excalidraw plugin. They are plain JSON.
 */

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const OUT_DIR = dirname(fileURLToPath(import.meta.url));

/* --------------------------------------------------------------- primitives */

let idSeq = 0;
let seed = 987654321;
const nextId = (prefix = "el") => `${prefix}_${(idSeq += 1).toString(36)}`;
const nextSeed = () => (seed = (seed * 48271) % 2147483647);

const TONES = {
  slate: { stroke: "#1e1e1e", fill: "#f8f9fa", title: "#1e1e1e" },
  blue: { stroke: "#1971c2", fill: "#e7f5ff", title: "#1864ab" },
  green: { stroke: "#2f9e44", fill: "#ebfbee", title: "#2b8a3e" },
  amber: { stroke: "#f08c00", fill: "#fff9db", title: "#e67700" },
  red: { stroke: "#e03131", fill: "#fff5f5", title: "#c92a2a" },
  violet: { stroke: "#6741d9", fill: "#f3f0ff", title: "#5f3dc4" },
  cyan: { stroke: "#0c8599", fill: "#e3fafc", title: "#0b7285" },
  plain: { stroke: "#868e96", fill: "transparent", title: "#495057" },
};

const CHAR_W = 0.53; // Nunito, close enough for layout purposes
const LINE_H = 1.45;

function element(type, props) {
  return {
    id: props.id ?? nextId(type),
    type,
    x: 0,
    y: 0,
    width: 0,
    height: 0,
    angle: 0,
    strokeColor: "#1e1e1e",
    backgroundColor: "transparent",
    fillStyle: "solid",
    strokeWidth: 1,
    strokeStyle: "solid",
    roughness: 0,
    opacity: 100,
    groupIds: [],
    frameId: null,
    roundness: null,
    seed: nextSeed(),
    version: 1,
    versionNonce: nextSeed(),
    isDeleted: false,
    boundElements: [],
    updated: 1,
    link: null,
    locked: false,
    ...props,
  };
}

function textWidth(lines, size) {
  const longest = lines.reduce((max, line) => Math.max(max, line.length), 0);
  return Math.ceil(longest * size * CHAR_W) + 2;
}

function text(x, y, body, { size = 14, color = "#1e1e1e", align = "left", width } = {}) {
  const lines = Array.isArray(body) ? body : String(body).split("\n");
  const value = lines.join("\n");
  return element("text", {
    x,
    y,
    width: width ?? textWidth(lines, size),
    height: Math.ceil(lines.length * size * LINE_H),
    text: value,
    originalText: value,
    fontSize: size,
    fontFamily: 2,
    textAlign: align,
    verticalAlign: "top",
    containerId: null,
    lineHeight: LINE_H,
    autoResize: true,
    strokeColor: color,
  });
}

/** Wrap a long sentence to a character budget so panels stay inside their box. */
function wrap(sentence, maxChars) {
  const words = sentence.split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    if (!line.length) line = word;
    else if (`${line} ${word}`.length <= maxChars) line = `${line} ${word}`;
    else {
      lines.push(line);
      line = word;
    }
  }
  if (line.length) lines.push(line);
  return lines;
}

/**
 * A titled box with body lines. Returns geometry so arrows can attach to it.
 * Everything in these sketches is a panel; that is what keeps them legible.
 */
function panel(out, opts) {
  const {
    x,
    y,
    w,
    title,
    lines = [],
    tone = "slate",
    titleSize = 16,
    bodySize = 13,
    pad = 12,
    dashed = false,
    height,
  } = opts;
  const colours = TONES[tone];
  const bodyBudget = Math.floor((w - pad * 2) / (bodySize * CHAR_W));
  const body = lines.flatMap((line) =>
    line.length > bodyBudget ? wrap(line, bodyBudget) : [line],
  );
  const titleH = title ? Math.ceil(titleSize * LINE_H) : 0;
  const bodyH = body.length ? Math.ceil(body.length * bodySize * LINE_H) : 0;
  const gap = title && body.length ? 6 : 0;
  const h = height ?? pad * 2 + titleH + gap + bodyH;

  const rect = element("rectangle", {
    x,
    y,
    width: w,
    height: h,
    strokeColor: colours.stroke,
    backgroundColor: colours.fill,
    strokeStyle: dashed ? "dashed" : "solid",
    roundness: { type: 3 },
  });
  out.push(rect);
  if (title) out.push(text(x + pad, y + pad, title, { size: titleSize, color: colours.title }));
  if (body.length) {
    out.push(
      text(x + pad, y + pad + titleH + gap, body, {
        size: bodySize,
        color: "#343a40",
        width: w - pad * 2,
      }),
    );
  }
  return { id: rect.id, el: rect, x, y, w, h, cx: x + w / 2, cy: y + h / 2 };
}

/** A dashed container drawn behind its contents, with a caption. */
function zone(out, { x, y, w, h, title, tone = "plain" }) {
  const colours = TONES[tone];
  const rect = element("rectangle", {
    x,
    y,
    width: w,
    height: h,
    strokeColor: colours.stroke,
    backgroundColor: colours.fill,
    strokeStyle: "dashed",
    roundness: { type: 3 },
  });
  out.push(rect);
  if (title) out.push(text(x + 14, y + 12, title, { size: 15, color: colours.title }));
  return { id: rect.id, el: rect, x, y, w, h, cx: x + w / 2, cy: y + h / 2 };
}

function anchor(p, side) {
  if (side === "top") return [p.cx, p.y];
  if (side === "bottom") return [p.cx, p.y + p.h];
  if (side === "left") return [p.x, p.cy];
  return [p.x + p.w, p.cy];
}

function autoSides(a, b) {
  const dx = b.cx - a.cx;
  const dy = b.cy - a.cy;
  if (Math.abs(dy) >= Math.abs(dx)) {
    return dy >= 0 ? ["bottom", "top"] : ["top", "bottom"];
  }
  return dx >= 0 ? ["right", "left"] : ["left", "right"];
}

function arrow(out, a, b, opts = {}) {
  const { label, dashed = false, tone = "slate", from, to, both = false, labelDx = 0, labelDy = 0 } =
    opts;
  const [sideA, sideB] = from && to ? [from, to] : autoSides(a, b);
  const [x1, y1] = anchor(a, sideA);
  const [x2, y2] = anchor(b, sideB);
  const line = element("arrow", {
    x: x1,
    y: y1,
    width: Math.abs(x2 - x1),
    height: Math.abs(y2 - y1),
    points: [
      [0, 0],
      [x2 - x1, y2 - y1],
    ],
    strokeColor: TONES[tone].stroke,
    strokeStyle: dashed ? "dashed" : "solid",
    startBinding: { elementId: a.id, focus: 0, gap: 4 },
    endBinding: { elementId: b.id, focus: 0, gap: 4 },
    startArrowhead: both ? "arrow" : null,
    endArrowhead: "arrow",
    elbowed: false,
  });
  out.push(line);
  a.el.boundElements.push({ id: line.id, type: "arrow" });
  b.el.boundElements.push({ id: line.id, type: "arrow" });
  if (label) {
    const lines = Array.isArray(label) ? label : [label];
    const w = textWidth(lines, 12);
    out.push(
      text((x1 + x2) / 2 - w / 2 + labelDx, (y1 + y2) / 2 - 9 + labelDy, lines, {
        size: 12,
        color: "#495057",
      }),
    );
  }
  return line;
}

function heading(out, x, y, title, subtitle) {
  out.push(text(x, y, title, { size: 28, color: "#1e1e1e" }));
  if (subtitle) out.push(text(x, y + 38, subtitle, { size: 14, color: "#495057" }));
}

function note(out, x, y, w, lines, tone = "amber") {
  return panel(out, { x, y, w, title: lines[0], lines: lines.slice(1), tone, titleSize: 14 });
}

function save(name, elements) {
  const file = {
    type: "excalidraw",
    version: 2,
    source: "agent-assurance/design/diagrams/build.mjs",
    elements,
    appState: { gridSize: null, viewBackgroundColor: "#ffffff" },
    files: {},
  };
  writeFileSync(join(OUT_DIR, name), `${JSON.stringify(file, null, 2)}\n`, "utf8");
  writeFileSync(join(OUT_DIR, "preview", name.replace(/\.excalidraw$/, ".svg")), toSvg(elements), "utf8");
  return `${name} (${elements.length} elements)`;
}

/** Flat SVG rendering of the same elements, so a diagram can be reviewed in a browser
 *  or a pull request without opening Excalidraw. Excalidraw remains the editable source. */
function escapeXml(value) {
  return value.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function toSvg(elements) {
  const pad = 40;
  let maxX = 0;
  let maxY = 0;
  for (const el of elements) {
    maxX = Math.max(maxX, el.x + (el.width ?? 0));
    maxY = Math.max(maxY, el.y + (el.height ?? 0));
  }
  const body = elements
    .map((el) => {
      if (el.type === "rectangle") {
        const dash = el.strokeStyle === "dashed" ? ' stroke-dasharray="8 6"' : "";
        return `<rect x="${el.x}" y="${el.y}" width="${el.width}" height="${el.height}" rx="10" fill="${el.backgroundColor}" stroke="${el.strokeColor}" stroke-width="1.4"${dash}/>`;
      }
      if (el.type === "text") {
        const size = el.fontSize;
        const lines = el.text.split("\n");
        const spans = lines
          .map(
            (line, i) =>
              `<tspan x="${el.x}" dy="${i === 0 ? size * 0.85 : size * LINE_H}" xml:space="preserve">${escapeXml(line)}</tspan>`,
          )
          .join("");
        return `<text y="${el.y}" fill="${el.strokeColor}" font-family="Nunito, Segoe UI, Helvetica, sans-serif" font-size="${size}">${spans}</text>`;
      }
      if (el.type === "arrow") {
        const [[x1, y1], [x2, y2]] = el.points;
        const dash = el.strokeStyle === "dashed" ? ' stroke-dasharray="7 5"' : "";
        return `<line x1="${el.x + x1}" y1="${el.y + y1}" x2="${el.x + x2}" y2="${el.y + y2}" stroke="${el.strokeColor}" stroke-width="1.4"${dash} marker-end="url(#head-${el.strokeColor.slice(1)})"/>`;
      }
      return "";
    })
    .join("\n  ");
  const markers = [...new Set(elements.filter((e) => e.type === "arrow").map((e) => e.strokeColor))]
    .map(
      (colour) =>
        `<marker id="head-${colour.slice(1)}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${colour}"/></marker>`,
    )
    .join("\n    ");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${maxX + pad}" height="${maxY + pad}" viewBox="0 0 ${maxX + pad} ${maxY + pad}">
  <defs>
    ${markers}
  </defs>
  <rect width="100%" height="100%" fill="#ffffff"/>
  ${body}
</svg>
`;
}

/* ------------------------------------------------------- 01 · topology */

function topology() {
  const o = [];
  heading(
    o,
    40,
    40,
    "01 · Deployment topology",
    "SaaS control plane + customer-hosted data plane. Prompts, code, tool payloads and provider credentials never leave the customer boundary.",
  );

  zone(o, { x: 40, y: 120, w: 1500, h: 250, title: "VENDOR CLOUD — CONTROL PLANE (metadata only)", tone: "violet" });
  const ui = panel(o, { x: 70, y: 170, w: 250, title: "Admin console", tone: "violet", lines: ["Discovery · Governance", "Security · Activity · Audit", "Per-persona dashboards"] });
  const policy = panel(o, { x: 350, y: 170, w: 250, title: "Policy authoring", tone: "violet", lines: ["Versioned policy sets", "Simulation + diff", "Signs policy bundles"] });
  const registry = panel(o, { x: 630, y: 170, w: 250, title: "Asset registry", tone: "violet", lines: ["Models · endpoints · aliases", "MCP servers · capabilities", "Agents · data sources"] });
  const identity = panel(o, { x: 910, y: 170, w: 250, title: "Identity & access", tone: "violet", lines: ["Accounts · org units (DLs)", "Members · roles · grants", "Auth provider config"] });
  const insight = panel(o, { x: 1190, y: 170, w: 320, title: "Aggregates & billing", tone: "violet", lines: ["Rollups by org unit / member / model / tool", "Risk scores · alerts · evidence index", "No prompt bodies, no tool payloads"] });

  zone(o, { x: 40, y: 470, w: 1500, h: 420, title: "CUSTOMER VPC / DATA CENTRE / AIR-GAP — DATA PLANE (payloads stay here)", tone: "green" });
  // The two gateway lanes are offset rather than side by side, so every connector runs
  // through open space instead of over a neighbouring box.
  const modelGw = panel(o, { x: 320, y: 505, w: 270, title: "Model gateway", tone: "green", lines: ["OpenAI chat + responses", "Anthropic messages", "Gemini generateContent", "Alias → pinned endpoint"] });
  const mcpGw = panel(o, { x: 620, y: 700, w: 270, title: "MCP gateway", tone: "green", lines: ["tools/list filtered by grant", "tools/call re-validated", "Argument-level rules", "Approval + quarantine"] });
  const dlp = panel(o, { x: 950, y: 560, w: 250, title: "Inspection & DLP", tone: "green", lines: ["Secrets · PII · code", "Mask / tokenize / block", "Response-side scanning"] });
  const vault = panel(o, { x: 1240, y: 560, w: 270, title: "Local stores", tone: "green", lines: ["Token vault (customer KMS)", "Payload store, by digest", "Policy cache, offline"] });

  const clients = panel(o, { x: 70, y: 620, w: 230, title: "Clients", tone: "blue", lines: ["Cursor", "Claude Code", "Codex CLI", "Gemini CLI", "In-house agents / SDKs", "Base URL + platform key only"] });

  zone(o, { x: 40, y: 950, w: 1500, h: 170, title: "UPSTREAMS", tone: "plain" });
  const providers = panel(o, { x: 300, y: 1000, w: 430, title: "Model providers", tone: "amber", lines: ["Azure Foundry · AWS Bedrock · Vertex", "OpenAI · Anthropic · Google direct", "Self-hosted vLLM / Ollama"] });
  const upstreams = panel(o, { x: 760, y: 1000, w: 430, title: "MCP upstreams", tone: "amber", lines: ["Bitbucket / GitHub · Jira · Slack", "Nexus · Jenkins · Perforce", "Databases · internal APIs"] });
  const siem = panel(o, { x: 1220, y: 1000, w: 290, title: "Customer SIEM / IdP", tone: "cyan", lines: ["OTLP + audit export", "Entra / Okta / LDAP", "Secrets manager / KMS"] });

  arrow(o, clients, modelGw, { from: "right", to: "left" });
  arrow(o, clients, mcpGw, { from: "bottom", to: "left", dashed: true, label: ["MCP URL"], labelDy: -20 });
  arrow(o, modelGw, dlp, { from: "right", to: "left" });
  arrow(o, mcpGw, dlp, { from: "right", to: "left" });
  arrow(o, dlp, vault, { from: "right", to: "left" });
  arrow(o, modelGw, providers, { from: "bottom", to: "top" });
  arrow(o, mcpGw, upstreams, { from: "bottom", to: "top" });
  arrow(o, vault, siem, { from: "bottom", to: "top", dashed: true });
  arrow(o, policy, modelGw, { from: "bottom", to: "top", label: ["signed policy bundle"], tone: "violet", labelDx: -60 });
  arrow(o, vault, insight, { from: "top", to: "bottom", dashed: true, label: ["signed telemetry", "envelopes"], tone: "cyan", labelDx: 30 });

  note(o, 40, 1160, 730, [
    "Invariant — the control plane is not on the request path",
    "A control-plane outage must not open access. The data plane runs the last signed",
    "policy bundle, keeps enforcing, and buffers telemetry. Bundles carry an expiry;",
    "past expiry the data plane fails closed for regulated classes and read-only for the rest.",
  ]);
  note(o, 810, 1160, 730, [
    "Invariant — payload separation",
    "Prompt bodies, completions and tool arguments are written only to the customer-side",
    "payload store, referenced by digest. The control plane stores counts, digests, decisions",
    "and reason codes. Revealing a payload is a separate permission plus an audited approval.",
  ], "red");

  return save("01-deployment-topology.excalidraw", o);
}

/* ------------------------------------------- 02 · identity & onboarding */

function identity() {
  const o = [];
  heading(
    o,
    40,
    40,
    "02 · Identity, login and onboarding",
    "Authentication is a per-account configuration served by the API, never a build-time constant in the browser bundle.",
  );

  const idp = panel(o, { x: 40, y: 140, w: 300, title: "Identity sources", tone: "blue", lines: ["Entra ID / Okta (OIDC)", "Keycloak / PingFederate", "SAML 2.0 IdP", "LDAP / Active Directory bind", "Local accounts + TOTP (air-gap)", "Dev stub (never in production)"] });

  const adapter = panel(o, { x: 400, y: 140, w: 320, title: "Auth adapter (server side)", tone: "cyan", lines: ["auth_providers row per account", "JWKS cache · issuer + audience check", "Claim map: subject, email, name,", "groups, employee id, manager", "Domain → account discovery"] });

  const resolver = panel(o, { x: 780, y: 140, w: 330, title: "Identity resolver", tone: "cyan", lines: ["1. issuer+subject → member_identities", "2. else verified email → member", "3. else onboarding mode decides", "Never trusts client-supplied identity", "Emits one session bootstrap payload"] });

  const session = panel(o, { x: 1170, y: 140, w: 330, title: "Session bootstrap (one call)", tone: "green", lines: ["member · account · org units", "roles · permissions · visibility scopes", "navigation manifest · feature flags", "Shell renders once, from one response"] });

  arrow(o, idp, adapter);
  arrow(o, adapter, resolver);
  arrow(o, resolver, session);

  const modes = panel(o, { x: 40, y: 420, w: 1460, title: "Onboarding modes — chosen per account, not per build", tone: "amber", lines: [
    "SCIM 2.0 push          IdP creates, updates and deactivates members and group memberships. Authoritative. Preferred for SaaS and VPC.",
    "Directory sync (pull)  Scheduled read of LDAP/AD or Graph groups. Distribution lists become org units. Preferred on-prem.",
    "Just-in-time           First successful login provisions the member from verified claims. Requires a domain allowlist and a default org unit.",
    "Invite only            An admin invites an address; the first matching login claims the invitation. Default when no directory is connected.",
    "Bulk import            CSV or DL export for pilots. Rows are staged, previewed, then committed as invitations.",
  ] });

  const bootstrapAdmin = panel(o, { x: 40, y: 640, w: 460, title: "Administrator bootstrap", tone: "red", lines: ["Exactly one path per deployment:", "SaaS — signed provisioning token from onboarding", "VPC / on-prem — installer-sealed bootstrap credential", "Air-gap — offline licence + sealed credential", "First holder gets account_owner, single use,", "consumed and audited. No implicit owner from login."] });

  const dbIdentity = panel(o, { x: 540, y: 640, w: 470, title: "Tables that own identity", tone: "violet", lines: ["accounts, auth_providers, provider_claim_maps", "org_units (+ org_unit_closure), org_unit_managers", "members, member_identities, member_org_units", "directory_groups, group_org_unit_rules", "roles, role_permissions, access_grants", "member_invitations, session_events"] });

  const failure = panel(o, { x: 1050, y: 640, w: 450, title: "Failure taxonomy the UI must show", tone: "slate", lines: ["401 expired      silent renew, then re-auth", "401 unknown      \"not provisioned\" + request access", "403 module        empty state naming the role needed", "403 scope        \"outside your visibility\" + owner", "409 pending      \"awaiting approval\", with request id", "5xx / offline     retry with the reason code visible"] });

  arrow(o, modes, bootstrapAdmin, { from: "bottom", to: "top" });
  arrow(o, modes, dbIdentity, { from: "bottom", to: "top" });
  // Session → failure taxonomy is a relationship, not a flow, and any straight connector
  // between them would cut across the onboarding-modes panel. Adjacency carries it.

  note(o, 40, 900, 1460, [
    "Why the current console breaks — and what removes the class of bug",
    "Today the browser decides the auth mode from build-time VITE_OIDC_* variables, saves a session before onboarding has",
    "succeeded, keeps it in sessionStorage, and then loads each screen through separate queries that can each fail with 403.",
    "Any one of those failing paints \"unable to login\" or \"something went wrong\" with no reason. The fix is structural:",
    "GET /v1/auth/config decides the mode, POST /v1/auth/session completes onboarding before a session is persisted, and",
    "GET /v1/session/bootstrap returns identity, permissions and navigation together so a rendered shell is always consistent.",
  ], "red");

  return save("02-identity-and-onboarding.excalidraw", o);
}

/* --------------------------------------- 03 · hierarchy and DL mapping */

function hierarchy() {
  const o = [];
  heading(
    o,
    40,
    40,
    "03 · Org hierarchy, distribution lists and who sees what",
    "One tree, one closure table, one visibility rule. tens of DLs with hundreds of people each is the shape this must fit.",
  );

  const account = panel(o, { x: 620, y: 140, w: 300, title: "account", tone: "violet", lines: ["one customer · tenant boundary", "residency + retention defaults"] });

  const bu1 = panel(o, { x: 300, y: 290, w: 280, title: "org_unit · business unit", tone: "blue", lines: ["kind = business_unit", "manager: VP", "sees whole subtree"] });
  const bu2 = panel(o, { x: 960, y: 290, w: 280, title: "org_unit · business unit", tone: "blue", lines: ["kind = business_unit", "manager: VP", "sees whole subtree"] });

  const dlA = panel(o, { x: 120, y: 450, w: 300, title: "org_unit · DL ide-users", tone: "cyan", lines: ["kind = distribution_list", "source = directory_sync", "external_ref = DL object id", "213 members · 1 DL admin"] });
  const dlB = panel(o, { x: 450, y: 450, w: 300, title: "org_unit · DL data-platform", tone: "cyan", lines: ["kind = distribution_list", "source = scim", "184 members · 2 DL admins"] });
  const dlC = panel(o, { x: 960, y: 450, w: 300, title: "org_unit · DL … (30+ total)", tone: "cyan", lines: ["One row per DL", "Nesting allowed", "A member may sit in several"] });

  const member = panel(o, { x: 120, y: 660, w: 300, title: "member", tone: "green", lines: ["person · one row per employee", "status: invited/active/suspended", "primary_org_unit + memberships"] });
  const identityRow = panel(o, { x: 450, y: 660, w: 300, title: "member_identities", tone: "green", lines: ["issuer + subject (unique)", "email_verified · mfa", "many identities → one member"] });
  const workload = panel(o, { x: 780, y: 660, w: 300, title: "service_identities", tone: "green", lines: ["platform keys · agents · CI", "acts_for_member_id", "project + environment + scopes"] });
  const agentRow = panel(o, { x: 1110, y: 660, w: 300, title: "agents", tone: "green", lines: ["registered agent or client", "owner_member_id + org_unit", "cursor / claude-code / custom"] });

  arrow(o, account, bu1);
  arrow(o, account, bu2);
  arrow(o, bu1, dlA);
  arrow(o, bu1, dlB);
  arrow(o, bu2, dlC);
  arrow(o, dlA, member);
  arrow(o, member, identityRow, { from: "right", to: "left" });
  arrow(o, member, workload, { from: "bottom", to: "bottom", dashed: true, label: "acts_for", labelDy: 26 });
  arrow(o, workload, agentRow, { from: "right", to: "left" });

  const closure = panel(o, { x: 40, y: 860, w: 700, title: "Hierarchy storage — closure table, not recursive queries at read time", tone: "amber", lines: [
    "org_unit_closure(ancestor_id, descendant_id, depth)   one row per ancestor pair",
    "org_units.path  ltree/text   '/acct/bu/dl'  for prefix filters and index scans",
    "Rollup rows carry org_path so a manager view is a prefix match, not a join storm.",
    "Reparenting rewrites closure + path for the moved subtree in one transaction.",
  ] });

  const visibility = panel(o, { x: 780, y: 860, w: 720, title: "Visibility rule — one function, used by every query", tone: "red", lines: [
    "visible_members(viewer) =",
    "   {self}",
    " ∪ {members of org units where viewer holds a grant with scope=org_unit and subtree=true}",
    " ∪ {all members, when the viewer holds account-scoped activity:read_all}",
    "Every activity, cost and risk query is filtered by this set. No endpoint accepts a",
    "caller-supplied member filter without intersecting it with the caller's own scope.",
  ] });

  note(o, 40, 1110, 1460, [
    "Worked example — the DL case",
    "A DL admin on ide-users holds role dl_admin scoped to that org unit with subtree=true. They see those members' usage,",
    "cost, tool calls and denials, and can drill into any one of them; they see aggregate counts for the rest of the company",
    "and nothing identifiable. A VP above them sees both DLs and the union. A member sees only themselves. Security admins",
    "see every denial and incident company-wide but need a separate payload:reveal grant plus an approval to read any prompt.",
  ], "green");

  return save("03-hierarchy-and-visibility.excalidraw", o);
}

/* ------------------------------------------------- 04 · data model (ER) */

function dataModel() {
  const o = [];
  heading(
    o,
    40,
    40,
    "04 · Data model",
    "Postgres holds configuration and identity. ClickHouse holds activity. The two never share a query.",
  );

  const T = (x, y, w, name, cols, tone) => panel(o, { x, y, w, title: name, lines: cols, tone, titleSize: 14, bodySize: 12, pad: 10 });

  zone(o, { x: 40, y: 130, w: 700, h: 560, title: "POSTGRES · identity and tenancy", tone: "violet" });
  const tAccounts = T(70, 180, 300, "accounts", ["id pk", "slug · legal_name", "deployment_mode", "residency_class", "retention_profile"], "violet");
  const tAuth = T(400, 180, 310, "auth_providers", ["id pk · account_id fk", "kind oidc|saml|ldap|local", "issuer · client_id · jwks_uri", "claim_map jsonb · group_claim", "email_domains[] · precedence", "onboarding_mode · enabled"], "violet");
  const tUnits = T(70, 340, 300, "org_units", ["id pk · account_id fk", "parent_id fk · path", "kind bu|team|dl", "source scim|sync|manual", "external_ref · name"], "violet");
  const tClosure = T(400, 340, 310, "org_unit_closure", ["ancestor_id fk", "descendant_id fk", "depth int", "pk(ancestor, descendant)"], "violet");
  const tMembers = T(70, 500, 300, "members", ["id pk · account_id fk", "email uk · display_name", "status · employee_ref", "primary_org_unit_id fk", "manager_member_id fk"], "violet");
  const tIdent = T(400, 500, 310, "member_identities", ["id pk · member_id fk", "issuer + subject uk", "email_verified · mfa_verified", "last_login_at"], "violet");

  zone(o, { x: 780, y: 130, w: 720, h: 560, title: "POSTGRES · authorization", tone: "blue" });
  const tRoles = T(810, 180, 330, "roles", ["key pk · builtin bool", "permissions[]", "assignable_scopes[]", "separation_of_duty bool"], "blue");
  const tGrants = T(1160, 180, 320, "access_grants", ["id pk · account_id fk", "subject_kind member|team|", "  org_unit|service|agent", "subject_id · role_key fk", "scope_kind account|org_unit|", "  project|resource", "scope_id · subtree bool", "expires_at · revoked_at"], "blue");
  const tGroups = T(810, 400, 330, "directory_groups", ["id pk · account_id fk", "external_ref uk · name", "member_count · synced_at"], "blue");
  const tRules = T(1160, 400, 320, "group_org_unit_rules", ["id pk · group_id fk", "org_unit_id fk", "grant_role_key nullable", "priority int"], "blue");
  const tInvites = T(810, 540, 330, "member_invitations", ["id pk · email", "org_unit_id · role_key", "invited_by · expires_at", "claimed_by_identity_id"], "blue");
  const tApprovals = T(1160, 560, 320, "approvals", ["id pk · kind · subject", "requested_by · state", "decided_by · decided_at", "expires_at · token_hash"], "blue");

  zone(o, { x: 40, y: 730, w: 700, h: 470, title: "POSTGRES · registry and policy", tone: "green" });
  const tProviders = T(70, 780, 300, "model_providers", ["id pk · kind azure|bedrock|", "  vertex|openai|anthropic|local", "connection_id fk (vaulted)", "enabled · owner_member_id"], "green");
  const tEndpoints = T(400, 780, 310, "model_endpoints", ["id pk · provider_id fk", "base_url · deployment_ref", "region · zone", "residency_class pinned|zone|", "  global_unpinned", "attested_at · evidence_ref"], "green");
  const tAliases = T(70, 940, 300, "model_aliases", ["id pk · account_id fk", "alias uk  e.g. aap-balanced", "state draft|approved|retired", "capabilities · context_window"], "green");
  const tTargets = T(400, 940, 310, "alias_targets", ["alias_id fk · endpoint_id fk", "weight int · priority int", "mode cost|balanced|quality", "max_input_class", "failover_group"], "green");
  const tPolicies = T(70, 1080, 640, "policies / policy_bindings / policy_versions", ["id pk · account_id · kind model|mcp|data|budget", "document jsonb (compiled) · version int · signature", "binding: subject_kind + subject_id + org_unit + environment", "effective_from · effective_to · created_by · simulated_at"], "green");

  zone(o, { x: 780, y: 730, w: 720, h: 470, title: "POSTGRES · MCP, secrets, budgets", tone: "amber" });
  const tServers = T(810, 780, 330, "mcp_servers", ["id pk · slug uk · transport", "endpoint_url | command", "state draft|in_review|approved|", "  quarantined · trust_tier", "connection_id fk · owner_unit"], "amber");
  const tCaps = T(1160, 780, 320, "mcp_capabilities", ["id pk · server_id fk", "snapshot_id fk · name", "declared_* hints", "verified_risk · verified_write", "verified_irreversible", "arg_rules jsonb"], "amber");
  const tSnap = T(810, 960, 330, "mcp_snapshots", ["id pk · server_id fk", "capability_digest", "approved_at · approved_by", "superseded_at"], "amber");
  const tMcpGrants = T(1160, 960, 320, "mcp_grants", ["id pk · server_id fk", "subject_kind + subject_id", "capability_name nullable", "environments[] · permission", "requires_approval · pinned_snapshot"], "amber");
  const tSecrets = T(810, 1120, 330, "connections / secret_versions", ["provider + MCP credentials", "KMS-wrapped · never returned"], "amber");
  const tBudgets = T(1160, 1120, 320, "budgets / model_prices", ["scope + period + limit_micros", "price effective-dated per model"], "amber");

  zone(o, { x: 40, y: 1240, w: 1460, h: 300, title: "CLICKHOUSE · activity (append-only, partitioned by day, TTL to object storage)", tone: "cyan" });
  const tEvents = T(70, 1295, 440, "ai_events  — one row per governed action", ["event_id · occurred_at · account_id", "actor: member_id · service_identity_id · agent_id", "org_path  (denormalised for prefix filters)", "kind model.request | mcp.call | policy.decision", "model_alias · endpoint_id · region · residency_class", "server_slug · tool_name · arg_digest", "decision allow|redact|approve|deny · reason_code", "finding_kinds[] · tokens_in/out · cost_micros", "latency_ms · payload_ref (customer-side digest)"], "cyan");
  const tRollup = T(540, 1295, 440, "rollups  — materialised views, 1m / 1h / 1d", ["key: account, bucket, org_path, member,", "     agent, model_alias, server, tool, decision", "counts · tokens · cost_micros", "latency quantiles (t-digest state)", "unique actors (HLL state)", "denial counts by reason_code"], "cyan");
  const tGraph = T(1010, 1295, 460, "graph_edges  — the activity graph", ["from_kind+from_id → to_kind+to_id", "member → agent → model | server → tool → resource", "first_seen · last_seen · call_count", "data_classes[] · max_risk", "answers: who could reach what, and did"], "cyan");

  arrow(o, tAccounts, tUnits, { from: "bottom", to: "top" });
  arrow(o, tUnits, tMembers, { from: "bottom", to: "top" });
  arrow(o, tMembers, tIdent, { from: "right", to: "left" });
  arrow(o, tUnits, tClosure, { from: "right", to: "left" });
  arrow(o, tAccounts, tAuth, { from: "right", to: "left" });
  arrow(o, tRoles, tGrants, { from: "right", to: "left" });
  arrow(o, tGroups, tRules, { from: "right", to: "left" });
  arrow(o, tProviders, tEndpoints, { from: "right", to: "left" });
  arrow(o, tAliases, tTargets, { from: "right", to: "left" });
  arrow(o, tEndpoints, tTargets, { from: "bottom", to: "top", dashed: true });
  arrow(o, tServers, tCaps, { from: "right", to: "left" });
  arrow(o, tServers, tSnap, { from: "bottom", to: "top" });
  arrow(o, tCaps, tMcpGrants, { from: "bottom", to: "top" });
  arrow(o, tEvents, tRollup, { from: "right", to: "left", label: "MV" });
  arrow(o, tRollup, tGraph, { from: "right", to: "left", label: "MV" });

  note(o, 40, 1580, 1460, [
    "Rules that keep this schema honest",
    "Every tenant table carries account_id and is protected by row-level security; the app never filters tenancy in Python alone.",
    "Nothing in ClickHouse is a foreign key — ids are denormalised copies, because activity must survive config deletion.",
    "Cost is integer micros. Summing floats over a billion rows gives an answer that depends on summation order.",
    "Credentials live in connections/secret_versions as KMS-wrapped material and are never returned by any read endpoint.",
  ], "red");

  return save("04-data-model.excalidraw", o);
}

/* --------------------------------------- 05 · model request lifecycle */

function modelLifecycle() {
  const o = [];
  heading(
    o,
    40,
    40,
    "05 · Model request lifecycle",
    "Nine steps, all in the data plane. Target: under 12 ms of added policy overhead at p95, excluding provider time.",
  );

  const steps = [
    ["1 · Terminate", ["OpenAI /v1/chat/completions", "OpenAI /v1/responses", "Anthropic /v1/messages", "Gemini :generateContent", "Streaming passthrough"], "blue"],
    ["2 · Authenticate", ["Platform key → service identity", "acts_for member · agent · project", "environment · scopes", "Unknown key → 401, no upstream"], "blue"],
    ["3 · Resolve subject", ["member + org units", "grants + effective policy", "budget state · rate state", "All from local cache (≤5 s TTL)"], "cyan"],
    ["4 · Inspect input", ["Secrets · PII · source code", "Classify to data class", "Action: allow / mask / tokenize /", "block / route-internal / approve"], "amber"],
    ["5 · Select model", ["Requested alias or mode", "Filter endpoints by residency,", "capability, budget, health", "Weighted pick inside the filter"], "green"],
    ["6 · Dispatch", ["Provider adapter translates", "Credentials from vault, never client", "Retry + failover inside group", "Circuit breaker per endpoint"], "green"],
    ["7 · Inspect output", ["Secret + PII scan on response", "Detokenize inside boundary", "Injection / exfil heuristics"], "amber"],
    ["8 · Account", ["Tokens in/out from provider", "cost = tokens × effective price", "Budget decrement, atomic"], "violet"],
    ["9 · Emit", ["One ai_event with decision,", "reason code, finding kinds,", "payload digest + local body ref"], "violet"],
  ];

  let x = 40;
  const boxes = steps.map(([title, lines, tone]) => {
    const p = panel(o, { x, y: 150, w: 300, title, lines, tone, height: 190 });
    x += 320;
    return p;
  });
  boxes.forEach((b, i) => {
    if (i > 0) arrow(o, boxes[i - 1], b, { from: "right", to: "left" });
  });

  const deny = panel(o, { x: 40, y: 400, w: 620, title: "Deny path — always explains itself", tone: "red", lines: [
    "HTTP 403 with a machine reason code and a human sentence:",
    "  reason: data_class_blocked · policy: DATA-004 · class: customer_pii",
    "  destination: anthropic/eu-central-1 · alternative alias: aap-internal-secure",
    "The same text appears in the console, the audit row and the client error.",
    "A developer who is blocked must know what to do next without filing a ticket.",
  ] });

  const approve = panel(o, { x: 700, y: 400, w: 620, title: "Approval path — never a dead end", tone: "amber", lines: [
    "A high-risk request returns 409 with an approval id and a resume token.",
    "Approver is notified in the console and over Slack/Teams/email webhook.",
    "On approval the client retries with the token; the gateway re-checks policy",
    "(state can have changed) and then dispatches. Tokens are single use and expire.",
  ] });

  const residency = panel(o, { x: 40, y: 620, w: 1280, title: "Residency — the part that is usually claimed dishonestly", tone: "cyan", lines: [
    "A model name carries no location. Processing location is a property of the endpoint you call:",
    "  Azure Foundry    GlobalStandard → any Azure region · DataZoneStandard → US/EU/APAC zone · Standard → the deployment region only",
    "  AWS Bedrock      in-region endpoint → that region · geographic inference profile → within the geography · global profile → worldwide",
    "  Vertex AI        regional endpoint → that location · global endpoint may route elsewhere",
    "  OpenAI direct    residency depends on the account tier and must be configured, not assumed",
    "Therefore the gateway stores residency on model_endpoints (region, zone, residency_class, deployment_ref, evidence_ref, attested_at),",
    "and policy filters on that column. An endpoint that cannot be attested is labelled global_unpinned and is unusable for regulated classes.",
    "The console shows 'attested' with its evidence, or 'unverified'. It never renders a region we merely inferred as if it were proof.",
  ] });

  arrow(o, boxes[3], deny, { from: "bottom", to: "top", tone: "red" });
  arrow(o, boxes[4], approve, { from: "bottom", to: "top", tone: "amber" });

  return save("05-model-request-lifecycle.excalidraw", o);
}

/* ------------------------------- 06 · client wiring + model catalogue */

function clientsAndCatalogue() {
  const o = [];
  heading(
    o,
    40,
    40,
    "06 · Client wiring and model catalogue",
    "What each coding client actually lets an enterprise control, and how a new model reaches users without an engineer.",
  );

  const cursor = panel(o, { x: 40, y: 150, w: 350, title: "Cursor", tone: "blue", lines: [
    "Route:  Override OpenAI Base URL → our",
    "OpenAI-compatible endpoint, key = platform key.",
    "Caveat: the override currently carries all",
    "OpenAI-family traffic, including built-in picks.",
    "Org control: Admin API model access policy,",
    "disable personal BYOK, MCP server allowlist,",
    "permissions.json auto-run allowlist via MDM.",
    "Limit: client-side allowlists are advisory —",
    "enforcement has to be ours, server side.",
  ] });

  const claude = panel(o, { x: 410, y: 150, w: 350, title: "Claude Code", tone: "blue", lines: [
    "Route:  ANTHROPIC_BASE_URL + auth token,",
    "or the Bedrock/Vertex/Foundry base URLs.",
    "Org control: managed settings deliver",
    "availableModels (checked at the gateway too),",
    "permissions allow/ask/deny,",
    "allowManagedPermissionRulesOnly,",
    "allowedMcpServers + allowManagedMcpServersOnly,",
    "disableBypassPermissionsMode.",
    "Caveat: a delivered base URL can prompt the user.",
  ] });

  const codex = panel(o, { x: 780, y: 150, w: 350, title: "Codex CLI", tone: "blue", lines: [
    "Route:  ~/.codex/config.toml",
    "[model_providers.aap] base_url, env_key,",
    "wire_api = \"responses\".",
    "So our gateway must implement the Responses",
    "API, not only chat completions.",
    "Org control: provider keys are user-level;",
    "project configs cannot override them, which",
    "is useful — a repo cannot redirect traffic.",
  ] });

  const gemini = panel(o, { x: 1150, y: 150, w: 350, title: "Gemini CLI", tone: "blue", lines: [
    "Route:  GOOGLE_GEMINI_BASE_URL, or",
    "GOOGLE_VERTEX_BASE_URL for Vertex auth.",
    "Honoured through the genai SDK http options;",
    "HTTPS required off localhost, and the",
    "behaviour has moved between releases — pin",
    "a version in the rollout guide.",
    "Org control: thin. Treat the gateway plus MDM",
    "as the only real enforcement.",
  ] });

  const wiring = panel(o, { x: 40, y: 430, w: 1460, title: "One-click onboarding — the console generates all of this per member and environment", tone: "green", lines: [
    "Pick a client and an environment → the console issues a scoped platform key, prints the exact config, and offers an MDM bundle.",
    "It also runs a preflight: key valid · alias reachable · residency attested · MCP grants present · a live test call and tool list.",
    "If the preflight fails it names the missing step and links to it. 'It shows zero tools' must never be something a user has to debug.",
  ] });

  const discover = panel(o, { x: 40, y: 600, w: 300, title: "Catalogue job (hourly)", tone: "cyan", lines: ["Lists models per provider:", "Azure deployments, Bedrock", "foundation models, Vertex", "publishers, OpenAI /models,", "local runtime /v1/models"] });
  const candidate = panel(o, { x: 360, y: 600, w: 300, title: "Candidate rows", tone: "cyan", lines: ["New / changed / withdrawn", "Pulls context window, modality,", "price, deployment SKU, region", "Never auto-enabled"] });
  const review = panel(o, { x: 680, y: 600, w: 300, title: "Admin review", tone: "amber", lines: ["Diff view + provider evidence", "Set residency_class,", "max data class, cost ceiling", "Approve → alias target"] });
  const alias = panel(o, { x: 1000, y: 600, w: 240, title: "Aliases", tone: "green", lines: ["aap-fast", "aap-balanced", "aap-deep", "aap-internal-secure"] });
  const publish = panel(o, { x: 1260, y: 600, w: 240, title: "Rollout", tone: "green", lines: ["Bundle signed + versioned", "Clients see the new model", "with no config change"] });

  arrow(o, discover, candidate, { from: "right", to: "left" });
  arrow(o, candidate, review, { from: "right", to: "left" });
  arrow(o, review, alias, { from: "right", to: "left" });
  arrow(o, alias, publish, { from: "right", to: "left" });

  const routing = panel(o, { x: 40, y: 820, w: 720, title: "Routing rules an admin writes (no code)", tone: "violet", lines: [
    "subject: org_unit=ide-users, environment=prod",
    "mode_default: balanced          # cost | balanced | quality | residency_strict",
    "split:  aap-balanced 70%  ·  aap-deep 20%  ·  aap-internal-secure 10%",
    "hard_constraints:",
    "   residency: eu_zone_or_stricter",
    "   max_data_class: internal",
    "   monthly_budget_usd: 12000   # then degrade to aap-fast, then block",
    "overrides: member may request a specific alias if it satisfies the constraints",
  ] });

  const router = panel(o, { x: 800, y: 820, w: 700, title: "How the router decides", tone: "violet", lines: [
    "1. Filter  endpoints failing a hard constraint are removed — never overridden by weights.",
    "2. Score   quality/cost/latency from a rolling window per endpoint, not a static table.",
    "3. Pick    weighted choice with deterministic tie-break on (session, alias) so a",
    "           conversation stays on one endpoint unless it degrades.",
    "4. Track   actual split is reported against the target; drift shows as a metric.",
    "5. Degrade budget exhaustion and breaker trips walk down a declared ladder, and the",
    "           reason is attached to the response headers and the event.",
  ] });

  return save("06-clients-and-model-catalogue.excalidraw", o);
}

/* ------------------------------------------------- 07 · MCP governance */

function mcpGateway() {
  const o = [];
  heading(
    o,
    40,
    40,
    "07 · MCP onboarding, grants and tool blocking",
    "Three screens to onboard a server. One place that decides whether a tool call happens.",
  );

  const wizard = [
    ["Step 1 · Declare", ["Paste a URL or a command", "Pick transport: stdio, SSE,", "streamable HTTP", "Choose owner org unit,", "environments, credential"], "blue"],
    ["Step 2 · Discover", ["Worker connects and lists", "tools, resources, prompts", "Stores an immutable snapshot", "with a capability digest", "Health + latency recorded"], "cyan"],
    ["Step 3 · Classify", ["Declared hints kept separately", "from verified findings", "Set risk, write, irreversible,", "data classes, argument rules", "Templates pre-fill; a human confirms"], "amber"],
    ["Publish", ["Approve the snapshot", "Grant subjects", "Console emits client config", "Preflight proves it works"], "green"],
  ];
  let x = 40;
  const wizardBoxes = wizard.map(([title, lines, tone]) => {
    const p = panel(o, { x, y: 150, w: 350, title, lines, tone, height: 190 });
    x += 370;
    return p;
  });
  wizardBoxes.forEach((b, i) => i && arrow(o, wizardBoxes[i - 1], b, { from: "right", to: "left" }));

  const call = panel(o, { x: 40, y: 400, w: 700, title: "tools/call — the checks, in order, all fail closed", tone: "red", lines: [
    "1  platform key valid, not revoked, scope mcp:invoke",
    "2  server approved, not quarantined, environment matches",
    "3  a live grant exists for this subject and this capability",
    "4  the approved snapshot is the one pinned by the grant (no substitution)",
    "5  arguments validate against the declared schema",
    "6  argument rules pass: repo not in the protected set, SQL verb allowed,",
    "   path inside the allowed root, blast radius under the cap",
    "7  input scan: no secret or PII leaves in the arguments",
    "8  rate + concurrency budget for this subject",
    "9  verified write or irreversible → approval token required",
    "10 dispatch, then scan the response before it returns to the model",
  ] });

  const listing = panel(o, { x: 780, y: 400, w: 720, title: "tools/list — filtered, because absence is the best deny", tone: "green", lines: [
    "A caller is shown only the capabilities they hold a grant for, from the pinned",
    "snapshot. A tool they cannot use does not appear, so the model never proposes it",
    "and the developer never sees a mysterious refusal.",
    "",
    "The same filter governs the registry itself: a member with no grant cannot see the",
    "server exists. Discovery of the estate is a privilege (registry:read_all), not a default.",
    "",
    "tools/call never trusts the list. A client that fabricates a tool name is re-checked",
    "against grants, so a patched or malicious client gains nothing.",
  ] });

  const drift = panel(o, { x: 40, y: 700, w: 460, title: "Drift and rug-pull", tone: "amber", lines: [
    "Rediscovery compares digests.",
    "New or changed tool → stays invisible,",
    "raises a review item.",
    "Removed tool → grant flagged, not deleted.",
    "Definition changed under an approved name",
    "→ server moves to in_review automatically.",
  ] });

  const kill = panel(o, { x: 520, y: 700, w: 460, title: "Kill switch", tone: "red", lines: [
    "Quarantine takes effect within one cache TTL",
    "(≤ 5 s) for every caller and environment.",
    "Reason and actor are recorded; release is a",
    "separate permission from quarantine.",
    "Per-subject revoke is instant and audited.",
  ] });

  const audit = panel(o, { x: 1000, y: 700, w: 500, title: "What every call leaves behind", tone: "violet", lines: [
    "member · service identity · agent · session",
    "server · tool · argument digest (not the arguments)",
    "decision · reason code · risk · approval id",
    "latency · bytes · upstream status",
    "graph edges: member → agent → server → tool → resource",
  ] });

  note(o, 40, 940, 1460, [
    "Why enforcement cannot live in the client",
    "Cursor's MCP allowlist, Claude Code's permission rules and MDM-delivered files are all useful defence in depth, and we should",
    "generate them. None of them is a control we can attest to: they run on a machine the user administers, and the model itself",
    "chooses which tool to invoke with which arguments. The only place a customer can be told 'this cannot happen' is the gateway",
    "that owns the URL and holds the upstream credential. That is why the upstream credential must never reach the client.",
  ], "red");

  return save("07-mcp-governance.excalidraw", o);
}

/* -------------------------------------------------- 08 · data protection */

function dataProtection() {
  const o = [];
  heading(
    o,
    40,
    40,
    "08 · Secrets and PII in prompts",
    "Layered detection, an explicit action matrix, reversible tokens that never leave the customer boundary.",
  );

  const detect = panel(o, { x: 40, y: 150, w: 340, title: "Detect (layered, cheap first)", tone: "amber", lines: [
    "1 literal + prefix scan: sk-, ghp_, AKIA,",
    "  xoxb-, -----BEGIN, Bearer ey…",
    "2 structural: Luhn, IBAN, NI/SSN, UUID,",
    "  regex with checksum validation",
    "3 entropy: base64/hex blocks over a",
    "  threshold, filtered by context",
    "4 NER: person, address, phone, org",
    "5 schema-aware: known column and table",
    "  names from the data catalogue",
    "6 code-aware: secrets in diffs, .env,",
    "  connection strings, private keys",
    "Scan raw bytes and the JSON-decoded",
    "values — escaping is a bypass otherwise.",
  ] });

  const classify = panel(o, { x: 400, y: 150, w: 320, title: "Classify", tone: "cyan", lines: [
    "Finding → data class:",
    "  secret_material",
    "  customer_pii · employee_pii",
    "  health · financial",
    "  source_code · internal_doc",
    "  regulated_record",
    "Highest class wins for the request.",
    "Confidence is kept, and low-confidence",
    "findings can be set to annotate rather",
    "than block so the tool stays usable.",
  ] });

  const act = panel(o, { x: 740, y: 150, w: 400, title: "Act (per class, per destination)", tone: "red", lines: [
    "allow              nothing found, or class permitted",
    "annotate           record only, useful while tuning",
    "mask               irreversible ****, model loses the value",
    "tokenize           PERSON_1 / ACCT_7, reversible in boundary",
    "route_internal     send to a self-hosted model instead",
    "require_approval   human releases it, with justification",
    "block              refuse, name the policy and an alternative",
    "",
    "secret_material is block or mask. Never tokenize a",
    "credential: a reversible credential is still a credential.",
  ] });

  const vault = panel(o, { x: 1160, y: 150, w: 340, title: "Token vault (data plane only)", tone: "green", lines: [
    "token → ciphertext, AEAD under the",
    "customer KMS key, per-account key ring",
    "Stable within a session so the model can",
    "reason about 'the same person'",
    "TTL measured in hours, then unrecoverable",
    "Detokenize on the response path, inside",
    "the boundary, before the client sees it",
    "The control plane never receives the map",
  ] });

  arrow(o, detect, classify, { from: "right", to: "left" });
  arrow(o, classify, act, { from: "right", to: "left" });
  arrow(o, act, vault, { from: "right", to: "left" });

  const flow = panel(o, { x: 40, y: 560, w: 1460, title: "Round trip with reversible tokens", tone: "violet", lines: [
    "developer prompt      \"summarise churn risk for John Smith, account 4471-2288\"",
    "after inspection      \"summarise churn risk for <PERSON_1>, account <ACCOUNT_1>\"        ← what the provider receives",
    "provider response     \"<PERSON_1> is high risk because account <ACCOUNT_1> …\"",
    "after detokenisation  \"John Smith is high risk because account 4471-2288 …\"             ← what the developer receives",
    "recorded              finding kinds, classes, counts, digests, decision, policy id — never the values",
  ] });

  const limits = panel(o, { x: 40, y: 760, w: 700, title: "Stated limits — put these in the product, not only the docs", tone: "slate", lines: [
    "Detection reduces risk; it does not prove absence. Names, addresses and",
    "paraphrased secrets are missed by every detector, ours included.",
    "So the most sensitive classes must be policy-protected by destination",
    "(route to an internal model) rather than by redaction confidence.",
    "Every rule ships with a measured false-positive rate on the customer's own",
    "traffic in annotate mode before it is allowed to block.",
  ] });

  const alerts = panel(o, { x: 780, y: 760, w: 720, title: "Signals this produces for the security team", tone: "cyan", lines: [
    "repeat offender        same member, same class, N times in a window",
    "novel destination      a data class reaching a provider it has not before",
    "credential attempt     secret_material blocked — always an incident, not a metric",
    "exfil shape            tool output with a secret, then an outbound model call",
    "prompt hygiene         oversized context, whole-repo pastes, prod connection strings",
    "Each alert names the member, the agent, the policy, the reason code and the evidence,",
    "and links to the one-click actions: revoke, restrict, require approval, open a case.",
  ] });

  return save("08-data-protection.excalidraw", o);
}

/* -------------------------------------------- 09 · telemetry and scale */

function telemetry() {
  const o = [];
  heading(
    o,
    40,
    40,
    "09 · Activity pipeline and scale",
    "Design point: 100k governed requests per 30 minutes sustained (~56/s), 10× burst, ~4 tool calls each → ~3k events/s peak, ~25M events/day.",
  );

  const emit = panel(o, { x: 40, y: 160, w: 280, title: "Emit", tone: "green", lines: ["Gateway writes one envelope", "per decision, into a bounded", "in-process ring buffer", "Telemetry never blocks or fails", "a policy decision — it sheds"] });
  const collect = panel(o, { x: 340, y: 160, w: 280, title: "Collect", tone: "green", lines: ["Batched, compressed, signed", "At-least-once with event_id", "Disk spool survives restarts", "Backpressure → sample the", "allow path, keep every deny"] });
  const queue = panel(o, { x: 640, y: 160, w: 280, title: "Queue", tone: "cyan", lines: ["Kafka / Redpanda", "Partition by account_id", "Ordering per session only", "Retention long enough to", "replay a bad consumer"] });
  const consumers = panel(o, { x: 940, y: 160, w: 280, title: "Consumers", tone: "cyan", lines: ["a raw insert", "b rollup aggregation", "c risk + alerting", "d graph projection", "Independent offsets, so one", "slow consumer stalls nothing"] });
  const store = panel(o, { x: 1240, y: 160, w: 280, title: "Store", tone: "violet", lines: ["ClickHouse, day partitions", "ReplacingMergeTree on event_id", "ZSTD, low-cardinality dicts", "TTL: 30d hot → 400d cold", "Payload bodies stay in the", "customer object store"] });

  [emit, collect, queue, consumers, store].forEach((b, i, all) => i && arrow(o, all[i - 1], b, { from: "right", to: "left" }));

  const read = panel(o, { x: 40, y: 430, w: 720, title: "Read path — dashboards never touch raw events", tone: "amber", lines: [
    "Every console query hits a rollup keyed by (account, bucket, org_path, member,",
    "agent, alias, server, tool, decision). A manager view is a path prefix scan.",
    "Raw events are reachable only from a drill-down that already names a narrow",
    "window and one subject, and that read is itself audited.",
    "Aggregate endpoints are cursor-paginated and return totals from sketches, never",
    "from count(*) over a partition.",
  ] });

  const sketches = panel(o, { x: 800, y: 430, w: 700, title: "Algorithms, and why each one", tone: "amber", lines: [
    "t-digest        p50/p95/p99 latency mergeable across buckets",
    "HyperLogLog     unique active people per org unit without a distinct scan",
    "count-min       top-K tools and models under a fixed memory budget",
    "EWMA + MAD      per-subject baselines for anomaly alerts, robust to outliers",
    "closure table   hierarchy reads in one indexed join",
    "token bucket    per-subject rate limits in Redis, one round trip",
    "Bloom filter    de-duplicate secret fingerprints without storing secrets",
  ] });

  const cardinality = panel(o, { x: 40, y: 660, w: 720, title: "Cardinality discipline (the thing that actually kills these systems)", tone: "red", lines: [
    "Dimensions are enumerable or bucketed. member, agent, alias, server, tool, decision,",
    "reason_code: enumerable. Anything free-form — prompt text, request id, argument values —",
    "is never a rollup dimension. Beyond top-N per bucket, the tail folds into 'other' and the",
    "exact answer stays available in raw events for the retention window.",
  ] });

  const cost = panel(o, { x: 800, y: 660, w: 700, title: "Cost and token accounting", tone: "violet", lines: [
    "Tokens come from the provider response; when a provider omits them we record",
    "measured=false and estimate, and the UI says which.",
    "cost_micros = tokens × effective price from an effective-dated price book, computed",
    "at ingest and stored, so a later price change cannot silently rewrite history.",
    "A correction job recomputes a window and writes a new version with a reason.",
    "Budgets decrement in Redis for enforcement and reconcile against ClickHouse hourly.",
  ] });

  note(o, 40, 880, 1460, [
    "Capacity sizing to state in the proposal",
    "~25M events/day at ~350 bytes compressed ≈ 9 GB/day raw, ~1 GB/day after rollup, well inside a three-node ClickHouse cluster.",
    "Gateway cost is dominated by inspection, not policy: budget 4–8 ms for DLP on a 32 KB prompt and cache compiled rules per policy",
    "version. Policy evaluation is a hash lookup plus a bounded rule walk, sub-millisecond, and must stay that way — no database call",
    "on the request path, only the local cache with a 5 second TTL and an explicit invalidation channel.",
  ], "cyan");

  return save("09-telemetry-and-scale.excalidraw", o);
}

/* ------------------------------------------------- 10 · dashboards */

function dashboards() {
  const o = [];
  heading(
    o,
    40,
    40,
    "10 · Who sees which dashboard",
    "Same data, five products. What changes is the scope filter and the payload permission — never a second copy of the numbers.",
  );

  const personas = [
    ["Member (everyone)", ["My AI usage: requests, tokens, cost", "My tool calls and what they touched", "My denials, with the reason and the fix", "My prompt hygiene score", "Cannot see another person, at all"], "green"],
    ["DL admin / manager", ["Subtree rollups: cost, tokens, adoption", "Ranked members, tools, models", "Denials and incidents in the subtree", "Budget burn-down + forecast", "Drill to one member; no prompt bodies"], "blue"],
    ["Security admin", ["Every denial, incident and risk case", "Data-class flows by destination", "Agent and MCP blast radius", "Attack-path queries on the graph", "Payload reveal only with approval"], "red"],
    ["Platform / finance", ["Cost by org unit, model, provider", "Alias split versus target", "Endpoint health, latency, breakers", "Price-book changes and corrections", "No identifiable prompt content"], "violet"],
    ["Auditor", ["Immutable audit stream", "Evidence packs with integrity proofs", "Policy versions and who changed them", "Approval history", "Read-only, and cannot change scope"], "cyan"],
  ];
  let x = 40;
  const boxes = personas.map(([title, lines, tone]) => {
    const p = panel(o, { x, y: 150, w: 285, title, lines, tone, height: 220, titleSize: 15 });
    x += 295;
    return p;
  });

  const engine = panel(o, { x: 40, y: 420, w: 1420, title: "One aggregate service behind all five", tone: "amber", lines: [
    "GET /v1/insights/usage?group_by=org_unit|member|model|tool&window=…&scope=…",
    "The scope argument is intersected with the caller's visibility set on the server. A caller who asks for an org unit they",
    "cannot see gets 403 with reason scope_outside_grant — never an empty chart, which would read as 'no usage'.",
    "Payload fields are omitted unless the caller holds payload:reveal and a valid approval; the response says which fields",
    "were withheld and why, so the UI can render a lock with an explanation instead of a blank cell.",
  ] });

  boxes.forEach((b) => arrow(o, b, engine, { from: "bottom", to: "top", dashed: true }));

  const nav = panel(o, { x: 40, y: 640, w: 700, title: "Navigation is server-driven", tone: "green", lines: [
    "The bootstrap response returns the navigation manifest for this caller.",
    "A module the caller cannot use is absent, not present-and-broken.",
    "This removes the whole class of 'click a tab, get 403, see a red box'.",
    "Deep links to a hidden module render a purposeful 'request access' page.",
  ] });

  const states = panel(o, { x: 780, y: 640, w: 720, title: "Every screen ships four states", tone: "slate", lines: [
    "loading   skeleton matching the final layout, no spinner-in-a-box",
    "empty     what this screen is for, and the one action that fills it",
    "error     the reason code, the human sentence, and a retry that works",
    "data      the thing itself, with the freshness of the numbers stated",
    "A screen without all four is not done, and the UI test asserts each one.",
  ] });

  return save("10-dashboards-and-access.excalidraw", o);
}

/* ------------------------------------------------------ 11 · roadmap */

function roadmap() {
  const o = [];
  heading(
    o,
    40,
    40,
    "11 · Development sequence",
    "One active ledger-first program. The old P0–P9 prompts are historical and must not be executed.",
  );

  const phases = [
    ["F0 · console contract", ["Finish revision 0022", "Server-side auth session", "One bootstrap + typed errors", "Gate: browser never exchanges", "tokens; no reasonless error"], "red"],
    ["F1 · schema", ["0023 runtime identity", "0024 agent_actions ledger", "RLS + append-only + partitions", "Gate: fresh/existing upgrade", "and privacy invariants pass"], "violet"],
    ["F2 · UI structure", ["One shell and nav source", "Reuse Observe + admin UI", "Ledger home empty states", "Gate: Observe works with", "no project selected"], "blue"],
    ["M1 · identity chain", ["Instance, agent session, task", "Human root + delegation", "Extend existing agent detail", "Gate: every instance resolves", "to one accountable human"], "blue"],
    ["M3 · action ingest", ["Claude Code first", "Cursor before the demo", "aap.action.v1, no payloads", "Gate: both clients query as", "graded content-free actions"], "green"],
    ["M4 · discovery", ["Read-only hooks", "Shadow agents", "Credential-shaped reads", "Gate: AP-1 path detected", "without blocking work"], "amber"],
    ["M2 · visibility", ["0025 org-unit closure", "0026 grants diff guard", "Server-driven navigation", "Gate: sibling units cannot", "see each other's actions"], "blue"],
    ["M5 · MVP console", ["Action list + reconstruction", "Coverage denominator A–E", "Session timeline + discovery", "Gate: investigator rebuilds", "one action end to end"], "green"],
    ["V1 · enforce", ["Cedar simulation first", "Grade-B hook veto", "MCP capability + broker", "Gate: narrow real prevention", "with honest grade"], "amber"],
    ["P · package", ["Customer data plane", "Self-hosted + air-gap profile", "Signed rollback-safe bundles", "Gate: no payload leaves", "customer boundary"], "cyan"],
  ];

  let x = 40;
  let y = 150;
  phases.forEach(([title, lines, tone], i) => {
    if (i === 5) {
      x = 40;
      y = 470;
    }
    const p = panel(o, { x, y, w: 285, title, lines, tone, height: 260, titleSize: 15 });
    x += 295;
    return p;
  });

  note(o, 40, 760, 1420, [
    "How to use this plan",
    "Paste one active file from design/prompts/README.md into a fresh session. F1 and F2 may overlap only because F2 adds no tables.",
    "The critical validation is M3: if Claude Code and Cursor cannot map to one content-free event contract, stop and revise the",
    "capability abstraction. Do not build a gateway, ClickHouse pipeline, DLP stack or cost system to make the MVP feel larger.",
    "A slice closes only when its gate is demonstrated and PROJECT_STATE.md records migrations as written versus actually applied.",
  ], "green");

  return save("11-phase-roadmap.excalidraw", o);
}

/* --------------------------------------------- 12 · enforcement grades */

function enforcementGrades() {
  const o = [];
  heading(
    o,
    40,
    40,
    "12 · Enforcement grades",
    "Every control we ship carries a grade, and every number in the console says which grade it came from. This is the honesty mechanism the product is sold on.",
  );

  const grades = [
    ["A · mediated", ["the call cannot happen", "without passing through us", "", "MCP tools via our gateway", "CI and in-house agents", "in-path egress proxy"], "green"],
    ["B · interposed", ["the client asks us before", "it acts, and honours a veto", "", "Claude Code PreToolUse [B-31]", "Cursor hooks [B-33]", "bypass: run another client"], "blue"],
    ["C · attested", ["your vendor enforces it and", "we verify it is still set", "", "Cursor enterprise MCP", "allowlist [B-42]", "Copilot AI Controls [B-36]"], "cyan"],
    ["D · observed", ["we learn about it afterwards", "", "Cursor prompts resolve in", "their cloud before they", "reach us [B-41]", "evidence, not prevention"], "amber"],
    ["E · uncovered", ["we cannot see it and cannot", "stop it", "", "a personal key on an", "unmanaged laptop, a local", "model, another client"], "red"],
  ];

  let x = 40;
  grades.forEach(([title, lines, tone]) => {
    panel(o, { x, y: 150, w: 272, title, lines, tone, height: 200, titleSize: 15 });
    x += 282;
  });

  panel(o, { x: 40, y: 400, w: 1400, title: "What each client can actually be held to — researched September 2026", tone: "slate", lines: [
    "client            model traffic          tool calls                     configuration          usage",
    "Claude Code       A  our base URL        A  MCP  +  B  hooks            C  managed settings    D  OTLP",
    "Cursor            D  their cloud only    A  MCP  +  B  hooks            C  dashboard policy    D  Admin API",
    "Copilot           E  no in-app redirect  C  MCP policy                  C  AI Controls         D  metrics API",
    "Codex CLI         A  openai_base_url     B  tool_decision               E  no vendor MDM       D  OTEL",
    "Gemini CLI        A  base URL            B  sandbox                     C  system settings     D",
    "CI and in-house   A                      A                              A  your infrastructure A",
  ] });

  note(o, 40, 640, 1400, [
    "The rule this diagram exists to enforce",
    "A coverage figure without a denominator does not ship. \"1,284 actions governed\" is not a number; \"1,284 of an estimated 1,610,",
    "of which 402 are grade D observation only and 180 are grade E we cannot see\" is a number. The grade is a mandatory column on",
    "every decision row, and a row whose grade is unknown is counted as E. This is the single habit that survives first contact with a",
    "CISO who has already been sold a control that turned out to be a dashboard.",
  ], "amber");

  return save("12-enforcement-grades.excalidraw", o);
}

/* ----------------------------------------------- 13 · capability model */

function capabilityModel() {
  const o = [];
  heading(
    o,
    40,
    40,
    "13 · Capability governance",
    "MCP becomes one row in a registry of capability kinds, not the architecture. The chain below is identical for every kind.",
  );

  const stages = [
    ["1 · definition", ["one named thing an agent", "can do", "kind · id · source · verbs", "argument shape", "digest of its description —", "that text is attacker input"], "blue"],
    ["2 · risk", ["ours first, yours final", "write? destructive?", "reversible? audience?", "data classes reachable", "blast radius if confused", "your override always wins"], "cyan"],
    ["3 · grant", ["who may invoke, and how", "subject · selector", "argument rules", "max_taint", "expiry — always", "no permanent exception"], "green"],
    ["4 · invocation", ["ordered, at call time", "instance → delegation →", "grant → taint → args →", "credential lease", "unparseable arg = deny", "decision carries its grade"], "amber"],
    ["5 · evidence", ["one envelope aap.action.v1", "identity chain + decision", "facets, never raw args", "hash-chained; gaps show", "joins to the code change"], "violet"],
  ];

  let x = 40;
  const boxes = stages.map(([title, lines, tone]) => {
    const p = panel(o, { x, y: 160, w: 232, title, lines, tone, height: 200, titleSize: 15 });
    x += 292;
    return p;
  });
  for (let i = 0; i < boxes.length - 1; i += 1) {
    arrow(o, boxes[i], boxes[i + 1], { from: "right", to: "left" });
  }

  panel(o, { x: 40, y: 420, w: 1400, title: "The registry of kinds — MCP is one row in it, not the model itself", tone: "slate", lines: [
    "kind             what it is                           where we can stand             why it matters",
    "mcp.tool         a tool on an MCP server              in path                        the 2025 design assumed this was all of it",
    "shell.exec       Bash, Run, a terminal                client hook, sandbox           step 4 of the reference incident",
    "net.http         curl, fetch, a raw SDK call          client hook, egress proxy      step 5 — the exfiltration path nobody models",
    "fs.read          reading files and secrets            client hook                    step 3 — .env, ~/.aws, ~/.ssh, CI tokens",
    "fs.write         writing files                        client hook                    persistence and configuration poisoning",
    "vcs.write        commit, push, open a PR, merge       provider API + hook            the join to the SDLC record",
    "cloud.api        AWS / Azure / GCP control plane      credential scope               often grade C when nothing else works",
    "db.query         SQL and warehouse access             proxy                          read scope, row limits, masking",
    "agent.delegate   hand work to a sub-agent             in path                        depth cap; authority only ever narrows",
    "memory.write     what the agent is allowed to keep    in path                        poisoning and cross-session leakage",
  ] });

  note(o, 40, 720, 1400, [
    "Why the abstraction moved up a level",
    "On 25 April 2026 an agent deleted a production database and its volume-level backups in nine seconds. The path was: read a",
    "long-lived token off the workspace filesystem, build a curl command, call a GraphQL mutation. Three capability kinds, none of",
    "them MCP. An MCP gateway was not on that path and neither was a model gateway. Governing the kind rather than the protocol is",
    "the difference between a control and a demonstration.",
  ], "amber");

  return save("13-capability-model.excalidraw", o);
}

/* ------------------------------------------ 14 · agent identity chain */

function agentIdentityChain() {
  const o = [];
  heading(
    o,
    40,
    40,
    "14 · Agent identity chain",
    "Seven links, because six of them are the ones an investigation asks for and the seventh is the thing being authorized.",
  );

  const chain = [
    ["human · the accountable root", "violet"],
    ["agent · the named workload", "blue"],
    ["agent version · what is approved", "blue"],
    ["agent instance · one running copy", "cyan"],
    ["session · carries the taint", "amber"],
    ["task · one unit of work", "amber"],
    ["action · the authorization unit", "green"],
  ];

  const links = chain.map(([title, tone], i) =>
    panel(o, { x: 40, y: 150 + i * 84, w: 340, title, tone, height: 54, titleSize: 15 }),
  );
  for (let i = 0; i < links.length - 1; i += 1) {
    arrow(o, links[i], links[i + 1], { from: "bottom", to: "top" });
  }

  panel(o, { x: 430, y: 150, w: 490, height: 190, title: "Who is responsible for an AI action", tone: "violet", lines: [
    "Every action resolves to exactly one human at the root.",
    "`root_human_basis` records why that human is there:",
    "interactive · scheduled_by · approved_by · owner_of_record.",
    "A job that fires at 03:00 is attributed to its owner, and the",
    "evidence says owner_of_record rather than implying that",
    "somebody was at a keyboard. A service identity may never",
    "be the root of a chain.",
  ] });

  panel(o, { x: 430, y: 370, w: 490, height: 160, title: "What gets approved is the version", tone: "green", lines: [
    "An agent is a name. An agent version is a composition",
    "digest: system prompt, tool set, MCP snapshot, model,",
    "memory scopes. Approval binds to the digest.",
    "A changed digest is a new version, and it is unapproved",
    "until a human approves it.",
  ] });

  panel(o, { x: 430, y: 560, w: 490, height: 170, title: "The instance is what you revoke", tone: "cyan", lines: [
    "One running copy: this laptop, this CI job, this container.",
    "It registers before it may act, and it carries the grade of",
    "enforcement actually available to it — which is how a report",
    "can say \"B here, D there\" instead of one average that is true",
    "nowhere. Revocation targets an instance, a session or a lease.",
  ] });

  panel(o, { x: 950, y: 150, w: 490, height: 190, title: "The credential is the real control", tone: "blue", lines: [
    "The broker issues, per task: short-lived, audience-bound",
    "(RFC 8707), sender-constrained (RFC 9449 / RFC 8705),",
    "scoped to the least authority the task declared it needs.",
    "This is the one control that survives a bypassed path.",
    "A stolen lease is narrow, expiring and attributable.",
    "It is also the direct answer to the reference incident,",
    "whose root cause was a long-lived token found on disk.",
  ] });

  panel(o, { x: 950, y: 370, w: 490, height: 160, title: "Taint travels with the session", tone: "amber", lines: [
    "A session that has ingested untrusted content is tainted.",
    "Taint does not block. It reduces what the session may do:",
    "grants carry max_taint, and a tainted session loses the",
    "capabilities whose ceiling it has passed — usually the",
    "destructive ones and the ones that reach the internet.",
  ] });

  panel(o, { x: 950, y: 560, w: 490, height: 170, title: "What this model does not claim", tone: "red", lines: [
    "It does not stop prompt injection. A 2026 formal result",
    "argues perfect prevention is unachievable at the model",
    "layer, and adaptive attacks beat deployed commercial",
    "detectors well above 90% while those detectors report",
    "near zero under static evaluation. What this model does",
    "is shrink the reach of a compromised session.",
  ] });

  note(o, 40, 790, 1400, [
    "The one-line test for this document",
    "Pick any action in the ledger. You must be able to name the human, the agent version and its composition digest, the instance",
    "and the machine it ran on, the session and whether it was tainted, the task and where it came from, the grant that permitted it,",
    "the credential lease it used, the policy version that decided it, and the enforcement grade of that decision. If any of those is",
    "missing, the ledger is telemetry rather than evidence, and it will not survive an investigation.",
  ], "green");

  return save("14-agent-identity-chain.excalidraw", o);
}

/* ----------------------------------------------------- 15 · threat paths */

function threatPaths() {
  const o = [];
  heading(
    o,
    40,
    40,
    "15 · The reference attack path",
    "25 April 2026 · a coding agent destroyed a production database and its volume-level backups in nine seconds.",
  );

  const steps = [
    ["1 · routine task", ["working in staging", "hit a credential", "mismatch"], "slate"],
    ["2 · it decided", ["delete the volume", "nobody asked it to", "no approval existed"], "amber"],
    ["3 · fs.read", ["searched the workspace", "found a long-lived", "account-scoped token", "in an unrelated file"], "red"],
    ["4 · shell.exec", ["constructed a curl", "command against the", "provider control plane"], "red"],
    ["5 · net.http", ["called the volumeDelete", "GraphQL mutation", "over public HTTPS"], "red"],
    ["6 · destruction", ["production database", "and its backups", "elapsed: nine seconds"], "red"],
  ];

  let x = 40;
  const boxes = steps.map(([title, lines, tone]) => {
    const p = panel(o, { x, y: 170, w: 196, title, lines, tone, height: 150, titleSize: 14 });
    x += 241;
    return p;
  });
  for (let i = 0; i < boxes.length - 1; i += 1) {
    arrow(o, boxes[i], boxes[i + 1], { from: "right", to: "left" });
  }

  panel(o, { x: 40, y: 380, w: 1400, title: "What the model gateway and the MCP gateway saw", tone: "red", lines: [
    "Nothing. A model gateway sits on the path of a model request, and this was not one. An MCP gateway sits on the path of a",
    "tools/call, and this was not one either. The destructive action travelled Bash → curl → public HTTPS API. Both of the",
    "enforcement points in the earlier design were off the path, and the only audit trail was the agent's own later confession.",
  ] });

  const interventions = [
    ["A · the credential", ["A per-task lease could not have carried", "volumeDelete against a production project.", "The real token was long-lived,", "account-scoped and readable from the", "agent's own workspace. This is the control", "that would have stopped it outright."], "green"],
    ["B · the hook", ["A PreToolUse veto on shell.exec matching a", "destructive verb against a production", "audience, on hardware the customer", "administers. Real prevention, and honestly", "bypassable by running a different client —", "which is exactly why it is graded B."], "blue"],
    ["D · the ledger", ["fs.read of a credential-shaped file, then", "net.http to a provider control plane, inside", "nine seconds, from one session. That is a", "detection, an alert and a revocation.", "It is not a prevention, and we will not", "describe it as one."], "amber"],
  ];
  let ix = 40;
  interventions.forEach(([title, lines, tone]) => {
    panel(o, { x: ix, y: 520, w: 453, title, lines, tone, height: 175, titleSize: 15 });
    ix += 473;
  });

  panel(o, { x: 40, y: 730, w: 1400, title: "Bypass taxonomy — stated plainly, because a control that can be walked around must say so", tone: "slate", lines: [
    "bypass                          probability   impact   detectability              what actually holds",
    "personal API key, own laptop    high          high     D  config attestation      device posture, and credential scoping",
    "provider-native SDK, direct     high          medium   D  netflow and billing     egress policy on a managed network",
    "local model, no network at all  medium        medium   E  none                    nothing — say so, and size it",
    "a different agent framework     medium        high     D  process inventory       registration required before credentials",
    "unregistered MCP over stdio     medium        high     B  client allowlist        enterprise policy replaces user config",
    "curl inside an allowed shell    high          high     B  hook on shell.exec      the credential lease is the only backstop",
    "DoH, alternate DNS, IPv6        low           medium   E  none                    customer network controls, not ours",
  ] });

  return save("15-threat-paths.excalidraw", o);
}

/* ---------------------------------------- 16 · MVP schema and UI blueprint */

function mvpBlueprint() {
  const o = [];
  heading(
    o,
    40,
    40,
    "16 · MVP schema and UI blueprint",
    "What is reused, what F1 adds, and how the existing console becomes the action ledger without building a second product shell.",
  );

  const reuseZone = zone(o, { x: 40, y: 130, w: 450, h: 650, title: "POSTGRES · reuse; never duplicate", tone: "violet" });
  panel(o, { x: 70, y: 185, w: 390, title: "Identity already present", tone: "violet", lines: [
    "organizations + org_id · keep for MVP",
    "members + member_identities",
    "agents + append-only agent_versions",
    "agent_ownership",
    "workload_credentials + generations",
  ] });
  panel(o, { x: 70, y: 355, w: 390, title: "Authorization and control already present", tone: "blue", lines: [
    "roles + access_grants + access_requests",
    "teams + team_members — dual-read until M2",
    "mcp_servers + snapshots + capabilities + grants",
    "provider_connections + secret versions",
    "policies + policy_versions + decisions",
  ] });
  panel(o, { x: 70, y: 565, w: 390, title: "Do not overload", tone: "red", lines: [
    "auth_sessions = human browser login",
    "evidence_events = durable assurance evidence",
    "security_audit_events = admin/config mutations",
    "Observe ClickHouse = rich OTLP executions",
    "none of these is the action ledger",
  ] });

  const addZone = zone(o, { x: 520, y: 130, w: 450, h: 650, title: "F1 · additive from real head 0022", tone: "green" });
  panel(o, { x: 550, y: 185, w: 390, title: "0023 · runtime identity", tone: "green", lines: [
    "agent_instances → existing agent + version + human",
    "agent_sessions → instance; taint",
    "agent_tasks → session; origin + intent digest",
    "delegations → parent/child; subset + expiry",
    "RLS on every org-scoped table",
  ] });
  panel(o, { x: 550, y: 405, w: 390, title: "0024 · agent_actions ledger", tone: "green", lines: [
    "monthly Postgres partitions · append-only",
    "receipt registry gives event-id idempotency",
    "aap.action.v1 identity + capability + decision",
    "enforcement grade required; unknown counts as E",
    "argument digest + bounded facets only",
    "collector hash chain + downstream mutation ref",
    "no prompt · completion · raw argument · file body",
  ] });
  note(o, 550, 650, 390, [
    "Naming prevents collisions",
    "auth_sessions = human",
    "agent_sessions = agent context",
    "agent_actions = security ledger",
  ], "amber");

  const uiZone = zone(o, { x: 1000, y: 130, w: 500, h: 650, title: "CONSOLE · reuse and improve", tone: "cyan" });
  panel(o, { x: 1030, y: 185, w: 440, title: "One shell and one bootstrap", tone: "cyan", lines: [
    "App.tsx owns routes · Shell.tsx owns chrome",
    "server navigation manifest; no second identity query",
    "DataBoundary: loading · empty · reasoned error · data",
    "URL-owned filters; exact active route",
    "EnforcementGrade on every ledger number",
  ] });
  panel(o, { x: 1030, y: 395, w: 440, title: "Reuse the working UI", tone: "blue", lines: [
    "Observe list/detail/timeline/graph patterns",
    "Nexus shell, cards, badges and theme tokens",
    "People · Access · MCP · Connections · Audit",
    "Pagination · RelativeTime · WindowDaysSelect",
    "same-origin /v1 client + generated OpenAPI types",
  ] });
  panel(o, { x: 1030, y: 600, w: 440, title: "Ledger-first information architecture", tone: "amber", lines: [
    "Home: coverage · risk · collectors · exposures",
    "Ledger: Actions · Sessions · Live",
    "Agents · Discovery · Control · Admin",
    "assurance-era routes stay reachable behind flags",
    "no fake counts and no show-prompt button",
  ] });

  arrow(o, reuseZone, addZone, { from: "right", to: "left", label: "FKs; no copies", labelDy: -18 });
  arrow(o, addZone, uiZone, { from: "right", to: "left", label: "typed /v1 API", labelDy: -18 });

  note(o, 40, 820, 1460, [
    "The invariant tying all three zones together",
    "Pick one action. The database can reconstruct its human root, agent version, instance, session, task, capability, decision,",
    "policy and grade; the API reveals no customer content; the UI shows the chain using existing components and says exactly",
    "whether the row was mediated, veto-capable, vendor-attested, observed afterwards, or uncovered.",
  ], "green");

  return save("16-mvp-schema-and-ui.excalidraw", o);
}

/* ------------------------------------------------------------- driver */

const built = [
  topology(),
  identity(),
  hierarchy(),
  dataModel(),
  modelLifecycle(),
  clientsAndCatalogue(),
  mcpGateway(),
  dataProtection(),
  telemetry(),
  dashboards(),
  roadmap(),
  enforcementGrades(),
  capabilityModel(),
  agentIdentityChain(),
  threatPaths(),
  mvpBlueprint(),
];

console.log(`wrote ${built.length} diagrams into ${OUT_DIR}`);
for (const line of built) console.log(`  ${line}`);
