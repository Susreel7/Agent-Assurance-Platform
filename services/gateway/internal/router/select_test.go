package router_test

import (
	"testing"

	"agent-assurance/services/gateway/internal/limiter"
	"agent-assurance/services/gateway/internal/router"
	"agent-assurance/services/gateway/internal/snapshot"
)

func TestWeightedShuffleCoversAll(t *testing.T) {
	sel := router.NewSelector(limiter.NewMemoryLimiter())
	deps := []snapshot.Deployment{
		{ID: "a", Weight: 1},
		{ID: "b", Weight: 2},
		{ID: "c", Weight: 3},
	}
	route := snapshot.Route{Strategy: "weighted", DeploymentIDs: []string{"a", "b", "c"}}
	out := sel.Order(route, deps)
	if len(out) != 3 {
		t.Fatalf("len=%d", len(out))
	}
	seen := map[string]bool{}
	for _, c := range out {
		seen[c.Deployment.ID] = true
	}
	for _, id := range []string{"a", "b", "c"} {
		if !seen[id] {
			t.Fatalf("missing %s", id)
		}
	}
}

func TestLowestCostOrdersByPrice(t *testing.T) {
	sel := router.NewSelector(limiter.NewMemoryLimiter())
	deps := []snapshot.Deployment{
		{ID: "expensive", Priority: 1, InputPriceMicrosPerM: 100, OutputPriceMicrosPerM: 100},
		{ID: "cheap", Priority: 99, InputPriceMicrosPerM: 1, OutputPriceMicrosPerM: 1},
	}
	route := snapshot.Route{Strategy: "lowest_cost"}
	out := sel.Order(route, deps)
	if out[0].Deployment.ID != "cheap" {
		t.Fatalf("first=%s", out[0].Deployment.ID)
	}
}
