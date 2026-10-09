// Fails the build if the console calls a URL the API does not serve.
//
// This exists because fifteen of the console's fifty-three request paths pointed at
// routes that had never existed — `/v1/findings` instead of `/v1/assurance/findings`,
// `/v1/sla/...` instead of `/v1/slos/...`, and so on. Every one of those screens worked
// in mock mode, because the mock handlers were written against the same wrong paths, and
// returned 404 the moment the console was pointed at a real backend. Nothing in the
// build, the typecheck or the lint had an opinion about it, so the breakage reached the
// user as "no page opens".
//
// A type checker cannot catch this: a path is a string, and both halves of the mistake
// live in different languages. So the check is mechanical and external — read the paths
// out of the source, read the routes out of the spec, and refuse to build on a mismatch.
//
// Run `npm run client` to refresh openapi.json and the generated types together. A stale
// spec turns this check into theatre, which is worse than not having it.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const specPath = join(webRoot, "openapi.json");
const srcRoot = join(webRoot, "src");

// `/v1/agents/{agent_id}` and `/v1/agents/${agentId}` describe the same route. Collapse
// both spellings of "a parameter goes here" to one token so they compare equal.
const PARAM = "\u0000";
const normalise = (p) =>
  p
    .replace(/\$\{[^}]*\}/g, PARAM) // TypeScript template hole
    .replace(/\{[^}]*\}/g, PARAM) // OpenAPI path parameter
    .replace(/\/+$/, "");

function sourceFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full));
    else if (/\.tsx?$/.test(entry) && !entry.endsWith(".d.ts")) out.push(full);
  }
  return out;
}

let spec;
try {
  spec = JSON.parse(readFileSync(specPath, "utf8"));
} catch {
  console.error(
    `check-api: cannot read ${relative(webRoot, specPath)}.\n` +
      `Generate it from a running API:\n` +
      `  curl http://localhost:8000/openapi.json -o services/web/openapi.json && npm run client\n`,
  );
  process.exit(1);
}

const routes = new Set(Object.keys(spec.paths ?? {}).map(normalise));
if (routes.size === 0) {
  console.error("check-api: the spec declares no paths, which cannot be right.");
  process.exit(1);
}

// Only string and template literals that look like a request path. Deliberately narrow:
// a false positive here blocks the build, so the pattern matches the one shape the client
// is called with — a leading /v1/ and no whitespace.
const PATH_LITERAL = /["'`](\/v1\/[^"'`\s?]*)/g;

// Comments are prose, not requests. This matters more than it sounds: the natural way to
// document a path that was removed is to quote it, and quoting a dead path in a comment
// would then fail the build that the comment exists to explain.
//
// Handles block comments and whole-line comments, which is where explanation lives. A
// trailing comment on a line of code is left in — deliberately, because `http://` makes
// naive `//` stripping unsafe, and a request path in a trailing comment is not a shape
// anyone writes.
function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .split("\n")
    .map((line) => (/^\s*(\/\/|\*)/.test(line) ? "" : line))
    .join("\n");
}

const dead = [];
const seen = new Set();

for (const file of sourceFiles(srcRoot)) {
  // The mock handlers legitimately mention paths they serve, and src/mocks is allowed to
  // describe shapes the API has not grown yet. It is excluded from the *route* check but
  // not from review: a mock path with no route behind it is how this bug was introduced.
  const text = stripComments(readFileSync(file, "utf8"));
  const lines = text.split("\n");
  lines.forEach((line, i) => {
    for (const m of line.matchAll(PATH_LITERAL)) {
      const raw = m[1];
      const key = `${raw}@${file}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (!routes.has(normalise(raw)))
        dead.push({ path: raw, file: relative(webRoot, file), line: i + 1 });
    }
  });
}

if (dead.length > 0) {
  console.error(`\ncheck-api: ${dead.length} request path(s) have no matching API route.\n`);
  for (const d of dead) console.error(`  ${d.file}:${d.line}\n    ${d.path}`);
  console.error(
    `\nThe API serves ${routes.size} routes. Check the spelling against openapi.json —\n` +
      `most of these are a missing domain prefix rather than a missing endpoint.\n`,
  );
  process.exit(1);
}

console.log(`check-api: ${seen.size} request path(s) all resolve against ${routes.size} routes.`);
