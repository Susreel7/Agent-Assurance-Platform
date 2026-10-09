package handler_test

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/audit"
	"agent-assurance/services/gateway/internal/auth"
	"agent-assurance/services/gateway/internal/config"
	"agent-assurance/services/gateway/internal/credentials"
	"agent-assurance/services/gateway/internal/handler"
	"agent-assurance/services/gateway/internal/limiter"
	"agent-assurance/services/gateway/internal/router"
	"agent-assurance/services/gateway/internal/snapshot"
	"agent-assurance/services/gateway/internal/testutil"
)

func TestChatCompletionMockUpstream(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Idempotency-Key") != "idem-1" {
			t.Fatalf("missing idempotency propagation")
		}
		_, _ = w.Write([]byte(`{"id":"cmpl","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()
	dir, token := installSnapshot(t, upstream.URL)
	creds, err := credentials.LoadFromFile(filepath.Join(dir, "credentials.json"))
	if err != nil {
		t.Fatal(err)
	}
	store := snapshot.NewStore(readPubPEM(t, dir))
	if err := store.ReloadFromDir(dir); err != nil {
		t.Fatal(err)
	}
	srv := newTestServer(store, creds)
	body := []byte(`{"model":"gpt-test","messages":[{"role":"user","content":"hi"}]}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-AAP-Agent-Id", "66666666-6666-4666-8666-666666666666")
	req.Header.Set("Idempotency-Key", "idem-1")
	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestSecretIsBlockedBeforeProviderDispatch(t *testing.T) {
	var upstreamCalled bool
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		upstreamCalled = true
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	dir, token := installSnapshot(t, upstream.URL)
	creds, _ := credentials.LoadFromFile(filepath.Join(dir, "credentials.json"))
	store := snapshot.NewStore(readPubPEM(t, dir))
	_ = store.ReloadFromDir(dir)
	srv := newTestServer(store, creds)

	body := []byte(`{"model":"gpt-test","messages":[{"role":"user","content":"password=correct-horse-battery-staple"}]}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-AAP-Agent-Id", "66666666-6666-4666-8666-666666666666")
	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if upstreamCalled {
		t.Fatal("provider received a request containing a detected secret")
	}
	if bytes.Contains(rec.Body.Bytes(), []byte("correct-horse")) {
		t.Fatal("response leaked blocked secret")
	}
	events := srv.Audit.Drain(1)
	if len(events) != 1 || events[0].ReasonCode != "secret_detected" {
		t.Fatalf("missing metadata-only denial audit: %#v", events)
	}
	if len(events[0].FindingKinds) != 1 || events[0].FindingKinds[0] != "labelled_secret" {
		t.Fatalf("unexpected finding metadata: %#v", events[0].FindingKinds)
	}
}

func TestSSEStreaming(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "data: {\"x\":1}\n\ndata: [DONE]\n\n")
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
	}))
	defer upstream.Close()
	dir, token := installSnapshot(t, upstream.URL)
	creds, _ := credentials.LoadFromFile(filepath.Join(dir, "credentials.json"))
	store := snapshot.NewStore(readPubPEM(t, dir))
	_ = store.ReloadFromDir(dir)
	srv := newTestServer(store, creds)
	body := []byte(`{"model":"gpt-test","stream":true,"messages":[{"role":"user","content":"hi"}]}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-AAP-Agent-Id", "66666666-6666-4666-8666-666666666666")
	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d", rec.Code)
	}
	if !bytes.Contains(rec.Body.Bytes(), []byte("[DONE]")) {
		t.Fatalf("expected streamed payload, got %q", rec.Body.String())
	}
}

func TestGoldenErrorEnvelope(t *testing.T) {
	srv := &handler.Server{Settings: config.Settings{}, Snapshots: snapshot.NewStore("")}
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader([]byte(`{"model":"x"}`)))
	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, req)
	var got map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &got)
	errObj := got["error"].(map[string]any)
	if errObj["type"] != "authentication_error" {
		t.Fatalf("golden mismatch: %s", rec.Body.String())
	}
}

