package snapshot_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/snapshot"
	"agent-assurance/services/gateway/internal/testutil"
)

func TestRemoteSync200Activates(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, sig := signedFixture(t, priv, -time.Hour, time.Hour)
	var etag atomic.Value
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeConfig200(w, body, meta, sig)
		etag.Store(w.Header().Get("ETag"))
	}))
	t.Cleanup(srv.Close)

	store := snapshot.NewStore(pubPEM)
	client := remoteTestClient(t, srv.URL, store, 1<<20)
	if err := client.SyncOnce(context.Background(), nil); err != nil {
		t.Fatalf("sync: %v", err)
	}
	if store.Current() == nil {
		t.Fatal("expected activated snapshot")
	}
}

func TestRemoteSync304PreservesSnapshot(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, sig := signedFixture(t, priv, -time.Hour, time.Hour)
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if calls.Load() == 1 {
			writeConfig200(w, body, meta, sig)
			return
		}
		if r.Header.Get("If-None-Match") == `"`+meta.configDigest+`"` {
			w.WriteHeader(http.StatusNotModified)
			w.Header().Set("ETag", `"`+meta.configDigest+`"`)
			return
		}
		t.Fatalf("unexpected If-None-Match %q", r.Header.Get("If-None-Match"))
	}))
	t.Cleanup(srv.Close)

	store := snapshot.NewStore(pubPEM)
	client := remoteTestClient(t, srv.URL, store, 1<<20)
	var etag string
	if err := client.SyncOnce(context.Background(), &etag); err != nil {
		t.Fatalf("first sync: %v", err)
	}
	first := store.Current()
	if err := client.SyncOnce(context.Background(), &etag); err != nil {
		t.Fatalf("304 sync: %v", err)
	}
	if store.Current() != first {
		t.Fatal("304 must preserve snapshot pointer")
	}
}

func TestRemoteSyncSendsIfNoneMatch(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, sig := signedFixture(t, priv, -time.Hour, time.Hour)
	var seenINM string
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) == 1 {
			writeConfig200(w, body, meta, sig)
			return
		}
		seenINM = r.Header.Get("If-None-Match")
		w.WriteHeader(http.StatusNotModified)
	}))
	t.Cleanup(srv.Close)

	store := snapshot.NewStore(pubPEM)
	client := remoteTestClient(t, srv.URL, store, 1<<20)
	var etag string
	_ = client.SyncOnce(context.Background(), &etag)
	want := `"` + meta.configDigest + `"`
	_ = client.SyncOnce(context.Background(), &etag)
	if seenINM != want {
		t.Fatalf("If-None-Match = %q, want %q", seenINM, want)
	}
}

func TestRemoteSyncTamperedBodyPreservesLastGood(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, sig := signedFixture(t, priv, -time.Hour, time.Hour)
	step := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		step++
		if step == 1 {
			writeConfig200(w, body, meta, sig)
			return
		}
		bad := append([]byte(nil), body...)
		bad[len(bad)-2] ^= 0xff
		writeConfig200(w, bad, meta, sig)
	}))
	t.Cleanup(srv.Close)

	store := snapshot.NewStore(pubPEM)
	client := remoteTestClient(t, srv.URL, store, 1<<20)
	if err := client.SyncOnce(context.Background(), nil); err != nil {
		t.Fatalf("first: %v", err)
	}
	good := store.Current()
	if err := client.SyncOnce(context.Background(), nil); err == nil {
		t.Fatal("expected tampered body to fail")
	}
	if store.Current() != good {
		t.Fatal("must preserve last good after tampered body")
	}
}

