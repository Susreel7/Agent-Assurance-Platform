// Guards the console's same-origin API contract and the F0/F2 frontend invariants.
//
// Tenant selection belongs to verified identity, never browser storage or a caller-set
// header. Readiness and health remain same-origin operational endpoints.
//
// Several invariants live here rather than in a test runner because they are properties
// of the source tree, not of a running app — `inv_no_build_time_auth`,
// `inv_bootstrap_is_single_request`, `inv_single_nav_source`, `inv_no_lucide_barrel`,
// `inv_data_boundary_exists` and `inv_grade_chip`. Every one of them is the kind of rule
// that is obeyed on the day it is written and broken six weeks later by somebody who had
// no way to know it existed, so the enforcement belongs in the build.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = join(webRoot, "..", "..");
const vite = readFileSync(join(webRoot, "vite.config.ts"), "utf8");
const composePath = join(repoRoot, "docker-compose.yml");
const compose = existsSync(composePath) ? readFileSync(composePath, "utf8") : null;

const failures = [];

/* ------------------------------------------------------- same-origin API contract */

for (const path of ['"/v1"', '"/readyz"', '"/healthz"']) {
  if (!vite.includes(path)) failures.push(`Vite does not proxy ${path}`);
}
if (!vite.includes("VITE_API_PROXY_TARGET")) {
  failures.push("Vite proxy target is not environment-configurable");
}

// Compose, when it exists, must not hand the browser a cross-origin API base: a console
// on a different origin cannot send the session cookie at all, and the fix people reach
// for when that happens is to put the token back in a header.
//
// Only the base is asserted. This used to also require `VITE_API_PROXY_TARGET` in the
// compose file, which stopped being true when the `web` service moved to a static
// runtime image — that image serves a build, so there is no dev-server proxy in it to
// configure, and the check was failing on a file that was correct.
if (compose !== null) {
  const sameOrigin = ['VITE_API_BASE: ""', "VITE_API_BASE: /", "VITE_API_BASE: ''"];
  if (!sameOrigin.some((form) => compose.includes(form))) {
    failures.push("Compose browser API base is not same-origin");
  }
}

/* -------------------------------------------------------------- source tree rules */

const sourceFiles = [];
(function walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else if (/\.(ts|tsx)$/.test(entry.name)) sourceFiles.push(full);
  }
})(join(webRoot, "src"));

/**
 * Source with comments removed.
 *
 * Every rule below asks "does this file *do* X", and a file that explains why it does
 * not do X would otherwise fail. The first version of these checks flagged four files
 * whose only mention of a forbidden thing was the comment saying it was forbidden,
 * which is precisely the documentation worth keeping.
 */
function withoutComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const sources = sourceFiles.map((path) => ({
  path: relative(webRoot, path).replaceAll("\\", "/"),
  code: withoutComments(readFileSync(path, "utf8")),
}));

const find = (name) => sources.find((source) => source.path === name);

// The API client must not handle a credential at all. It is an HttpOnly cookie, which
// this code cannot read by construction — and a fallback that reads `sessionStorage`
// puts one back within reach of any script on the page, which is where it was.
const client = find("src/api/client.ts");
if (!client) {
  failures.push("src/api/client.ts is missing");
} else {
  for (const forbidden of ["X-Org-Id", "getOrgId", "aap.orgId"]) {
    if (client.code.includes(forbidden)) {
      failures.push(`API client still permits browser-owned tenant selection: ${forbidden}`);
    }
  }
  for (const forbidden of ["sessionStorage", "localStorage", "Authorization"]) {
    if (client.code.includes(forbidden)) {
      failures.push(`API client handles credentials itself: ${forbidden}`);
    }
  }
  if (!client.code.includes('credentials: "same-origin"')) {
    failures.push("API client does not send the session cookie");
  }
}

// inv_no_build_time_auth — identity configuration is a server answer, not a build
// argument. A `VITE_OIDC_*` read means the bundle decides which issuer to trust, so
// changing provider means rebuilding, and the browser ships the client id of whichever
// account was configured on the build machine.
for (const { path, code } of sources) {
  const found = code.match(/VITE_(OIDC|ENTRA)_[A-Z_]+/g);
  if (found) {
    failures.push(`build-time auth configuration in ${path}: ${[...new Set(found)].join(", ")}`);
  }
}

// inv_bootstrap_is_single_request — one module per identity endpoint, and the shell
// reads only the bootstrap.
//
// Honest about what it proves: one call site, not one call. That is the half that
// actually regressed — every extra identity request the shell made arrived as a new
// component reaching for `/v1/members/me` or `/v1/access/me` on mount. `/v1/access/me`
// has no owner because the bootstrap now carries the same answer, so any use of it is
// a second request for something already in hand.
const IDENTITY_OWNERS = {
  "/v1/session/bootstrap": "src/features/auth/useBootstrap.ts",
  "/v1/members/me": "src/api/platformQueries.ts",
  "/v1/access/me": null,
};
for (const { path, code } of sources) {
  if (path.endsWith("api/schema.d.ts")) continue;
  for (const [endpoint, owner] of Object.entries(IDENTITY_OWNERS)) {
    if (path === owner) continue;
    // A quoted request path, not a mention of the name.
    if (code.includes(`"${endpoint}"`) || code.includes(`\`${endpoint}`)) {
      const advice = owner ? `only ${owner} may` : "the bootstrap already carries this";
      failures.push(`${path} fetches identity itself: ${endpoint} (${advice})`);
    }
  }
}

