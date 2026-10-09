package provider

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"strings"
	"time"
)

var defaultHTTPClient = &http.Client{
	Timeout: 0, // per-request context
	Transport: &http.Transport{
		MaxIdleConns:        256,
		MaxIdleConnsPerHost: 64,
		IdleConnTimeout:     90 * time.Second,
	},
}

func doUpstream(ctx context.Context, method, url string, headers map[string]string, body []byte) (*http.Response, error) {
	var r io.Reader
	if body != nil {
		r = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, url, r)
	if err != nil {
		return nil, err
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	if req.Header.Get("Content-Type") == "" {
		req.Header.Set("Content-Type", "application/json")
	}
	return defaultHTTPClient.Do(req)
}

func joinURL(base, path string) string {
	if strings.HasSuffix(base, "/") {
		base = base[:len(base)-1]
	}
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	return base + path
}

func cloneHeaders(h http.Header) http.Header {
	out := make(http.Header, len(h))
	for k, vv := range h {
		vv2 := make([]string, len(vv))
		copy(vv2, vv)
		out[k] = vv2
	}
	return out
}
