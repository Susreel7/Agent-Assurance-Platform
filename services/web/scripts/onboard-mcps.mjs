/**
 * Register and discover the synthetic local MCP server shipped with this repository.
 *
 * This script never executes a command read from the registry. The executable path
 * below is part of this reviewed source file; treating an arbitrary submitted command
 * as discoverable would turn the control plane into remote code execution.
 */

import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const API = process.env.AAP_API_BASE ?? "http://localhost:8000";
const ORG = process.env.AAP_ORG_ID ?? "";
const demoServer = resolve(dirname(fileURLToPath(import.meta.url)), "../../../examples/mcp/demo_server.py");

const servers = [
  {
    slug: "demo-mcp",
    name: "Synthetic demo MCP",
    description:
      "Local stdio server with two synthetic tools. No network client and no credential.",
    transport: "stdio",
    command: "python examples/mcp/demo_server.py",
    trust_tier: "internal",
    environments: ["dev"],
    requires_approval_for_writes: true,
    executable: ["python", [demoServer]],
  },
];

async function main() {
  for (const definition of servers) {
    const { executable, ...payload } = definition;
    const res = await fetch(`${API}/v1/mcp/servers`, {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify(payload),
    });

    let server;
    if (res.ok) {
      server = await res.json();
      console.log(`registered ${payload.slug}: ${res.status}`);
    } else if (res.status === 409) {
      server = await existingServer(payload.slug);
      console.log(`already present ${payload.slug}: ${server.id}`);
    } else {
      const body = await res.text();
      console.error(`failed ${payload.slug}: ${res.status} ${body}`);
      continue;
    }

    const discovery = await discover(executable[0], executable[1]);
    const snapshot = await fetch(
      `${API}/v1/mcp/servers/${encodeURIComponent(server.id)}/snapshots`,
      {
        method: "POST",
        headers: requestHeaders(),
        body: JSON.stringify(discovery),
      },
    );
    const snapshotBody = await snapshot.text();
    if (!snapshot.ok) {
      throw new Error(`discovery submit failed for ${payload.slug}: ${snapshot.status} ${snapshotBody}`);
    }
    const recorded = JSON.parse(snapshotBody);
    console.log(
      `discovered ${payload.slug}: ${recorded.tool_count} tools, snapshot ${recorded.id}`,
    );
  }
}

function requestHeaders() {
  return {
    "Content-Type": "application/json",
    Accept: "application/json",
    ...(ORG ? { "X-Org-Id": ORG } : {}),
  };
}

async function existingServer(slug) {
  const response = await fetch(`${API}/v1/mcp/servers?limit=200`, {
    headers: requestHeaders(),
  });
  if (!response.ok) {
    throw new Error(`could not resolve existing server ${slug}: ${response.status}`);
  }
  const page = await response.json();
  const row = page.items.find((item) => item.server.slug === slug);
  if (!row) throw new Error(`registry conflict returned but ${slug} was not found`);
  return row.server;
}

function discover(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      env: {
        PATH: process.env.PATH ?? "",
        Path: process.env.Path ?? "",
        SystemRoot: process.env.SystemRoot ?? "",
        TEMP: process.env.TEMP ?? "",
        TMP: process.env.TMP ?? "",
        PYTHONIOENCODING: "utf-8",
      },
    });
    const lines = createInterface({ input: child.stdout });
    const responses = new Map();
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => finish(new Error("MCP discovery timed out")), 10_000);

    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => {
      stderr = `${stderr}${chunk}`.slice(-2_000);
    });
    child.on("error", finish);
    child.on("exit", (code) => {
      if (!settled && code !== null && code !== 0) {
        finish(new Error(`MCP process exited ${code}: ${stderr}`));
      }
    });
    lines.on("line", (line) => {
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        return;
      }
      if (message.id !== undefined) responses.set(message.id, message);
      if (!responses.has(1) || !responses.has(2)) return;

      const initialized = responses.get(1);
      const listed = responses.get(2);
      if (initialized.error || listed.error) {
        finish(new Error(`MCP discovery failed: ${JSON.stringify(initialized.error ?? listed.error)}`));
        return;
      }
      const tools = Array.isArray(listed.result?.tools) ? listed.result.tools : [];
      finish(null, {
        protocol_version: initialized.result?.protocolVersion ?? null,
        source: "discovery",
        capabilities: tools.map((tool) => {
          const annotations = tool.annotations ?? {};
          return {
            kind: "tool",
            name: String(tool.name),
            title: tool.title ? String(tool.title) : null,
            input_schema_digest: sha256(stableStringify(tool.inputSchema ?? {})),
            declared_read_only: booleanOrNull(annotations.readOnlyHint),
            declared_destructive: booleanOrNull(annotations.destructiveHint),
            declared_idempotent: booleanOrNull(annotations.idempotentHint),
            declared_open_world: booleanOrNull(annotations.openWorldHint),
          };
        }),
      });
    });

    child.stdin.write(
      `${JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          protocolVersion: "2025-06-18",
          capabilities: {},
          clientInfo: { name: "agent-assurance-discovery", version: "0.1.0" },
        },
      })}\n`,
    );
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" })}\n`);
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} })}\n`);

    function finish(error, result) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      lines.close();
      child.kill();
      if (error) reject(error);
      else resolve(result);
    }
  });
}

function booleanOrNull(value) {
  return typeof value === "boolean" ? value : null;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
