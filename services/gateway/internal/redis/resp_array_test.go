package redis

import (
	"bufio"
	"bytes"
	"testing"
)

func TestReadReplyArrayAndBulk(t *testing.T) {
	raw := "*2\r\n$3\r\nfoo\r\n$3\r\nbar\r\n"
	v, err := ReadReply(bufio.NewReader(bytes.NewReader([]byte(raw))))
	if err != nil {
		t.Fatal(err)
	}
	arr, ok := v.([]any)
	if !ok || len(arr) != 2 {
		t.Fatalf("arr=%v", v)
	}
	if arr[0] != "foo" || arr[1] != "bar" {
		t.Fatalf("elems=%v", arr)
	}
}

func TestReadReplyInteger(t *testing.T) {
	v, err := ReadReply(bufio.NewReader(bytes.NewReader([]byte(":42\r\n"))))
	if err != nil || v.(int64) != 42 {
		t.Fatalf("v=%v err=%v", v, err)
	}
}
