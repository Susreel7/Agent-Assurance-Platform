package normalize_test

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http/httptest"
	"strings"
	"testing"

	"agent-assurance/services/gateway/internal/bedrockstream"
	"agent-assurance/services/gateway/internal/normalize"
)

type errAfter struct {
	data []byte
	off  int
	err  error
}

func (e *errAfter) Read(p []byte) (int, error) {
	if e.off >= len(e.data) {
		return 0, e.err
	}
	n := copy(p, e.data[e.off:])
	e.off += n
	if e.off >= len(e.data) {
		return n, e.err
	}
	return n, nil
}

func assertNoDone(t *testing.T, body string) {
	t.Helper()
	if strings.Contains(body, "[DONE]") {
		t.Fatalf("must not synthesize [DONE] on partial failure, body=%q", body)
	}
}

func TestStreamAnthropicMalformedAndPartialDisconnect(t *testing.T) {
	t.Run("malformed_json_skipped", func(t *testing.T) {
		up := strings.NewReader("data: not-json\n\ndata: {\"type\":\"content_block_delta\",\"delta\":{\"type\":\"text_delta\",\"text\":\"ok\"}}\n\n")
		rec := httptest.NewRecorder()
		_, err := normalize.StreamAnthropicToOpenAI(context.Background(), up, rec, "alias")
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(rec.Body.String(), "ok") {
			t.Fatalf("expected normalized chunk, got %q", rec.Body.String())
		}
	})
	t.Run("partial_upstream_no_done", func(t *testing.T) {
		line := `data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"partial"}}` + "\n\n"
		up := &errAfter{data: []byte(line), err: io.ErrUnexpectedEOF}
		rec := httptest.NewRecorder()
		_, err := normalize.StreamAnthropicToOpenAI(context.Background(), up, rec, "alias")
		if err == nil {
			t.Fatal("expected upstream error")
		}
		if !strings.Contains(rec.Body.String(), "partial") {
			t.Fatal("expected partial bytes")
		}
		assertNoDone(t, rec.Body.String())
	})
}

func TestStreamGeminiMalformedAndPartialDisconnect(t *testing.T) {
	t.Run("malformed_skipped", func(t *testing.T) {
		up := strings.NewReader("data: {broken\n\ndata: {\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"g\"}]}}]}\n\n")
		rec := httptest.NewRecorder()
		_, err := normalize.StreamGeminiSSEToOpenAI(context.Background(), up, rec, "alias")
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(rec.Body.String(), "g") {
			t.Fatalf("body=%q", rec.Body.String())
		}
	})
	t.Run("partial_no_done", func(t *testing.T) {
		line := `data: {"candidates":[{"content":{"parts":[{"text":"x"}]}}]}` + "\n\n"
		up := &errAfter{data: []byte(line), err: io.ErrUnexpectedEOF}
		rec := httptest.NewRecorder()
		_, err := normalize.StreamGeminiSSEToOpenAI(context.Background(), up, rec, "alias")
		if err == nil {
			t.Fatal("expected error")
		}
		assertNoDone(t, rec.Body.String())
	})
}

func TestStreamBedrockMalformedAndPartialDisconnect(t *testing.T) {
	deltaPayload, _ := json.Marshal(map[string]any{
		"contentBlockDelta": map[string]any{"delta": map[string]any{"text": "b"}},
	})
	frame := bedrockstream.EncodeTestFrame(map[string]string{":message-type": "event"}, deltaPayload)
	t.Run("bad_crc_skipped_loop", func(t *testing.T) {
		bad := append([]byte(nil), frame...)
		bad[len(bad)-1] ^= 0xff
		rec := httptest.NewRecorder()
		_, err := normalize.StreamBedrockConverseToOpenAI(context.Background(), bytes.NewReader(bad), rec, "alias")
		if err == nil {
			t.Fatal("expected crc/read error")
		}
	})
	t.Run("partial_no_done", func(t *testing.T) {
		up := &errAfter{data: frame, err: io.ErrUnexpectedEOF}
		rec := httptest.NewRecorder()
		_, err := normalize.StreamBedrockConverseToOpenAI(context.Background(), up, rec, "alias")
		if err == nil {
			t.Fatal("expected disconnect error")
		}
		if !strings.Contains(rec.Body.String(), "b") {
			t.Fatalf("body=%q", rec.Body.String())
		}
		assertNoDone(t, rec.Body.String())
	})
	t.Run("complete_with_message_stop", func(t *testing.T) {
		stopPayload, _ := json.Marshal(map[string]any{"messageStop": map[string]any{"stopReason": "end_turn"}})
		stopFrame := bedrockstream.EncodeTestFrame(map[string]string{":message-type": "event"}, stopPayload)
		up := io.MultiReader(bytes.NewReader(frame), bytes.NewReader(stopFrame))
		rec := httptest.NewRecorder()
		_, err := normalize.StreamBedrockConverseToOpenAI(context.Background(), up, rec, "alias")
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(rec.Body.String(), "[DONE]") {
			t.Fatal("expected DONE on clean completion")
		}
	})
}

func TestStreamClientCancel(t *testing.T) {
	line := `data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"a"}}` + "\n\n"
	line += line
	up := strings.NewReader(line)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	rec := httptest.NewRecorder()
	_, err := normalize.StreamAnthropicToOpenAI(ctx, up, rec, "alias")
	if err == nil {
		t.Fatal("expected cancel")
	}
}
