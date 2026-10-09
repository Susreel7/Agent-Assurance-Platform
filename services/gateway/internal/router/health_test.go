package router_test

import (
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/router"
	"agent-assurance/services/gateway/internal/snapshot"
)

func TestCooldownExcludesThenHalfOpen(t *testing.T) {
	h := router.NewHealthRegistry()
	dep := snapshot.Deployment{ID: "d1", Cooldown: snapshot.CooldownPolicy{FailureThreshold: 2, InitialCooldownMS: 500, MaxCooldownMS: 5000}}
	pol := dep.Cooldown
	h.RecordFailure(dep.ID, pol)
	h.RecordFailure(dep.ID, pol)
	now := time.Now().UTC()
	if h.Available(dep, now) {
		t.Fatal("expected cooling")
	}
	future := now.Add(2 * time.Second)
	if !h.Available(dep, future) {
		t.Fatal("expected half-open probe")
	}
}