/* ------------------------------------------------------------- F2 · one console IA */

// inv_single_nav_source — `Shell.tsx` is the navigation, and there is no second one.
//
// Two navigations existed for four sessions. `Rail.tsx` was unmounted but still in the
// tree, and it disagreed with the live one about labels, grouping and which product was
// primary — so anyone reading the source to learn the IA had even odds of reading the
// wrong file. Deleting it fixed today; this fixes the next time somebody adds
// `SideNav.tsx` rather than editing the one that ships.
const NAV_COMPONENT = "src/components/Shell.tsx";
const RETIRED_NAV = ["src/components/Rail.tsx", "src/components/TopBar.tsx"];

for (const retired of RETIRED_NAV) {
  if (existsSync(join(webRoot, retired))) {
    failures.push(`${retired} is back; ${NAV_COMPONENT} is the only navigation`);
  }
}
for (const { path, code } of sources) {
  for (const retired of RETIRED_NAV) {
    const specifier = retired.replace(/^src\//, "@/").replace(/\.tsx$/, "");
    if (code.includes(`"${specifier}"`) || code.includes(`'${specifier}'`)) {
      failures.push(`${path} imports a retired navigation component: ${specifier}`);
    }
  }
}
if (!find(NAV_COMPONENT)) {
  failures.push(`${NAV_COMPONENT} is missing — the console has no navigation`);
}

// inv_no_lucide_barrel — direct imports, not the barrel.
//
// `from "lucide-react"` pulls the whole icon set into the module graph. Three icons cost
// roughly a thousand modules of dev resolution and hundreds of milliseconds of cold
// start. Vite has no `optimizePackageImports`, so the barrel cannot be optimised away
// after the fact; it has to not be written. Asserted across the tree rather than only in
// `Shell.tsx`, because the cost is per-entry-point and the shell is merely the worst one.
//
// `import type` is exempt because it is erased before a bundler ever sees it, and the
// exemption is load-bearing: the package ships no declarations for the per-icon modules,
// so `src/types/lucide-icons.d.ts` has to name `LucideIcon` from the barrel to type the
// direct imports at all. Without the exemption this rule forbids the one import that
// makes obeying it possible.
const LUCIDE_IMPORT = /\bimport\s+(type\s+)?[^;]*?from\s+["']lucide-react["']/g;
for (const { path, code } of sources) {
  for (const [, typeOnly] of code.matchAll(LUCIDE_IMPORT)) {
    if (!typeOnly) {
      failures.push(
        `${path} barrel-imports lucide-react; use "lucide-react/dist/esm/icons/<name>"`,
      );
    }
  }
}

// inv_data_boundary_exists — Home and the Observe layout render their four states
// through the shared boundary rather than hand-rolling them.
//
// Named files rather than a tree-wide sweep, deliberately. The legacy assurance screens
// still hand-roll their states and converting them is not this slice; what must not
// happen is a *new* ledger surface doing it, and these two are the ledger's entry
// points.
const BOUNDARY_REQUIRED = [
  "src/features/dashboard/LedgerHomeScreen.tsx",
  "src/features/observe/ObserveSuiteLayout.tsx",
];
for (const required of BOUNDARY_REQUIRED) {
  const source = find(required);
  if (!source) {
    failures.push(`${required} is missing`);
  } else if (!source.code.includes("DataBoundary")) {
    failures.push(`${required} does not use DataBoundary for its loading/empty/error states`);
  }
}

// inv_grade_chip — the grade component exists, and `unknown` is labelled rather than
// rounded up or rendered blank.
//
// `design/12-strategic-thesis.md` §5 makes the grade a first-class field because a
// coverage number without its denominator is the claim every competitor makes and no
// CISO believes. A missing grade is Grade E, and saying so is the product.
//
// Two files: the chip renders, `grades.ts` holds the vocabulary. They are separate
// because a module that exports both components and constants loses Fast Refresh, and
// both have to exist for the chip to mean anything.
const gradeChip = find("src/components/EnforcementGrade.tsx");
const gradeFacts = find("src/components/grades.ts");
if (!gradeChip) {
  failures.push("src/components/EnforcementGrade.tsx is missing");
}
if (!gradeFacts) {
  failures.push("src/components/grades.ts is missing — the chip has no vocabulary");
} else {
  for (const grade of ["A", "B", "C", "D", "E", "unknown"]) {
    if (!gradeFacts.code.includes(`"${grade}"`)) {
      failures.push(`grades.ts does not handle grade ${grade}`);
    }
  }
  if (!/Ungraded/.test(gradeFacts.code)) {
    failures.push("grades.ts does not label an unknown grade as ungraded");
  }
}

if (failures.length) {
  console.error(
    "runtime contract check failed:\n" + failures.map((item) => `  - ${item}`).join("\n"),
  );
  process.exit(1);
}

console.log(
  "runtime contract check: same-origin proxy, identity-owned tenancy, cookie-only " +
    "credentials, no build-time auth, one identity call site, one navigation source, " +
    `no icon barrel, graded ledger surfaces (${sources.length} files).`,
);
