package handler

import (
	"net/http/httptest"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/auth"
	"agent-assurance/services/gateway/internal/provider"
	"agent-assurance/services/gateway/internal/snapshot"
)

func TestRevalidateBlocksRevokedCredential(t *testing.T) {
	w := httptest.NewRecorder()
	rev := time.Now().UTC().Add(-time.Hour)
	ok := RevalidateFallbackAttempt(w, RevalidateInput{
		Snap:  &snapshot.ActivatedSnapshot{Config: snapshot.Config{OrganizationID: "o"}},
		Route: snapshot.Route{AgentID: "a", Environment: "dev"},
		Principal: auth.Principal{
			OrganizationID: "o",
			Modules:        map[string]struct{}{"router": {}},
			Scopes:         map[string]struct{}{"router:chat": {}},
		},
		Binding: snapshot.WorkloadBinding{OrganizationID: "o", RevokedAt: &rev},
		AgentID: "a", Environment: "dev", ModelAlias: "m", Scope: "router:chat",
		Operation: provider.OpChat, DepID: "d",
	})
	if ok {
		t.Fatal("expected false")
	}
}
