package sse

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"agent-assurance/services/gateway/internal/normalize"
)

// Relay copies upstream SSE to the client incrementally without buffering the full stream.
func Relay(w http.ResponseWriter, upstream io.Reader) (bytes int64, err error) {
	rec := &countWriter{ResponseWriter: w}
	_, err = RelayWithUsage(context.Background(), rec, upstream)
	return rec.n, err
}

type countWriter struct {
	http.ResponseWriter
	n int64
}

func (c *countWriter) Write(p []byte) (int, error) {
	n, err := c.ResponseWriter.Write(p)
	c.n += int64(n)
	return n, err
}

func (c *countWriter) Flush() {
	if f, ok := c.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func RelayWithUsage(ctx context.Context, w http.ResponseWriter, upstream io.Reader) (normalize.TokenUsage, error) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		return normalize.TokenUsage{EstimateOnly: true}, io.ErrClosedPipe
	}
	scanner := bufio.NewScanner(upstream)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	var usage normalize.TokenUsage
	for scanner.Scan() {
		if err := ctx.Err(); err != nil {
			return usage, err
		}
		line := scanner.Bytes()
		if u, ok := usageFromSSELine(line); ok {
			usage = u
		}
		if _, err := fmt.Fprintf(w, "%s\n\n", line); err != nil {
			return usage, err
		}
		flusher.Flush()
	}
	if err := scanner.Err(); err != nil {
		return usage, err
	}
	if usage.PromptTokens == 0 && usage.CompletionTokens == 0 {
		usage.EstimateOnly = true
	}
	return usage, nil
}

// RelayResponsesRaw passes OpenAI Responses SSE through without reformatting lines.
func RelayResponsesRaw(ctx context.Context, w http.ResponseWriter, upstream io.Reader) (normalize.TokenUsage, error) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		return normalize.TokenUsage{EstimateOnly: true}, io.ErrClosedPipe
	}
	var usage normalize.TokenUsage
	buf := make([]byte, 32*1024)
	var carry []byte
	for {
		if err := ctx.Err(); err != nil {
			return usage, err
		}
		n, err := upstream.Read(buf)
		if n > 0 {
			carry = append(carry, buf[:n]...)
			if u, ok := usageFromRawSSE(carry); ok {
				usage = u
			}
			if _, werr := w.Write(buf[:n]); werr != nil {
				return usage, werr
			}
			flusher.Flush()
		}
		if err == io.EOF {
			return usage, nil
		}
		if err != nil {
			return usage, err
		}
	}
}

func usageFromRawSSE(b []byte) (normalize.TokenUsage, bool) {
	for _, line := range bytes.Split(b, []byte("\n")) {
		if u, ok := usageFromSSELine(line); ok {
			return u, true
		}
	}
	return normalize.TokenUsage{}, false
}

func RelayResponses(ctx context.Context, w http.ResponseWriter, upstream io.Reader) (normalize.TokenUsage, error) {
	return RelayResponsesRaw(ctx, w, upstream)
}

func usageFromSSELine(line []byte) (normalize.TokenUsage, bool) {
	if !bytes.HasPrefix(line, []byte("data:")) {
		return normalize.TokenUsage{}, false
	}
	payload := bytes.TrimSpace(line[5:])
	if len(payload) == 0 || bytes.Equal(payload, []byte("[DONE]")) {
		return normalize.TokenUsage{}, false
	}
	if u, ok := normalize.UsageFromOpenAIChunk(payload); ok {
		return u, true
	}
	var resp struct {
		Response struct {
			Usage struct {
				InputTokens  int64 `json:"input_tokens"`
				OutputTokens int64 `json:"output_tokens"`
			} `json:"usage"`
		} `json:"response"`
		Type string `json:"type"`
	}
	if json.Unmarshal(payload, &resp) == nil && resp.Type == "response.completed" {
		if resp.Response.Usage.InputTokens > 0 || resp.Response.Usage.OutputTokens > 0 {
			return normalize.TokenUsage{
				PromptTokens:     resp.Response.Usage.InputTokens,
				CompletionTokens: resp.Response.Usage.OutputTokens,
			}, true
		}
	}
	return normalize.TokenUsage{}, false
}

func IsEventStream(h http.Header) bool {
	ct := h.Get("Content-Type")
	return strings.HasPrefix(ct, "text/event-stream") || ct == "application/x-ndjson"
}
