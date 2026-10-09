//go:build integration

package limiter_test

import (
	"context"
	"os"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/limiter"
)

func TestRedisAcquireReconcileIntegration(t *testing.T) {
	addr := os.Getenv("GATEWAY_TEST_REDIS_ADDR")
	if addr == "" {
		t.Skip("GATEWAY_TEST_REDIS_ADDR not set")
	}
	rl := limiter.NewRedisLimiter(addr)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := rl.Ready(ctx); err != nil {
		t.Fatal(err)
	}
	maxC := 2
	dim := limiter.LimitDimensions{MaxConcurrency: &maxC}
	tok, err := rl.Acquire(ctx, limiter.AcquireRequest{
		OrgID: "itest", CredentialGen: "g1", DeploymentID: "dep1", TokensEstimate: 1, CostMicrosEst: 0,
	}, dim, limiter.LimitDimensions{}, limiter.LimitDimensions{})
	if err != nil {
		t.Fatal(err)
	}
	if err := rl.Reconcile(ctx, tok, 1, 0); err != nil {
		t.Fatal(err)
	}
}
