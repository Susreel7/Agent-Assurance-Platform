package sse_test

import (
	"io"
	"net/http/httptest"
	"strings"
	"testing"

	"agent-assurance/services/gateway/internal/sse"
)

func TestRelayIncremental(t *testing.T) {
	rec := httptest.NewRecorder()
	up := io.NopCloser(strings.NewReader("data: hello\n\ndata: world\n\n"))
	n, err := sse.Relay(rec, up)
	if err != nil {
		t.Fatal(err)
	}
	if n < 10 {
		t.Fatalf("expected bytes relayed, got %d", n)
	}
}

func FuzzSSERelay(f *testing.F) {
	f.Add("data: x\n\n")
	f.Fuzz(func(t *testing.T, payload string) {
		rec := httptest.NewRecorder()
		_, _ = sse.Relay(rec, io.NopCloser(strings.NewReader(payload)))
	})
}
