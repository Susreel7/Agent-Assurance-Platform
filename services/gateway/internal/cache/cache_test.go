package cache_test

import (
	"context"
	"os"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/cache"
)

func TestCacheKeyCrossTenantIsolation(t *testing.T) {
	a := cache.CacheKey("org1", "g1", "r1", "chat", "digest1", "req1")
	b := cache.CacheKey("org2", "g1", "r1", "chat", "digest1", "req1")
	if a == b {
		t.Fatal("keys must differ by org")
	}
	c := cache.CacheKey("org1", "g2", "r1", "chat", "digest1", "req1")
	if a == c {
		t.Fatal("keys must differ by credential generation")
	}
	d := cache.CacheKey("org1", "g1", "r1", "embeddings", "digest1", "req1")
	if a == d {
		t.Fatal("keys must differ by operation")
	}
}

func TestPutAsyncAndGetRoundTrip(t *testing.T) {
	addr := os.Getenv("GATEWAY_TEST_REDIS_ADDR")
	if addr == "" {
		t.Skip("set GATEWAY_TEST_REDIS_ADDR to run redis integration test")
	}
	rc, err := cache.NewResponseCache(addr, 4096)
	if err != nil {
		t.Fatal(err)
	}
	defer rc.Close()
	key := cache.CacheKey("o", "g", "r", "responses", "d", "req")
	entry := cache.CachedResponse{
		Status: 200, Body: []byte(`{"ok":true}`), ConfigDigest: "d",
		Headers: map[string]string{"Content-Type": "application/json"},
	}
	if err := rc.PutAsync(key, entry, time.Minute); err != nil {
		t.Fatal(err)
	}
	time.Sleep(300 * time.Millisecond)
	got, err := rc.Get(context.Background(), key)
	if err != nil {
		t.Fatal(err)
	}
	if string(got.Body) != string(entry.Body) || got.ConfigDigest != "d" {
		t.Fatalf("got=%+v", got)
	}
}

func TestCacheFlushAndDroppedOnClose(t *testing.T) {
	addr := os.Getenv("GATEWAY_TEST_REDIS_ADDR")
	if addr == "" {
		t.Skip("set GATEWAY_TEST_REDIS_ADDR")
	}
	rc, err := cache.NewResponseCache(addr, 4096)
	if err != nil {
		t.Fatal(err)
	}
	key := cache.CacheKey("o", "g", "r", "chat", "d", "req-close")
	entry := cache.CachedResponse{Status: 200, Body: []byte(`{"z":1}`), ConfigDigest: "d"}
	if err := rc.PutAsync(key, entry, time.Minute); err != nil {
		t.Fatal(err)
	}
	if err := rc.Flush(context.Background()); err != nil {
		t.Fatal(err)
	}
	got, err := rc.Get(context.Background(), key)
	if err != nil || string(got.Body) != `{"z":1}` {
		t.Fatalf("flush miss: err=%v got=%v", err, got)
	}
	before := rc.DroppedWrites()
	_ = rc.PutAsync("k2", entry, time.Minute)
	rc.Close()
	if err := rc.PutAsync("k3", entry, time.Minute); err != cache.ErrCacheClosed {
		t.Fatalf("expected closed, got %v", err)
	}
	if rc.DroppedWrites() <= before {
		t.Fatalf("expected dropped write counter to increase")
	}
}

func TestCacheRejectsOversizeBody(t *testing.T) {
	addr := os.Getenv("GATEWAY_TEST_REDIS_ADDR")
	if addr == "" {
		t.Skip("set GATEWAY_TEST_REDIS_ADDR")
	}
	rc, err := cache.NewResponseCache(addr, 10)
	if err != nil {
		t.Fatal(err)
	}
	defer rc.Close()
	err = rc.PutAsync("k", cache.CachedResponse{Body: []byte("012345678901")}, time.Minute)
	if err == nil {
		t.Fatal("expected oversize error")
	}
}
