package limiter

import (
	"bufio"
	"context"
	"net"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestRedisEvalAcquireMock(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	go func() {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		r := bufio.NewReader(conn)
		for {
			line, err := r.ReadString('\n')
			if err != nil {
				return
			}
			if strings.HasPrefix(line, "*") {
				_, _ = r.ReadString('\n')
				for {
					l2, _ := r.ReadString('\n')
					if !strings.HasPrefix(l2, "$") {
						break
					}
					n, _ := strconv.Atoi(strings.TrimSpace(l2[1:]))
					buf := make([]byte, n+2)
					_, _ = r.Read(buf)
				}
				_, _ = conn.Write([]byte(":1\r\n"))
			}
		}
	}()
	rl := NewRedisLimiter("redis://" + ln.Addr().String())
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	tok, err := rl.Acquire(ctx, AcquireRequest{
		OrgID: "o", CredentialGen: "g", DeploymentID: "d", TokensEstimate: 10,
	}, LimitDimensions{}, LimitDimensions{}, LimitDimensions{})
	if err != nil {
		t.Fatal(err)
	}
	if tok.DeploymentID != "d" {
		t.Fatalf("dep=%s", tok.DeploymentID)
	}
}
