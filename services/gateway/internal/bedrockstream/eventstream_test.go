package bedrockstream

import (
	"bytes"
	"encoding/json"
	"testing"
)

func TestReadEventCRC(t *testing.T) {
	payload, _ := json.Marshal(map[string]any{"contentBlockDelta": map[string]any{"delta": map[string]any{"text": "hi"}}})
	frame := EncodeTestFrame(map[string]string{":message-type": "event"}, payload)
	ev, err := ReadEvent(bytes.NewReader(frame))
	if err != nil {
		t.Fatal(err)
	}
	if ev.Headers[":message-type"] != "event" {
		t.Fatal("header mismatch")
	}
}

func TestMalformedCRC(t *testing.T) {
	frame := EncodeTestFrame(map[string]string{}, []byte("{}"))
	frame[len(frame)-1] ^= 0xff
	_, err := ReadEvent(bytes.NewReader(frame))
	if err != ErrBadCRC {
		t.Fatalf("expected crc error, got %v", err)
	}
}