func TestRemoteSyncTamperedSignaturePreservesLastGood(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, _ := signedFixture(t, priv, time.Hour, time.Hour)
	goodSig := testutil.SignPayload(priv, body)
	badSig := testutil.SignPayload(priv, []byte("other"))
	step := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		step++
		if step == 1 {
			writeConfig200(w, body, meta, goodSig)
			return
		}
		writeConfig200(w, body, meta, badSig)
	}))
	t.Cleanup(srv.Close)

	store := snapshot.NewStore(pubPEM)
	client := remoteTestClient(t, srv.URL, store, 1<<20)
	_ = client.SyncOnce(context.Background(), nil)
	good := store.Current()
	if err := client.SyncOnce(context.Background(), nil); err == nil {
		t.Fatal("expected bad signature to fail")
	}
	if store.Current() != good {
		t.Fatal("must preserve last good after bad signature")
	}
}

func TestRemoteSyncHeaderDigestMismatch(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, sig := signedFixture(t, priv, -time.Hour, time.Hour)
	metaBad := meta
	metaBad.rulesDigest = "sha256:" + strings.Repeat("b", 64)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeConfig200(w, body, metaBad, sig)
	}))
	t.Cleanup(srv.Close)

	store := snapshot.NewStore(pubPEM)
	client := remoteTestClient(t, srv.URL, store, 1<<20)
	if err := client.SyncOnce(context.Background(), nil); err == nil {
		t.Fatal("expected digest mismatch")
	}
	if store.Current() != nil {
		t.Fatal("must not activate on header mismatch")
	}
}

func TestRemoteSyncOversizedBody(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, sig := signedFixture(t, priv, -time.Hour, time.Hour)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeConfig200(w, body, meta, sig)
	}))
	t.Cleanup(srv.Close)

	store := snapshot.NewStore(pubPEM)
	client := remoteTestClient(t, srv.URL, store, 32)
	if err := client.SyncOnce(context.Background(), nil); err == nil {
		t.Fatal("expected oversize error")
	}
}

func TestRemoteSyncTimeoutAndCancel(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, sig := signedFixture(t, priv, -time.Hour, time.Hour)
	block := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		<-block
		writeConfig200(w, body, meta, sig)
	}))
	t.Cleanup(func() {
		close(block)
		srv.Close()
	})

	store := snapshot.NewStore(pubPEM)
	client := &snapshot.RemoteClient{
		HTTPClient:   snapshot.NewRemoteHTTPClient(50 * time.Millisecond),
		URL:          srv.URL,
		MaxBodyBytes: 1 << 20,
		Store:        store,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 80*time.Millisecond)
	defer cancel()
	if err := client.SyncOnce(ctx, nil); err == nil {
		t.Fatal("expected timeout/cancel error")
	}

	ctx2, cancel2 := context.WithCancel(context.Background())
	cancel2()
	if err := client.SyncOnce(ctx2, nil); err == nil {
		t.Fatal("expected cancelled error")
	}
}

func TestRemoteSyncExpiredConfig(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, sig := signedFixture(t, priv, -2*time.Hour, -time.Hour)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeConfig200(w, body, meta, sig)
	}))
	t.Cleanup(srv.Close)

	store := snapshot.NewStore(pubPEM)
	client := remoteTestClient(t, srv.URL, store, 1<<20)
	if err := client.SyncOnce(context.Background(), nil); err == nil {
		t.Fatal("expected expired config error")
	}
}

func TestRemoteSyncOptionalAuthAndOrgHeaders(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, sig := signedFixture(t, priv, -time.Hour, time.Hour)
	var auth, org string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		org = r.Header.Get("X-Org-Id")
		writeConfig200(w, body, meta, sig)
	}))
	t.Cleanup(srv.Close)

	store := snapshot.NewStore(pubPEM)
	client := &snapshot.RemoteClient{
		HTTPClient:    snapshot.NewRemoteHTTPClient(time.Second),
		URL:           srv.URL,
		Authorization: "Bearer test-token",
		OrgID:         "22222222-2222-4222-8222-222222222222",
		MaxBodyBytes:  1 << 20,
		Store:         store,
	}
	if err := client.SyncOnce(context.Background(), nil); err != nil {
		t.Fatalf("sync: %v", err)
	}
	if auth != "Bearer test-token" || org == "" {
		t.Fatalf("headers auth=%q org=%q", auth, org)
	}
}

