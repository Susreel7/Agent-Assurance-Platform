#!/usr/bin/env bash
# Zero-code brownfield: standard OTEL auto-instrumentation → Observe ingest
export OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-my-agent}"
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-https://observe.example}"
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-${OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces}"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20${AAP_WORKLOAD_TOKEN:?set AAP_WORKLOAD_TOKEN}"
export AAP_ORGANIZATION_ID="${AAP_ORGANIZATION_ID:?set AAP_ORGANIZATION_ID}"
export AAP_PROJECT_ID="${AAP_PROJECT_ID:?set AAP_PROJECT_ID}"
export AAP_CAPTURE_MODE="${AAP_CAPTURE_MODE:-digest}"
exec opentelemetry-instrument "$@"
