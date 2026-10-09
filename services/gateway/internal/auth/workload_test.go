package auth_test

import (
	"crypto/sha256"
	"testing"

	"agent-assurance/services/gateway/internal/auth"
	"agent-assurance/services/gateway/internal/snapshot"
)

func TestAuthenticateFromSnapshot(t *testing.T) {
	secret := make([]byte, 32)
	for i := range secret {
		secret[i] = byte(i)
	}
	org := "22222222-2222-4222-8222-222222222222"
	gen := "77777777-7777-4777-8777-777777777777"
	token := auth.FormatTestToken(org, gen, secret)
	snap := &snapshot.ActivatedSnapshot{
		Config:    snapshot.Config{OrganizationID: org},
		ByGenHash: map[[32]byte]snapshot.WorkloadBinding{},
	}
	key := sha256.Sum256(secret)
	snap.ByGenHash[key] = snapshot.WorkloadBinding{
		GenerationID: gen, OrganizationID: org, ProjectID: "33333333-3333-4333-8333-333333333333",
		Environment: "dev", Modules: []string{"router"}, Scopes: []string{"router:chat"},
		SecretHash: auth.SecretHashHex(secret),
	}
	p, err := auth.Authenticate(snap, token)
	if err != nil {
		t.Fatal(err)
	}
	if err := p.RequireScope("router:chat"); err != nil {
		t.Fatal(err)
	}
}
