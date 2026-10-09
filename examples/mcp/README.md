# Demo MCP server

`demo_server.py` is a synthetic stdio MCP server used by the local adapter.

It exposes two tools, `echo` and `describe_workspace`. Both return fixed or
caller-supplied text. The process does not open a network connection, does not
read a credential, and has no default host.

The Compose file mounts this directory into the adapter at `/servers` and starts
`python /servers/demo_server.py`. Register it with the control plane from the
repository root:

```text
node services/web/scripts/onboard-mcps.mjs
```

Bring your own MCP server by setting `MCP_STDIO_SERVERS_JSON` on the adapter.
Do not commit that file if it contains a host, a token, or an internal path.