func TestLimiterConcurrencyRelease(t *testing.T) {
	lim := limiter.NewMemoryLimiter()
	const n = 32
	done := make(chan struct{}, n)
	for i := 0; i < n; i++ {
		go func() {
			res, err := lim.TryAcquire(context.Background(), "dep", limiter.LimitDimensions{}, 1, 0)
			if err != nil {
				t.Error(err)
			}
			lim.Release(res)
			done <- struct{}{}
		}()
	}
	for i := 0; i < n; i++ {
		<-done
	}
	if lim.BusyCount("dep") != 0 {
		t.Fatalf("busy leak")
	}
}

func newTestServer(store *snapshot.Store, creds *credentials.Resolver) *handler.Server {
	return &handler.Server{
		Settings: config.Settings{
			MaxRequestBodyBytes:     1 << 20,
			MaxResponseBodyBytes:    1 << 20,
			DefaultUpstreamTimeout:  5 * time.Second,
			BuildRevision:           "test",
			DevAllowInsecureLimiter: true,
		},
		Snapshots:   store,
		Credentials: creds,
		LocalLimit:  limiter.NewMemoryLimiter(),
		GlobalLimit: limiter.NewRedisLimiter(""),
		Selector:    router.NewSelector(limiter.NewMemoryLimiter()),
		Audit:       audit.NewQueue(128),
	}
}

func installSnapshot(t testing.TB, endpoint string) (dir, token string) {
	t.Helper()
	priv, pubPEM := testutil.GenerateP256KeyPair()
	dir = t.TempDir()
	_ = os.WriteFile(filepath.Join(dir, "public.pem"), []byte(pubPEM), 0o600)
	secret := bytes.Repeat([]byte{9}, 32)
	gen := "77777777-7777-4777-8777-777777777777"
	org := "22222222-2222-4222-8222-222222222222"
	token = auth.FormatTestToken(org, gen, secret)
	cfg := map[string]any{
		"schema_revision": 1,
		"snapshot_id":     "11111111-1111-4111-8111-111111111111",
		"organization_id": org,
		"project_id":      "33333333-3333-4333-8333-333333333333",
		"issued_at":       time.Now().UTC().Add(-time.Hour).Format(time.RFC3339),
		"expires_at":      time.Now().UTC().Add(time.Hour).Format(time.RFC3339),
		"rules_digest":    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		"deployments": []any{map[string]any{
			"id": "44444444-4444-4444-8444-444444444444", "provider": "openai_compatible",
			"model": "gpt-test", "endpoint": endpoint, "credential_ref": "test",
			"region": "us-east-1", "jurisdiction": "US",
			"capabilities": []string{"chat", "streaming"}, "priority": 1, "weight": 1,
		}},
		"routes": []any{map[string]any{
			"id":          "55555555-5555-4555-8555-555555555555",
			"agent_id":    "66666666-6666-4666-8666-666666666666",
			"environment": "dev", "alias": "gpt-test", "strategy": "priority",
			"deployment_ids": []string{"44444444-4444-4444-8444-444444444444"},
			"enforcement":    "blocking",
		}},
		"workload_bindings": []any{map[string]any{
			"generation_id": gen, "secret_hash": auth.SecretHashHex(secret),
			"organization_id": org, "project_id": "33333333-3333-4333-8333-333333333333",
			"environment": "dev", "modules": []string{"router"},
			"scopes": []string{"router:chat", "router:models", "router:responses", "router:embeddings"},
		}},
	}
	raw, _ := json.Marshal(cfg)
	sig := testutil.SignPayload(priv, raw)
	_ = os.WriteFile(filepath.Join(dir, "router.json"), raw, 0o600)
	_ = os.WriteFile(filepath.Join(dir, "router.json.sig"), []byte(sig), 0o600)
	cred := map[string]string{"test": "sk-test"}
	cRaw, _ := json.Marshal(cred)
	_ = os.WriteFile(filepath.Join(dir, "credentials.json"), cRaw, 0o600)
	return dir, token
}

func readPubPEM(t testing.TB, dir string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(dir, "public.pem"))
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}