func TestPollRemoteStopsOnContextCancel(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	body, meta, sig := signedFixture(t, priv, -time.Hour, time.Hour)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeConfig200(w, body, meta, sig)
	}))
	t.Cleanup(srv.Close)

	store := snapshot.NewStore(pubPEM)
	client := remoteTestClient(t, srv.URL, store, 1<<20)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		snapshot.PollRemote(ctx, client, 20*time.Millisecond)
		close(done)
	}()
	time.Sleep(60 * time.Millisecond)
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("poller did not stop after context cancel")
	}
}

type fixtureMeta struct {
	configDigest string
	rulesDigest  string
	keyID        string
	snapshotID   string
}

func signedFixture(t *testing.T, priv *ecdsa.PrivateKey, issuedOffset, expiresOffset time.Duration) ([]byte, fixtureMeta, string) {
	t.Helper()
	now := time.Now().UTC()
	meta := fixtureMeta{
		rulesDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		keyID:       "test-key-1",
		snapshotID:  "11111111-1111-4111-8111-111111111111",
	}
	cfg := map[string]any{
		"schema_revision": 1,
		"snapshot_id":     meta.snapshotID,
		"organization_id": "22222222-2222-4222-8222-222222222222",
		"project_id":      "33333333-3333-4333-8333-333333333333",
		"issued_at":       now.Add(issuedOffset).Format(time.RFC3339),
		"expires_at":      now.Add(expiresOffset).Format(time.RFC3339),
		"rules_digest":    meta.rulesDigest,
		"key_id":          meta.keyID,
		"deployments": []any{
			map[string]any{
				"id":       "44444444-4444-4444-8444-444444444444",
				"provider": "openai_compatible", "model": "gpt-test",
				"endpoint": "http://127.0.0.1:9", "credential_ref": "test",
				"region": "us-east-1", "jurisdiction": "US",
				"capabilities": []string{"chat", "streaming"},
				"priority":     1, "weight": 1,
			},
		},
		"routes": []any{
			map[string]any{
				"id":          "55555555-5555-4555-8555-555555555555",
				"agent_id":    "66666666-6666-4666-8666-666666666666",
				"environment": "dev", "alias": "gpt-test",
				"strategy": "priority", "deployment_ids": []string{"44444444-4444-4444-8444-444444444444"},
				"enforcement": "blocking",
			},
		},
		"workload_bindings": []any{
			map[string]any{
				"generation_id":   "77777777-7777-4777-8777-777777777777",
				"secret_hash":     "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
				"organization_id": "22222222-2222-4222-8222-222222222222",
				"project_id":      "33333333-3333-4333-8333-333333333333",
				"environment":     "dev", "modules": []string{"router"},
				"scopes": []string{"infer:chat"}, "allowed_model_patterns": []string{"*"},
			},
		},
	}
	raw, err := json.Marshal(cfg)
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(raw)
	meta.configDigest = fmt.Sprintf("sha256:%x", sum)
	return raw, meta, testutil.SignPayload(priv, raw)
}

func writeConfig200(w http.ResponseWriter, body []byte, meta fixtureMeta, sig string) {
	w.Header().Set("ETag", `"`+meta.configDigest+`"`)
	w.Header().Set("X-AAP-Config-Digest", meta.configDigest)
	w.Header().Set("X-AAP-Rules-Digest", meta.rulesDigest)
	w.Header().Set("X-AAP-Config-Key-Id", meta.keyID)
	w.Header().Set("X-AAP-Config-Signature", sig)
	w.Header().Set("X-AAP-Snapshot-Id", meta.snapshotID)
	w.WriteHeader(http.StatusOK)
	_, _ = io.WriteString(w, string(body))
}

func remoteTestClient(t *testing.T, url string, store *snapshot.Store, maxBody int64) *snapshot.RemoteClient {
	t.Helper()
	return &snapshot.RemoteClient{
		HTTPClient:   snapshot.NewRemoteHTTPClient(5 * time.Second),
		URL:          url,
		MaxBodyBytes: maxBody,
		Store:        store,
	}
}
