package redis

import (
	"bufio"
	"bytes"
	"testing"
)

func TestWriteReadOK(t *testing.T) {
	v, err := readReply(bufio.NewReader(bytes.NewReader([]byte("+PONG\r\n"))))
	if err != nil || v != "PONG" {
		t.Fatalf("got %v %v", v, err)
	}
}

func TestWriteCommandPing(t *testing.T) {
	var buf bytes.Buffer
	if err := writeCommand(&buf, "PING"); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("PING")) {
		t.Fatalf("payload %q", buf.Bytes())
	}
}
