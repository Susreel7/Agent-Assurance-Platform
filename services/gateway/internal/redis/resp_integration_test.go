//go:build integration

package redis

import (
	"context"
	"os"
	"testing"
	"time"
)

func TestRealRedisPingAndEval(t *testing.T) {
	addr := os.Getenv("GATEWAY_TEST_REDIS_ADDR")
	if addr == "" {
		t.Skip("GATEWAY_TEST_REDIS_ADDR not set")
	}
	c, err := ParseURL(addr)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := c.Ping(ctx); err != nil {
		t.Fatal(err)
	}
	v, err := c.Eval(ctx, "return 1", nil)
	if err != nil {
		// Redis < 7 may not support return in lua; use classic script
		v, err = c.Eval(ctx, "return 1", []string{})
	}
	_ = v
	if err != nil {
		v, err = c.Do(ctx, "EVAL", "return 1", 0)
	}
	if err != nil {
		t.Fatalf("eval: %v", err)
	}
}
