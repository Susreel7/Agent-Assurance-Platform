package handler_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/auth"
	"agent-assurance/services/gateway/internal/credentials"
	"agent-assurance/services/gateway/internal/handler"
	"agent-assurance/services/gateway/internal/normalize"
	"agent-assurance/services/gateway/internal/provider"
	"agent-assurance/services/gateway/internal/snapshot"
	"agent-assurance/services/gateway/internal/testutil"
)

func TestGoldenAnthropicNormalizedChat(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"id":"msg_1","type":"message","role":"assistant","content":[{"type":"text","text":"hello"}],"stop_reason":"end_turn","usage":{"input_tokens":3,"output_tokens":2}}`))
	}))
	defer upstream.Close()
	srv, token := serverWithProvider(t, upstream.URL, "anthropic", []string{"chat", "streaming"})
	body := []byte(`{"model":"gpt-test","messages":[{"role":"user","content":"hi"}]}`)
	rec := postChat(t, srv, token, body, false)
	var out map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &out)
	if out["object"] != "chat.completion" {
		t.Fatalf("expected openai envelope, got %s", rec.Body.String())
	}
}

func TestGoldenAnthropicStreamOpenAIChunks(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("data: {\"type\":\"content_block_delta\",\"delta\":{\"type\":\"text_delta\",\"text\":\"x\"}}\n\n"))
	}))
	defer upstream.Close()
	srv, token := serverWithProvider(t, upstream.URL, "anthropic", []string{"chat", "streaming"})
	body := []byte(`{"model":"gpt-test","stream":true,"messages":[{"role":"user","content":"hi"}]}`)
	rec := postChat(t, srv, token, body, false)
	if !bytes.Contains(rec.Body.Bytes(), []byte("chat.completion.chunk")) || !bytes.Contains(rec.Body.Bytes(), []byte("[DONE]")) {
		t.Fatalf("bad stream: %s", rec.Body.String())
	}
}

func TestGoldenAnthropicUnsupportedParam(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	defer upstream.Close()
	srv, token := serverWithProvider(t, upstream.URL, "anthropic", []string{"chat"})
	body := []byte(`{"model":"gpt-test","messages":[{"role":"user","content":"hi"}],"n":2}`)
	rec := postChat(t, srv, token, body, false)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestGoldenFallbackSkipsAfterAuthError(t *testing.T) {
	calls := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls++
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte(`{"error":{"message":"bad key"}}`))
	}))
	defer upstream.Close()
	srv, token := serverWithProviderMulti(t, upstream.URL)
	body := []byte(`{"model":"gpt-test","messages":[{"role":"user","content":"hi"}]}`)
	rec := postChat(t, srv, token, body, false)
	if rec.Code == http.StatusOK {
		t.Fatal("expected failure")
	}
	if calls != 1 {
		t.Fatalf("auth error must not fallback to second deployment, calls=%d", calls)
	}
}

func TestStreamCancellation(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		fl, _ := w.(http.Flusher)
		for i := 0; i < 1000; i++ {
			_, _ = w.Write([]byte("data: {\"type\":\"content_block_delta\",\"delta\":{\"type\":\"text_delta\",\"text\":\"x\"}}\n\n"))
			fl.Flush()
			time.Sleep(2 * time.Millisecond)
		}
	}))
	defer upstream.Close()
	srv, token := serverWithProvider(t, upstream.URL, "anthropic", []string{"chat", "streaming"})
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	body := []byte(`{"model":"gpt-test","stream":true,"messages":[{"role":"user","content":"hi"}]}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body)).WithContext(ctx)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-AAP-Agent-Id", "66666666-6666-4666-8666-666666666666")
	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, req)
}

func TestAzureURLGolden(t *testing.T) {
	u, err := provider.AzureChatURL("https://ex.openai.azure.com", "mydep", "2024-02-15-preview")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains([]byte(u), []byte("api-version=2024-02-15-preview")) {
		t.Fatalf("missing api-version: %s", u)
	}
}

