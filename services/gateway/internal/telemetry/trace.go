package telemetry

import "net/http"

func TraceParent(r *http.Request) string {
	if tp := r.Header.Get("traceparent"); tp != "" {
		return tp
	}
	return r.Header.Get("Traceparent")
}

func IdempotencyKey(r *http.Request) string {
	if k := r.Header.Get("Idempotency-Key"); k != "" {
		return k
	}
	return r.Header.Get("X-Idempotency-Key")
}
