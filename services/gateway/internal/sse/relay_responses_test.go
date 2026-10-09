package sse_test

import (
	"bytes"
	"context"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/sse"
)

func TestRelayResponsesRawPassthrough(t *testing.T) {
	raw := "event: response.output_text.delta\n" +
		"data: {\"type\":\"response.output_text.delta\",\"delta\":\"hello\"}\n\n" +
		"data: {\"type\":\"response.completed\",\"response\":{\"usage\":{\"input_tokens\":1,\"output_tokens\":2}}}\n\n"
	rec := httptest.NewRecorder()
	usage, err := sse.RelayResponsesRaw(context.Background(), rec, strings.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	if rec.Body.String() != raw {
		t.Fatalf("passthrough mismatch:\nwant %q\ngot  %q", raw, rec.Body.String())
	}
	if usage.PromptTokens != 1 || usage.CompletionTokens != 2 {
		t.Fatalf("usage=%+v", usage)
	}
}

type blockAfterFirst struct {
	first []byte
	sent  bool
	ctx   context.Context
}

func (b *blockAfterFirst) Read(p []byte) (int, error) {
	if !b.sent {
		b.sent = true
		n := copy(p, b.first)
		return n, nil
	}
	<-b.ctx.Done()
	return 0, b.ctx.Err()
}

func TestRelayPassThroughCancelPropagates(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	up := &blockAfterFirst{first: []byte("data: {\"choices\":[]}\n\n"), ctx: ctx}
	rec := httptest.NewRecorder()
	go func() {
		time.Sleep(20 * time.Millisecond)
		cancel()
	}()
	_, err := sse.RelayResponsesRaw(ctx, rec, up)
	if err == nil {
		t.Fatal("expected context error")
	}
	if rec.Body.Len() == 0 {
		t.Fatal("expected at least one chunk before cancel")
	}
}

func TestRelayPassThroughOpenAIBytesUnmodified(t *testing.T) {
	raw := "data: {\"id\":\"1\",\"choices\":[{\"delta\":{\"content\":\"x\"}}]}\n\n"
	rec := httptest.NewRecorder()
	_, err := sse.RelayResponsesRaw(context.Background(), rec, strings.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(rec.Body.Bytes(), []byte(raw)) {
		t.Fatalf("modified relay: %q", rec.Body.String())
	}
}
