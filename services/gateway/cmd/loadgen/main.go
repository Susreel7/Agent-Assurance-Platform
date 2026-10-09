package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"sync"
	"sync/atomic"
	"time"
)

func main() {
	base := flag.String("url", "http://127.0.0.1:8080", "gateway base URL")
	token := flag.String("token", "", "bearer token")
	agent := flag.String("agent", "", "X-AAP-Agent-Id")
	rps := flag.Int("rps", 100, "target RPS for non-stream phase")
	streams := flag.Int("streams", 50, "concurrent streaming requests")
	duration := flag.Duration("duration", 10*time.Second, "non-stream phase duration")
	flag.Parse()
	if *token == "" || *agent == "" {
		fmt.Fprintln(os.Stderr, "token and agent required")
		os.Exit(2)
	}
	client := &http.Client{Timeout: 120 * time.Second}
	var latencies []int64
	var mu sync.Mutex
	var okCount, errCount int64
	stop := time.Now().Add(*duration)
	var wg sync.WaitGroup
	tick := time.NewTicker(time.Second / time.Duration(max(1, *rps)))
	defer tick.Stop()
	for time.Now().Before(stop) {
		<-tick.C
		wg.Add(1)
		go func() {
			defer wg.Done()
			start := time.Now()
			body := []byte(`{"model":"gpt-test","messages":[{"role":"user","content":"ping"}]}`)
			req, _ := http.NewRequest(http.MethodPost, *base+"/v1/chat/completions", bytes.NewReader(body))
			req.Header.Set("Authorization", "Bearer "+*token)
			req.Header.Set("X-AAP-Agent-Id", *agent)
			req.Header.Set("Content-Type", "application/json")
			res, err := client.Do(req)
			ms := time.Since(start).Milliseconds()
			mu.Lock()
			latencies = append(latencies, ms)
			mu.Unlock()
			if err != nil || res.StatusCode >= 300 {
				atomic.AddInt64(&errCount, 1)
				return
			}
			atomic.AddInt64(&okCount, 1)
			_, _ = io.Copy(io.Discard, res.Body)
			_ = res.Body.Close()
		}()
	}
	wg.Wait()
	for i := 0; i < *streams; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			start := time.Now()
			body := []byte(`{"model":"gpt-test","stream":true,"messages":[{"role":"user","content":"ping"}]}`)
			req, _ := http.NewRequest(http.MethodPost, *base+"/v1/chat/completions", bytes.NewReader(body))
			req.Header.Set("Authorization", "Bearer "+*token)
			req.Header.Set("X-AAP-Agent-Id", *agent)
			req.Header.Set("Content-Type", "application/json")
			res, err := client.Do(req)
			ms := time.Since(start).Milliseconds()
			mu.Lock()
			latencies = append(latencies, ms)
			mu.Unlock()
			if err != nil || res.StatusCode >= 300 {
				atomic.AddInt64(&errCount, 1)
				return
			}
			atomic.AddInt64(&okCount, 1)
			_, _ = io.Copy(io.Discard, res.Body)
			_ = res.Body.Close()
		}()
	}
	wg.Wait()
	sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })
	out := map[string]any{
		"ok": okCount, "errors": errCount, "samples": len(latencies),
		"p50_ms": pct(latencies, 50), "p95_ms": pct(latencies, 95), "p99_ms": pct(latencies, 99),
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	_ = enc.Encode(out)
}

func pct(v []int64, p int) int64 {
	if len(v) == 0 {
		return 0
	}
	i := (len(v) * p) / 100
	if i >= len(v) {
		i = len(v) - 1
	}
	return v[i]
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
