import { configure, shutdown, toolSpan, withSpan } from "../dist/index.js";

configure({
  endpoint: "http://localhost:4318/v1/traces",
  bearerToken: "aap_wk_dev.1.replace_me",
  organizationId: "00000000-0000-0000-0000-000000000001",
  projectId: "00000000-0000-0000-0000-000000000002",
  enabled: false,
});

await withSpan("run", { "gen_ai.operation.name": "invoke_agent" }, async () => {
  await toolSpan("lookup", { id: "1" })(async () => undefined);
});

await shutdown();
