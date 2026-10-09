package normalize

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// StreamChatToResponsesSSE translates provider chat SSE into OpenAI Responses API event stream.
func StreamChatToResponsesSSE(ctx context.Context, provider string, upstream io.Reader, w http.ResponseWriter, modelAlias string) (TokenUsage, error) {
	fl, ok := w.(http.Flusher)
	if !ok {
		return TokenUsage{EstimateOnly: true}, fmt.Errorf("response writer does not flush")
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	respID := "resp_" + modelAlias
	created := time.Now().Unix()
	writeEv := func(typ string, payload any) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		b, _ := json.Marshal(payload)
		ev := map[string]any{"type": typ, "response": json.RawMessage(b)}
		if typ == "response.created" || typ == "response.completed" {
			ev = map[string]any{"type": typ, "response": payload}
		}
		out, _ := json.Marshal(ev)
		if _, err := fmt.Fprintf(w, "event: %s\ndata: %s\n\n", typ, out); err != nil {
			return err
		}
		fl.Flush()
		return nil
	}
	_ = writeEv("response.created", map[string]any{"id": respID, "object": "response", "created_at": created, "model": modelAlias})
	sc := bufio.NewScanner(upstream)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	var usage TokenUsage
	switch provider {
	case "anthropic", "bedrock", "gemini", "vertex":
		for sc.Scan() {
			if err := ctx.Err(); err != nil {
				return usage, err
			}
			line := sc.Bytes()
			text, tools, u, ok := chatLineToParts(provider, line)
			if u.PromptTokens > 0 || u.CompletionTokens > 0 {
				usage = u
			}
			if !ok {
				continue
			}
			if text != "" {
				if err := writeEv("response.output_text.delta", map[string]any{"delta": text, "output_index": 0}); err != nil {
					return usage, err
				}
			}
			if tools != "" {
				if err := writeEv("response.function_call_arguments.delta", map[string]any{"delta": tools, "output_index": 0}); err != nil {
					return usage, err
				}
			}
		}
	default:
		return TokenUsage{EstimateOnly: true}, fmt.Errorf("unsupported provider for responses stream translation")
	}
	if err := sc.Err(); err != nil {
		return usage, err
	}
	if usage.PromptTokens == 0 && usage.CompletionTokens == 0 {
		usage.EstimateOnly = true
	}
	_ = writeEv("response.completed", map[string]any{
		"id": respID, "status": "completed",
		"usage": map[string]any{"input_tokens": usage.PromptTokens, "output_tokens": usage.CompletionTokens},
	})
	return usage, nil
}

func chatLineToParts(provider string, line []byte) (text, tools string, usage TokenUsage, ok bool) {
	if !bytes.HasPrefix(line, []byte("data:")) {
		return "", "", TokenUsage{}, false
	}
	payload := bytes.TrimSpace(line[5:])
	if len(payload) == 0 {
		return "", "", TokenUsage{}, false
	}
	if u, found := UsageFromOpenAIChunk(payload); found {
		usage = u
	}
	switch provider {
	case "anthropic":
		var ev struct {
			Type  string `json:"type"`
			Delta struct {
				Text        string `json:"text"`
				PartialJSON string `json:"partial_json"`
			} `json:"delta"`
		}
		if json.Unmarshal(payload, &ev) != nil {
			return "", "", usage, false
		}
		if ev.Type == "content_block_delta" {
			return ev.Delta.Text, ev.Delta.PartialJSON, usage, ev.Delta.Text != "" || ev.Delta.PartialJSON != ""
		}
	}
	return "", "", usage, false
}
