"""TraceClient — OTLP export with AAP bearer auth and no-op when disabled."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from aap_trace.attributes import base_resource_attrs, session_attrs, tag_attrs
from aap_trace.config import TraceConfig
from aap_trace.scores import ScoreClient

_client: TraceClient | None = None


def _normalize_traces_endpoint(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/v1/traces"):
        return base
    if base.endswith("/v1"):
        return f"{base}/traces"
    return f"{base}/v1/traces"


class TraceClient:
    def __init__(self, config: TraceConfig) -> None:
        self.config = config
        self._provider: TracerProvider | object | None = None
        self._processor: BatchSpanProcessor | None = None
        self._score_client: ScoreClient | None = None
        if config.enabled and config.endpoint and config.bearer_token:
            self._init_otel()
        else:
            self._provider = None

    def _init_otel(self) -> None:
        resource = Resource.create(
            {
                **base_resource_attrs(
                    organization_id=self.config.organization_id,
                    project_id=self.config.project_id,
                    service_name=self.config.service_name,
                    environment=self.config.environment,
                    agent_id=self.config.agent_id,
                    agent_name=self.config.agent_name,
                    agent_version=self.config.agent_version,
                    metadata=self.config.metadata,
                ),
                **session_attrs(self.config.session_id, self.config.user_id),
                **tag_attrs(self.config.tags),
                **{
                    key: value
                    for key, value in {
                        "aap.actor.id": self.config.actor_id,
                        "aap.actor.type": self.config.actor_type,
                        "aap.invocation.source": self.config.invocation_source,
                        "aap.invocation.application": self.config.application_name,
                        "aap.invocation.client": self.config.client_name,
                        "aap.request.id": self.config.request_id,
                        "aap.replay.of_execution_id": self.config.replay_of_execution_id,
                        "aap.sampling.rate": self.config.sample_rate,
                    }.items()
                    if value is not None
                },
            }
        )
        headers = {"Authorization": f"Bearer {self.config.bearer_token}"}
        exporter = OTLPSpanExporter(
            endpoint=_normalize_traces_endpoint(self.config.endpoint),
            headers=headers,
            timeout=int(self.config.otlp_timeout_seconds),
        )
        provider = TracerProvider(
            resource=resource,
            sampler=ParentBased(root=TraceIdRatioBased(self.config.sample_rate)),
        )
        processor = BatchSpanProcessor(
            exporter,
            max_export_batch_size=self.config.max_export_batch_size,
            schedule_delay_millis=self.config.schedule_delay_millis,
        )
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        self._provider = provider
        self._processor = processor
        self._score_client = ScoreClient(self.config)

    @property
    def tracer(self) -> trace.Tracer:
        return trace.get_tracer("aap_trace", "0.1.0")

    @property
    def scores(self) -> ScoreClient:
        if self._score_client is None:
            self._score_client = ScoreClient(self.config)
        return self._score_client

    def flush(self, timeout_millis: int = 30000) -> bool:
        if self._processor is None:
            return True
        return self._processor.force_flush(timeout_millis=timeout_millis)

    def shutdown(self) -> None:
        if self._processor is not None:
            self._processor.shutdown()  # type: ignore[no-untyped-call]
        if isinstance(self._provider, TracerProvider):
            self._provider.shutdown()


def configure(config: TraceConfig) -> TraceClient:
    global _client
    if _client is not None:
        _client.shutdown()
    _client = TraceClient(config)
    return _client


def get_client() -> TraceClient:
    if _client is None:
        raise RuntimeError("aap_trace.configure() has not been called")
    return _client


def shutdown() -> None:
    global _client
    if _client is not None:
        _client.shutdown()
        _client = None
