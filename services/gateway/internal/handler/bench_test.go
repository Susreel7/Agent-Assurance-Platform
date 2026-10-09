package handler_test

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"sort"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/audit"
	"agent-assurance/services/gateway/internal/config"
	"agent-assurance/services/gateway/internal/credentials"
	"agent-assurance/services/gateway/internal/handler"
	"agent-assurance/services/gateway/internal/limiter"
	"agent-assurance/services/gateway/internal/router"
	"agent-assurance/services/gateway/internal/snapshot"
)

func BenchmarkGatewayOverhead(b *testing.B) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()
	dir, token := installSnapshot(b, upstream.URL)
	store := snapshot.NewStore(readPubPEM(b, dir))
	_ = store.ReloadFromDir(dir)
	creds, _ := credentials.LoadFromFile(filepath.Join(dir, "credentials.json"))
	srv := &handler.Server{
		Settings: config.Settings{
			MaxRequestBodyBytes: 1 << 20, MaxResponseBodyBytes: 1 << 20,
			DefaultUpstreamTimeout: 5 * time.Second, DevAllowInsecureLimiter: true,
		},
		Snapshots: store, Credentials: creds, LocalLimit: limiter.NewMemoryLimiter(),
		GlobalLimit: limiter.NewRedisLimiter(""), Selector: router.NewSelector(limiter.NewMemoryLimiter()),
		Audit: audit.NewQueue(128),
	}
	body := []byte(`{"model":"gpt-test","messages":[{"role":"user","content":"hi"}]}`)
	latencies := make([]time.Duration, 0, b.N)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		start := time.Now()
		req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("X-AAP-Agent-Id", "66666666-6666-4666-8666-666666666666")
		rec := httptest.NewRecorder()
		srv.Handler().ServeHTTP(rec, req)
		latencies = append(latencies, time.Since(start))
	}
	sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })
	if len(latencies) > 0 {
		b.ReportMetric(float64(latencies[len(latencies)*50/100].Microseconds()), "p50_us")
		b.ReportMetric(float64(latencies[len(latencies)*95/100].Microseconds()), "p95_us")
		b.ReportMetric(float64(latencies[len(latencies)*99/100].Microseconds()), "p99_us")
	}
}
