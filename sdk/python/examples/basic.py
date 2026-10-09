"""Minimal tracing example (requires Observe endpoint or disabled export)."""

from aap_trace import CaptureMode, TraceConfig, configure, generation_span, shutdown, tool_span


def main() -> None:
    configure(
        TraceConfig(
            endpoint="http://localhost:4318/v1/traces",
            bearer_token="aap_wk_dev.1.replace_me",
            organization_id="00000000-0000-0000-0000-000000000001",
            project_id="00000000-0000-0000-0000-000000000002",
            agent_id="00000000-0000-0000-0000-000000000003",
            capture_mode=CaptureMode.DIGEST,
            enabled=False,
        )
    )
    with generation_span(provider="openai", model="gpt-4o-mini", input_messages=[{"role": "user", "content": "ping"}]):
        with tool_span(name="lookup", arguments={"id": "1"}):
            pass
    shutdown()


if __name__ == "__main__":
    main()
