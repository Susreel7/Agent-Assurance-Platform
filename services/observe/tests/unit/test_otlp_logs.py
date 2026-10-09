from __future__ import annotations

import json

from observe.ingest import otlp


def test_logs_from_json_lifecycle_event() -> None:
    body = json.dumps(
        {
            "resourceLogs": [
                {
                    "resource": {"attributes": []},
                    "scopeLogs": [
                        {
                            "logRecords": [
                                {
                                    "timeUnixNano": "1000",
                                    "traceId": "c" * 32,
                                    "spanId": "d" * 16,
                                    "attributes": [
                                        {
                                            "key": "aap.event.type",
                                            "value": {"stringValue": "execution.started"},
                                        },
                                        {
                                            "key": "aap.execution.id",
                                            "value": {"stringValue": "exec-1"},
                                        },
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    ).encode()
    req = otlp.parse_logs_export_request(body, "application/json")
    records, rejected = otlp.logs_from_request(req)
    assert rejected == 0
    assert len(records) == 1
    assert records[0].attributes["aap.event.type"] == "execution.started"
