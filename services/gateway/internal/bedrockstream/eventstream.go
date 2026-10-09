package bedrockstream

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"hash/crc32"
	"io"
)

const MaxFrame = 10 << 20

var (
	ErrFrameTooLarge = errors.New("bedrock frame too large")
	ErrBadCRC        = errors.New("bedrock frame crc mismatch")
)

type Event struct {
	Headers map[string]string
	Payload []byte
}

func ReadEvent(r io.Reader) (Event, error) {
	var prelude [12]byte
	if _, err := io.ReadFull(r, prelude[:]); err != nil {
		return Event{}, err
	}
	totalLen := binary.BigEndian.Uint32(prelude[0:4])
	headerLen := binary.BigEndian.Uint32(prelude[4:8])
	preludeCRC := binary.BigEndian.Uint32(prelude[8:12])
	if crc32.ChecksumIEEE(prelude[:8]) != preludeCRC {
		return Event{}, ErrBadCRC
	}
	if totalLen < 16 || totalLen > MaxFrame {
		return Event{}, ErrFrameTooLarge
	}
	rest := make([]byte, totalLen-12)
	if _, err := io.ReadFull(r, rest); err != nil {
		return Event{}, err
	}
	msgCRC := binary.BigEndian.Uint32(rest[len(rest)-4:])
	body := append(prelude[:], rest[:len(rest)-4]...)
	if crc32.ChecksumIEEE(body) != msgCRC {
		return Event{}, ErrBadCRC
	}
	headers := decodeEventHeaders(rest[:headerLen])
	payloadEnd := len(rest) - 4
	payload := rest[headerLen:payloadEnd]
	return Event{Headers: headers, Payload: payload}, nil
}

func decodeEventHeaders(b []byte) map[string]string {
	out := map[string]string{}
	i := 0
	for i+2 <= len(b) {
		nameLen := int(b[i])
		i++
		if i+nameLen+3 > len(b) {
			break
		}
		name := string(b[i : i+nameLen])
		i += nameLen
		typ := b[i]
		i++
		valLen := int(binary.BigEndian.Uint16(b[i : i+2]))
		i += 2
		if i+valLen > len(b) {
			break
		}
		val := string(b[i : i+valLen])
		i += valLen
		if typ == 7 {
			out[name] = val
		}
	}
	return out
}

func ParseConversePayload(payload []byte) (map[string]any, error) {
	var v map[string]any
	if err := json.Unmarshal(payload, &v); err != nil {
		return nil, err
	}
	return v, nil
}

func EncodeTestFrame(headers map[string]string, payload []byte) []byte {
	hb := encodeEventHeaders(headers)
	preludeLen := 12 + len(hb) + len(payload) + 4
	buf := make([]byte, preludeLen)
	binary.BigEndian.PutUint32(buf[0:4], uint32(preludeLen))
	binary.BigEndian.PutUint32(buf[4:8], uint32(len(hb)))
	binary.BigEndian.PutUint32(buf[8:12], crc32.ChecksumIEEE(buf[0:8]))
	copy(buf[12:], hb)
	copy(buf[12+len(hb):], payload)
	binary.BigEndian.PutUint32(buf[preludeLen-4:], crc32.ChecksumIEEE(buf[:preludeLen-4]))
	return buf
}

func encodeEventHeaders(h map[string]string) []byte {
	var b []byte
	for k, v := range h {
		b = append(b, byte(len(k)))
		b = append(b, k...)
		b = append(b, 7)
		b = append(b, byte(len(v)>>8), byte(len(v)))
		b = append(b, v...)
	}
	return b
}

func ExtractDelta(m map[string]any) string {
	if d, ok := m["contentBlockDelta"].(map[string]any); ok {
		if delta, ok := d["delta"].(map[string]any); ok {
			if t, ok := delta["text"].(string); ok {
				return t
			}
		}
	}
	return ""
}

func ExtractToolUseDelta(m map[string]any) string {
	if d, ok := m["contentBlockDelta"].(map[string]any); ok {
		if delta, ok := d["delta"].(map[string]any); ok {
			if t, ok := delta["toolUse"].(map[string]any); ok {
				if inp, ok := t["input"].(string); ok {
					return inp
				}
			}
		}
	}
	return ""
}
