"""Sanitize OTLP envelopes before the first durable write."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from observe.config import CaptureMode, Settings
from observe.errors import InvalidEnvelopeError, ObserveError
from observe.ingest.otlp_ids import canonical_span_id, canonical_trace_id
from observe.providers.object_store.base import ObjectStore, tenant_payload_key
from observe.providers.object_store.encrypted import PayloadCipher

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"""(?ix)
        (["']?(?:api[_-]?key|secret|password|token|access[_-]?token|refresh[_-]?token|
        authorization|session[_-]?cookie|private[_-]?key)["']?)
        \s*[:=]\s*["']?[^"',\s}\]]+
        """
    ),
    re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"),
    re.compile(r"\b(?:sk|rk|pk)-[a-zA-Z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"(?i)(aws|azure|gcp)_[a-z0-9_]{16,}"),
    re.compile(r"(?i)postgresql://[^\s]+:[^\s]+@"),
)

SECRET_KEY = re.compile(
    r"(?i)(?:^|[._-])(?:api[_-]?key|secret|password|token|authorization|"
    r"access[_-]?token|refresh[_-]?token|session[_-]?cookie|private[_-]?key)(?:$|[._-])"
)

PII_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PII_PHONE = re.compile(
    r"(?<!\w)(?:\+\d{8,15}|\+?\d{1,3}[ .-]?\(\d{2,4}\)[ .-]?\d{3,4}[ .-]?\d{3,4}"
    r"|\d{3}[ .-]\d{3}[ .-]\d{4})(?!\w)"
)
PII_IPV4 = re.compile(
    r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)"
)
PII_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
PII_PAYMENT_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")

CONTENT_ATTR_KEYS = frozenset(
    {
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "gen_ai.request.tools",
        "gen_ai.retrieval.query",
        "gen_ai.prompt",
        "gen_ai.completion",
        "llm.prompts",
        "llm.completions",
        "aap.prompt.system",
        "aap.prompt.developer",
        "aap.prompt.user",
        "aap.prompt.messages",
        "aap.prompt.context",
        "aap.prompt.tool_definitions",
        "aap.tool.arguments",
        "aap.tool.result",
        "aap.sdk.arguments",
        "aap.sdk.result",
        "aap.node.input_state",
        "aap.node.output_state",
        "aap.graph.definition",
        "aap.state.output",
        "aap.checkpoint.state",
        "aap.retrieval.query",
        "aap.retrieval.documents",
        "aap.mcp.arguments",
        "aap.mcp.result",
        "aap.observation.input",
        "aap.observation.output",
        "aap.payload.input",
        "aap.payload.output",
        "http.request.body",
        "http.response.body",
        "db.query.text",
        "db.statement",
        "log.message",
        "exception.message",
        "exception.stacktrace",
    }
)


@dataclass(frozen=True, slots=True)
class SanitizedEnvelope:
    body: bytes
    content_type: str
    envelope_digest: str
    source_wire_digest: str
    payload_refs: list[dict[str, Any]]


def _wire_digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _scrub_secrets_text(text: str) -> str:
    out = text
    for pattern in SECRET_PATTERNS:
        out = pattern.sub("[REDACTED_SECRET]", out)
    return out


def _redact_pii_text(text: str) -> str:
    text = PII_EMAIL.sub("[REDACTED_EMAIL]", text)
    text = PII_IPV4.sub("[REDACTED_IP]", text)
    text = PII_SSN.sub("[REDACTED_SSN]", text)
    text = PII_PAYMENT_CARD.sub("[REDACTED_PAYMENT_CARD]", text)
    return PII_PHONE.sub("[REDACTED_PHONE]", text)


def _redacted_anyvalue() -> dict[str, str]:
    return {"stringValue": "[REDACTED_SECRET]"}


def _is_secret_key(key: str) -> bool:
    return SECRET_KEY.search(key) is not None


def _is_anyvalue_dict(value: Any) -> bool:
    return isinstance(value, dict) and any(
        k in value
        for k in (
            "stringValue",
            "boolValue",
            "intValue",
            "doubleValue",
            "bytesValue",
            "arrayValue",
            "kvlistValue",
        )
    )


def _sanitize_anyvalue(
    value: Any,
    *,
    mode: CaptureMode,
    redact_pii: bool,
) -> Any:
    if not isinstance(value, dict):
        return value
    if "stringValue" in value and len(value) == 1:
        text = _scrub_secrets_text(str(value["stringValue"]))
        if redact_pii:
            text = _redact_pii_text(text)
        return {"stringValue": text}
    if "bytesValue" in value and len(value) == 1:
        raw = value["bytesValue"]
        if not isinstance(raw, str):
            return {"bytesValue": raw}
        try:
            decoded = base64.b64decode(raw, validate=True)
            text = decoded.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return {"bytesValue": raw}
        sanitized = _scrub_secrets_text(text)
        if redact_pii:
            sanitized = _redact_pii_text(sanitized)
        return {"bytesValue": base64.b64encode(sanitized.encode("utf-8")).decode("ascii")}
    if "boolValue" in value and len(value) == 1:
        return {"boolValue": bool(value["boolValue"])}
    if "intValue" in value and len(value) == 1:
        return {"intValue": str(value["intValue"])}
    if "doubleValue" in value and len(value) == 1:
        return {"doubleValue": float(value["doubleValue"])}
    if "arrayValue" in value:
        inner = value.get("arrayValue") or {}
        values = inner.get("values") if isinstance(inner, dict) else []
        return {
            "arrayValue": {
                "values": [
                    _sanitize_anyvalue(v, mode=mode, redact_pii=redact_pii) for v in (values or [])
                ]
            }
        }
    if "kvlistValue" in value:
        inner = value.get("kvlistValue") or {}
        kvs = inner.get("values") if isinstance(inner, dict) else []
        cleaned_kvs: list[dict[str, Any]] = []
        for kv in kvs or []:
            if not isinstance(kv, dict):
                continue
            key = kv.get("key")
            if not key:
                continue
            cleaned_value = (
                _redacted_anyvalue()
                if _is_secret_key(str(key))
                else _sanitize_anyvalue(kv.get("value", {}), mode=mode, redact_pii=redact_pii)
            )
            cleaned_kvs.append(
                {
                    "key": key,
                    "value": cleaned_value,
                }
            )
        return {"kvlistValue": {"values": cleaned_kvs}}
    return {k: _sanitize_anyvalue(v, mode=mode, redact_pii=redact_pii) for k, v in value.items()}


def _content_bytes_from_anyvalue(value: Any) -> bytes:
    if isinstance(value, dict) and "stringValue" in value:
        return str(value["stringValue"]).encode("utf-8")
    if isinstance(value, dict) and "bytesValue" in value:
        raw = value["bytesValue"]
        if isinstance(raw, str):
            import base64

            return base64.b64decode(raw)
        return bytes(raw)
    return json.dumps(value, default=str, sort_keys=True).encode("utf-8")


def _externalize_content(
    *,
    key: str,
    value: Any,
    mode: CaptureMode,
    store: ObjectStore,
    cipher: PayloadCipher | None,
    org_id: UUID,
    project_id: UUID,
    encryption_key_ref: str,
    redact_pii: bool,
    payload_refs: list[dict[str, Any]],
    trace_id: str,
    span_id: str,
) -> dict[str, Any]:
    if mode in (CaptureMode.FULL, CaptureMode.REDACTED):
        if cipher is None:
            raise ObserveError(
                "payload encryption required for content capture",
                code="payload_encryption_required",
            )
        plaintext = _content_bytes_from_anyvalue(value)
        plaintext = _scrub_secrets_text(plaintext.decode("utf-8", errors="replace")).encode("utf-8")
        if mode == CaptureMode.REDACTED:
            preview = _redact_pii_text(plaintext.decode("utf-8", errors="replace"))
            plaintext = preview.encode("utf-8")
        digest = store.digest(plaintext)
        object_key = tenant_payload_key(org_id, project_id, digest)
        if not store.exists(object_key):
            store.put(object_key, cipher.encrypt(plaintext), "application/octet-stream")
        payload_refs.append(
            {
                "trace_id": trace_id,
                "span_id": span_id,
                "field_name": key,
                "digest": digest,
                "object_key": object_key,
                "byte_size": len(plaintext),
                "encryption_key_ref": encryption_key_ref,
                "redaction_state": "redacted" if mode == CaptureMode.REDACTED else "full",
            }
        )
        suffix = (
            key.split(".")[-1]
            if key.startswith("aap.payload.")
            else re.sub(r"[^a-zA-Z0-9_]+", "_", key)[:96]
        )
        return {
            f"aap.payload.{suffix}_ref": {"stringValue": digest},
            f"{key}.size": {"intValue": str(len(plaintext))},
        }
    if mode == CaptureMode.DIGEST:
        raw = _content_bytes_from_anyvalue(value)
        raw = _scrub_secrets_text(raw.decode("utf-8", errors="replace")).encode("utf-8")
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        return {
            f"{key}.digest": {"stringValue": digest},
            f"{key}.size": {"intValue": str(len(raw))},
        }
    if mode == CaptureMode.NONE:
        raw = _content_bytes_from_anyvalue(value)
        return {f"{key}.size": {"intValue": str(len(raw))}}
    return {}


def _sanitize_attribute_list(
    attrs: list[Any],
    *,
    mode: CaptureMode,
    store: ObjectStore,
    cipher: PayloadCipher | None,
    org_id: UUID,
    project_id: UUID,
    encryption_key_ref: str,
    redact_pii: bool,
    payload_refs: list[dict[str, Any]],
    trace_id: str,
    span_id: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in attrs:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not key:
            continue
        value = item.get("value", {})
        if _is_secret_key(str(key)):
            out.append({"key": key, "value": _redacted_anyvalue()})
            continue
        if key in CONTENT_ATTR_KEYS:
            replacements = _externalize_content(
                key=key,
                value=value,
                mode=mode,
                store=store,
                cipher=cipher,
                org_id=org_id,
                project_id=project_id,
                encryption_key_ref=encryption_key_ref,
                redact_pii=redact_pii,
                payload_refs=payload_refs,
                trace_id=trace_id,
                span_id=span_id,
            )
            for rep_key, rep_val in replacements.items():
                out.append({"key": rep_key, "value": rep_val})
            continue
        out.append(
            {
                "key": key,
                "value": _sanitize_anyvalue(value, mode=mode, redact_pii=redact_pii),
            }
        )
    return out


def _sanitize_metadata_attribute_list(
    attrs: list[Any],
    *,
    mode: CaptureMode,
    redact_pii: bool,
) -> list[dict[str, Any]]:
    """Sanitize attributes that cannot safely own external payload references."""
    out: list[dict[str, Any]] = []
    for item in attrs:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        key = str(item["key"])
        value = item.get("value", {})
        if _is_secret_key(key):
            out.append({"key": key, "value": _redacted_anyvalue()})
            continue
        if key in CONTENT_ATTR_KEYS:
            raw = _content_bytes_from_anyvalue(value)
            raw = _scrub_secrets_text(raw.decode("utf-8", errors="replace")).encode("utf-8")
            out.append({"key": f"{key}.size", "value": {"intValue": str(len(raw))}})
            if mode != CaptureMode.NONE:
                out.append(
                    {
                        "key": f"{key}.digest",
                        "value": {"stringValue": _wire_digest(raw)},
                    }
                )
            continue
        out.append(
            {
                "key": key,
                "value": _sanitize_anyvalue(value, mode=mode, redact_pii=redact_pii),
            }
        )
    return out


def _canonicalize_span_ids(span: dict[str, Any]) -> tuple[str, str]:
    trace_raw = str(span.get("traceId") or span.get("trace_id") or "")
    span_raw = str(span.get("spanId") or span.get("span_id") or "")
    trace_id = canonical_trace_id(trace_raw)
    span_id = canonical_span_id(span_raw)
    if trace_id:
        span["traceId"] = trace_id
        span.pop("trace_id", None)
    if span_id:
        span["spanId"] = span_id
        span.pop("span_id", None)
    parent_raw = span.get("parentSpanId") or span.get("parent_span_id")
    if parent_raw:
        parent = canonical_span_id(str(parent_raw))
        span["parentSpanId"] = parent
        span.pop("parent_span_id", None)
    return trace_id, span_id


def _sanitize_resource_spans(
    document: dict[str, Any],
    *,
    mode: CaptureMode,
    store: ObjectStore,
    cipher: PayloadCipher | None,
    org_id: UUID,
    project_id: UUID,
    encryption_key_ref: str,
    payload_refs: list[dict[str, Any]],
) -> None:
    redact_pii = mode == CaptureMode.REDACTED
    resources = document.get("resourceSpans", document.get("resource_spans", []))
    for resource in resources:
        resource_meta = resource.get("resource", {})
        if isinstance(resource_meta, dict):
            resource_meta["attributes"] = _sanitize_metadata_attribute_list(
                resource_meta.get("attributes", []),
                mode=mode,
                redact_pii=redact_pii,
            )
        scopes = resource.get("scopeSpans", resource.get("scope_spans", []))
        for scope in scopes:
            scope_meta = scope.get("scope", {})
            if isinstance(scope_meta, dict):
                scope_meta["attributes"] = _sanitize_metadata_attribute_list(
                    scope_meta.get("attributes", []),
                    mode=mode,
                    redact_pii=redact_pii,
                )
            for span in scope.get("spans", []):
                trace_id, span_id = _canonicalize_span_ids(span)
                attrs = span.get("attributes", [])
                if not isinstance(attrs, list):
                    attrs = []
                span["attributes"] = _sanitize_attribute_list(
                    attrs,
                    mode=mode,
                    store=store,
                    cipher=cipher,
                    org_id=org_id,
                    project_id=project_id,
                    encryption_key_ref=encryption_key_ref,
                    redact_pii=redact_pii,
                    payload_refs=payload_refs,
                    trace_id=trace_id,
                    span_id=span_id,
                )
                for event in span.get("events", []):
                    if isinstance(event, dict):
                        event["attributes"] = _sanitize_attribute_list(
                            event.get("attributes", []),
                            mode=mode,
                            store=store,
                            cipher=cipher,
                            org_id=org_id,
                            project_id=project_id,
                            encryption_key_ref=encryption_key_ref,
                            redact_pii=redact_pii,
                            payload_refs=payload_refs,
                            trace_id=trace_id,
                            span_id=span_id,
                        )
                for link in span.get("links", []):
                    if isinstance(link, dict):
                        link["attributes"] = _sanitize_metadata_attribute_list(
                            link.get("attributes", []),
                            mode=mode,
                            redact_pii=redact_pii,
                        )


def _sanitize_resource_logs(
    document: dict[str, Any],
    *,
    mode: CaptureMode,
    store: ObjectStore,
    cipher: PayloadCipher | None,
    org_id: UUID,
    project_id: UUID,
    encryption_key_ref: str,
    payload_refs: list[dict[str, Any]],
) -> None:
    redact_pii = mode == CaptureMode.REDACTED
    resources = document.get("resourceLogs", document.get("resource_logs", []))
    for resource in resources:
        resource_meta = resource.get("resource", {})
        if isinstance(resource_meta, dict):
            resource_meta["attributes"] = _sanitize_metadata_attribute_list(
                resource_meta.get("attributes", []),
                mode=mode,
                redact_pii=redact_pii,
            )
        scopes = resource.get("scopeLogs", resource.get("scope_logs", []))
        for scope in scopes:
            scope_meta = scope.get("scope", {})
            if isinstance(scope_meta, dict):
                scope_meta["attributes"] = _sanitize_metadata_attribute_list(
                    scope_meta.get("attributes", []),
                    mode=mode,
                    redact_pii=redact_pii,
                )
            for record in scope.get("logRecords", scope.get("log_records", [])):
                trace_raw = str(record.get("traceId") or record.get("trace_id") or "")
                span_raw = str(record.get("spanId") or record.get("span_id") or "")
                trace_id = canonical_trace_id(trace_raw)
                span_id = canonical_span_id(span_raw)
                if trace_id:
                    record["traceId"] = trace_id
                if span_id:
                    record["spanId"] = span_id
                attrs = record.get("attributes", [])
                if not isinstance(attrs, list):
                    attrs = []
                record["attributes"] = _sanitize_attribute_list(
                    attrs,
                    mode=mode,
                    store=store,
                    cipher=cipher,
                    org_id=org_id,
                    project_id=project_id,
                    encryption_key_ref=encryption_key_ref,
                    redact_pii=redact_pii,
                    payload_refs=payload_refs,
                    trace_id=trace_id,
                    span_id=span_id,
                )
                body = record.get("body")
                if body is not None:
                    if mode in (CaptureMode.FULL, CaptureMode.REDACTED):
                        if cipher is None:
                            raise ObserveError(
                                "payload encryption required for content capture",
                                code="payload_encryption_required",
                            )
                        replacements = _externalize_content(
                            key="log.message",
                            value=body if _is_anyvalue_dict(body) else {"stringValue": str(body)},
                            mode=mode,
                            store=store,
                            cipher=cipher,
                            org_id=org_id,
                            project_id=project_id,
                            encryption_key_ref=encryption_key_ref,
                            redact_pii=redact_pii,
                            payload_refs=payload_refs,
                            trace_id=trace_id,
                            span_id=span_id,
                        )
                        for rep_key, rep_val in replacements.items():
                            if rep_key.endswith("_ref"):
                                record["body"] = rep_val
                    elif mode == CaptureMode.DIGEST:
                        text = str(
                            body.get("stringValue", body) if isinstance(body, dict) else body
                        )
                        record["body"] = {
                            "stringValue": "[digest:"
                            + hashlib.sha256(text.encode()).hexdigest()[:16]
                            + "]"
                        }
                    else:
                        record.pop("body", None)


def _scrub_document_strings(value: Any, *, redact_pii: bool) -> Any:
    if isinstance(value, str):
        sanitized = _scrub_secrets_text(value)
        return _redact_pii_text(sanitized) if redact_pii else sanitized
    if isinstance(value, list):
        return [_scrub_document_strings(item, redact_pii=redact_pii) for item in value]
    if isinstance(value, dict):
        return {
            key: _scrub_document_strings(item, redact_pii=redact_pii) for key, item in value.items()
        }
    return value


def sanitize_otlp_json_envelope(
    settings: Settings,
    store: ObjectStore,
    *,
    org_id: UUID,
    project_id: UUID,
    mode: CaptureMode,
    encryption_key_ref: str | None,
    body: bytes,
    content_type: str,
    envelope_kind: str,
) -> SanitizedEnvelope:
    """Parse JSON OTLP, scrub secrets, externalize content; returns sanitized bytes."""
    source_wire_digest = _wire_digest(body)
    ct = content_type.split(";")[0].strip().lower()
    if ct != "application/json":
        raise InvalidEnvelopeError("sanitizer requires JSON OTLP envelope")

    document = json.loads(body)
    payload_refs: list[dict[str, Any]] = []
    cipher: PayloadCipher | None = None
    if mode in (CaptureMode.FULL, CaptureMode.REDACTED):
        if not settings.payload_encryption_key:
            raise ObserveError(
                "OBSERVE_PAYLOAD_ENCRYPTION_KEY required for redacted/full capture",
                code="payload_encryption_required",
            )
        cipher = PayloadCipher(settings.payload_encryption_key)

    key_ref = encryption_key_ref or "local:fernet"
    if envelope_kind == "logs":
        _sanitize_resource_logs(
            document,
            mode=mode,
            store=store,
            cipher=cipher,
            org_id=org_id,
            project_id=project_id,
            encryption_key_ref=key_ref,
            payload_refs=payload_refs,
        )
    else:
        _sanitize_resource_spans(
            document,
            mode=mode,
            store=store,
            cipher=cipher,
            org_id=org_id,
            project_id=project_id,
            encryption_key_ref=key_ref,
            payload_refs=payload_refs,
        )

    document = _scrub_document_strings(
        document,
        redact_pii=mode == CaptureMode.REDACTED,
    )
    sanitized = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return SanitizedEnvelope(
        body=sanitized,
        content_type="application/json",
        envelope_digest=store.digest(sanitized),
        source_wire_digest=source_wire_digest,
        payload_refs=payload_refs,
    )
