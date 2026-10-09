package handler_test

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/credentials"
	"agent-assurance/services/gateway/internal/limiter"
	"agent-assurance/services/gateway/internal/router"
	"agent-assurance/services/gateway/internal/snapshot"
)

func TestSlowClientCancelPropagatesUpstream(t *testing.T) {
	var upstreamCancelled atomic.Bool
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		fl, _ := w.(http.Flusher)
		_, _ = io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"content\":\"1\"}}]}\n\n")
		fl.Flush()
		<-r.Context().Done()
		upstreamCancelled.Store(true)
	}))
	defer upstream.Close()
	dir, token := installSnapshot(t, upstream.URL)
	creds, _ := credentials.LoadFromFile(filepath.Join(dir, "credentials.json"))
	store := snapshot.NewStore(readPubPEM(t, dir))
	_ = store.ReloadFromDir(dir)
	srv := newTestServer(store, creds)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	body := []byte(`{"model":"gpt-test","stream":true,"messages":[{"role":"user","content":"hi"}]}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body)).WithContext(ctx)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-AAP-Agent-Id", "66666666-6666-4666-8666-666666666666")
	rec := httptest.NewRecorder()
	done := make(chan struct{})
	go func() {
		srv.Handler().ServeHTTP(rec, req)
		close(done)
	}()
	time.Sleep(100 * time.Millisecond)
	cancel()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("handler did not return after client cancel")
	}
	if !upstreamCancelled.Load() {
		t.Fatal("upstream request context was not cancelled")
	}
}

func TestPartialStreamFailureReleasesReservation(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, `data: {"choices":[{"delta":{"content":"x"}}]}`+"\n\n")
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
		// Abrupt close without [DONE] — client sees truncated stream.
		if hj, ok := w.(http.Hijacker); ok {
			conn, _, _ := hj.Hijack()
			_ = conn.Close()
		}
	}))
	defer upstream.Close()
	dir, token := installSnapshot(t, upstream.URL)
	creds, _ := credentials.LoadFromFile(filepath.Join(dir, "credentials.json"))
	store := snapshot.NewStore(readPubPEM(t, dir))
	_ = store.ReloadFromDir(dir)
	lim := limiter.NewMemoryLimiter().(limiter.InFlightLimiter)
	srv := newTestServer(store, creds)
	srv.LocalLimit = lim
	srv.Selector = router.NewSelector(lim)
	body := []byte(`{"model":"gpt-test","stream":true,"messages":[{"role":"user","content":"hi"}]}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-AAP-Agent-Id", "66666666-6666-4666-8666-666666666666")
	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, req)
	if lim.InFlight() != 0 {
		t.Fatalf("reservation leak in-flight=%d", lim.InFlight())
	}
}
