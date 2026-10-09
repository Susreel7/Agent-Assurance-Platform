package normalize_test

import (
	"testing"

	"agent-assurance/services/gateway/internal/normalize"
)

func TestUsageFromOpenAIChatActual(t *testing.T) {
	body := []byte(`{"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}`)
	u := normalize.UsageFromOpenAIChat(body)
	if u.EstimateOnly || u.PromptTokens != 10 || u.CompletionTokens != 5 {
		t.Fatalf("u=%+v", u)
	}
}

func TestUsageFromOpenAIChatEstimateOnlyWhenMissing(t *testing.T) {
	u := normalize.UsageFromOpenAIChat([]byte(`{"choices":[]}`))
	if !u.EstimateOnly {
		t.Fatal("expected estimate only")
	}
}

func TestUsageFromOpenAIChunk(t *testing.T) {
	chunk := []byte(`{"usage":{"prompt_tokens":1,"completion_tokens":2}}`)
	u, ok := normalize.UsageFromOpenAIChunk(chunk)
	if !ok || u.PromptTokens != 1 {
		t.Fatalf("u=%+v ok=%v", u, ok)
	}
}