func TestGeminiNormalizeGolden(t *testing.T) {
	raw := []byte(`{"candidates":[{"content":{"parts":[{"text":"hi"}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":1,"candidatesTokenCount":1}}`)
	out, err := normalize.GeminiToOpenAIChat(raw, "alias")
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	_ = json.Unmarshal(out, &m)
	if m["object"] != "chat.completion" {
		t.Fatal("not normalized")
	}
}

func postChat(t *testing.T, srv *handler.Server, token string, body []byte, _ bool) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-AAP-Agent-Id", "66666666-6666-4666-8666-666666666666")
	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, req)
	return rec
}

func serverWithProvider(t *testing.T, endpoint, providerName string, caps []string) (*handler.Server, string) {
	dir, token := writeProviderSnapshot(t, endpoint, providerName, caps, false)
	return newTestServerFromDir(t, dir), token
}

func serverWithProviderMulti(t *testing.T, endpoint string) (*handler.Server, string) {
	dir, token := writeProviderSnapshot(t, endpoint, "openai_compatible", []string{"chat"}, true)
	return newTestServerFromDir(t, dir), token
}

func newTestServerFromDir(t *testing.T, dir string) *handler.Server {
	store := snapshot.NewStore(readPubPEM(t, dir))
	if err := store.ReloadFromDir(dir); err != nil {
		t.Fatal(err)
	}
	creds, _ := credentials.LoadFromFile(filepath.Join(dir, "credentials.json"))
	return newTestServer(store, creds)
}

func writeProviderSnapshot(t *testing.T, endpoint, providerName string, caps []string, twoDeploys bool) (string, string) {
	t.Helper()
	priv, pubPEM := testutil.GenerateP256KeyPair()
	dir := t.TempDir()
	_ = os.WriteFile(filepath.Join(dir, "public.pem"), []byte(pubPEM), 0o600)
	secret := bytes.Repeat([]byte{9}, 32)
	gen := "77777777-7777-4777-8777-777777777777"
	org := "22222222-2222-4222-8222-222222222222"
	token := auth.FormatTestToken(org, gen, secret)
	deploys := []any{map[string]any{
		"id": "44444444-4444-4444-8444-444444444444", "provider": providerName,
		"model": "gpt-test", "endpoint": endpoint, "credential_ref": "test",
		"region": "us-east-1", "jurisdiction": "US", "capabilities": caps, "priority": 1, "weight": 1,
	}}
	depIDs := []string{"44444444-4444-4444-8444-444444444444"}
	if twoDeploys {
		deploys = append(deploys, map[string]any{
			"id": "88888888-8888-4888-8888-888888888888", "provider": "openai_compatible",
			"model": "gpt-test", "endpoint": endpoint, "credential_ref": "test",
			"region": "us-east-1", "jurisdiction": "US", "capabilities": []string{"chat"}, "priority": 2, "weight": 1,
		})
		depIDs = append(depIDs, "88888888-8888-4888-8888-888888888888")
	}
	cfg := map[string]any{
		"schema_revision": 1, "snapshot_id": "11111111-1111-4111-8111-111111111111",
		"organization_id": org, "project_id": "33333333-3333-4333-8333-333333333333",
		"issued_at":    time.Now().UTC().Add(-time.Hour).Format(time.RFC3339),
		"expires_at":   time.Now().UTC().Add(time.Hour).Format(time.RFC3339),
		"rules_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		"deployments":  deploys,
		"routes": []any{map[string]any{
			"id": "55555555-5555-4555-8555-555555555555", "agent_id": "66666666-6666-4666-8666-666666666666",
			"environment": "dev", "alias": "gpt-test", "strategy": "priority",
			"deployment_ids": depIDs, "enforcement": "blocking", "max_attempts": 2,
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
	_ = os.WriteFile(filepath.Join(dir, "credentials.json"), []byte(`{"test":"k"}`), 0o600)
	return dir, token
}
