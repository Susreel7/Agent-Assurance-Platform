package snapshot_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/snapshot"
	"agent-assurance/services/gateway/internal/testutil"
)

func TestLoadSignedSnapshot(t *testing.T) {
	priv, pubPEM := testutil.GenerateP256KeyPair()
	dir := t.TempDir()
	cfg := map[string]any{
		"schema_revision": 1,
		"snapshot_id":     "11111111-1111-4111-8111-111111111111",
		"organization_id": "22222222-2222-4222-8222-222222222222",
		"project_id":      "33333333-3333-4333-8333-333333333333",
		"issued_at":       time.Now().UTC().Add(-time.Hour).Format(time.RFC3339),
		"expires_at":      time.Now().UTC().Add(time.Hour).Format(time.RFC3339),
		"rules_digest":    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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
				"strategy":       "priority",
				"deployment_ids": []string{"44444444-4444-4444-8444-444444444444"},
				"enforcement":    "blocking",
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
	raw, _ := json.Marshal(cfg)
	sig := testutil.SignPayload(priv, raw)
	_ = os.WriteFile(filepath.Join(dir, snapshotConfigName()), raw, 0o600)
	_ = os.WriteFile(filepath.Join(dir, snapshotSigName()), []byte(sig), 0o600)
	store := snapshot.NewStore(pubPEM)
	if err := store.ReloadFromDir(dir); err != nil {
		t.Fatalf("reload: %v", err)
	}
	if store.Current() == nil {
		t.Fatal("expected activated snapshot")
	}
	badSig := testutil.SignPayload(priv, []byte("tampered"))
	_ = os.WriteFile(filepath.Join(dir, snapshotSigName()), []byte(badSig), 0o600)
	before := store.Current()
	if err := store.ReloadFromDir(dir); err == nil {
		t.Fatal("expected verify failure")
	}
	if store.Current() != before {
		t.Fatal("bad reload must preserve last-known-good")
	}
}

func snapshotConfigName() string { return "router.json" }
func snapshotSigName() string    { return "router.json.sig" }

func FuzzValidateConfigJSON(f *testing.F) {
	f.Add([]byte(`{"schema_revision":1}`))
	f.Fuzz(func(t *testing.T, b []byte) {
		var cfg snapshot.Config
		if json.Unmarshal(b, &cfg) != nil {
			return
		}
		_ = snapshot.ValidateConfig(&cfg, time.Now().UTC())
	})
}
