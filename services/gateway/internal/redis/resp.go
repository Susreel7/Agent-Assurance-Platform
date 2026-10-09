package redis

import (
	"bufio"
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

var ErrNil = errors.New("redis nil")

type Client struct {
	addr     string
	password string
	db       int
	tlsCfg   *tls.Config
	dialTO   time.Duration
}

func ParseURL(raw string) (*Client, error) {
	if raw == "" {
		return nil, errors.New("redis url empty")
	}
	if !strings.Contains(raw, "://") {
		raw = "redis://" + raw
	}
	u, err := url.Parse(raw)
	if err != nil {
		return nil, err
	}
	c := &Client{dialTO: 2 * time.Second, db: 0}
	switch u.Scheme {
	case "redis", "rediss":
	default:
		return nil, fmt.Errorf("unsupported redis scheme %q", u.Scheme)
	}
	host := u.Host
	if host == "" {
		return nil, errors.New("redis host required")
	}
	c.addr = host
	if u.User != nil {
		c.password, _ = u.User.Password()
	}
	if p := strings.TrimPrefix(u.Path, "/"); p != "" {
		c.db, err = strconv.Atoi(p)
		if err != nil {
			return nil, err
		}
	}
	if u.Scheme == "rediss" {
		c.tlsCfg = &tls.Config{MinVersion: tls.VersionTLS12}
		if ca := os.Getenv("GATEWAY_REDIS_TLS_CA"); ca != "" {
			pool := x509.NewCertPool()
			b, err := os.ReadFile(ca)
			if err != nil {
				return nil, err
			}
			pool.AppendCertsFromPEM(b)
			c.tlsCfg.RootCAs = pool
		}
	}
	return c, nil
}

func (c *Client) Ping(ctx context.Context) error {
	_, err := c.Do(ctx, "PING")
	return err
}

func (c *Client) Do(ctx context.Context, args ...any) (any, error) {
	conn, err := c.dial(ctx)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	if err := conn.SetDeadline(deadline(ctx)); err != nil {
		return nil, err
	}
	if err := writeCommand(conn, args...); err != nil {
		return nil, err
	}
	return ReadReply(bufio.NewReader(conn))
}

func (c *Client) Eval(ctx context.Context, script string, keys []string, args ...any) (any, error) {
	all := make([]any, 0, 3+len(keys)+len(args))
	all = append(all, "EVAL", script, len(keys))
	for _, k := range keys {
		all = append(all, k)
	}
	all = append(all, args...)
	return c.Do(ctx, all...)
}

func (c *Client) dial(ctx context.Context) (net.Conn, error) {
	d := net.Dialer{Timeout: c.dialTO}
	var conn net.Conn
	var err error
	if c.tlsCfg != nil {
		conn, err = d.DialContext(ctx, "tcp", c.addr)
		if err != nil {
			return nil, err
		}
		conn = tls.Client(conn, c.tlsCfg)
	} else {
		conn, err = d.DialContext(ctx, "tcp", c.addr)
	}
	if err != nil {
		return nil, err
	}
	if c.password != "" {
		if _, err := c.authConn(conn, c.password); err != nil {
			_ = conn.Close()
			return nil, err
		}
	}
	if c.db != 0 {
		if _, err := c.selectDB(conn, c.db); err != nil {
			_ = conn.Close()
			return nil, err
		}
	}
	return conn, nil
}

func (c *Client) authConn(conn net.Conn, pass string) (any, error) {
	_ = conn.SetDeadline(time.Now().Add(c.dialTO))
	if err := writeCommand(conn, "AUTH", pass); err != nil {
		return nil, err
	}
	return ReadReply(bufio.NewReader(conn))
}

func (c *Client) selectDB(conn net.Conn, db int) (any, error) {
	if err := writeCommand(conn, "SELECT", db); err != nil {
		return nil, err
	}
	return ReadReply(bufio.NewReader(conn))
}

func deadline(ctx context.Context) time.Time {
	if d, ok := ctx.Deadline(); ok {
		return d
	}
	return time.Now().Add(5 * time.Second)
}

func writeCommand(w io.Writer, args ...any) error {
	var b strings.Builder
	b.WriteString("*")
	b.WriteString(strconv.Itoa(len(args)))
	b.WriteString("\r\n")
	for _, a := range args {
		s := fmt.Sprint(a)
		b.WriteString("$")
		b.WriteString(strconv.Itoa(len(s)))
		b.WriteString("\r\n")
		b.WriteString(s)
		b.WriteString("\r\n")
	}
	_, err := io.WriteString(w, b.String())
	return err
}

// ReadReply parses any RESP2 reply (simple, bulk, integer, array, error, nil).
func ReadReply(r *bufio.Reader) (any, error) {
	line, err := r.ReadString('\n')
	if err != nil {
		return nil, err
	}
	if len(line) < 1 {
		return nil, errors.New("empty redis reply")
	}
	switch line[0] {
	case '+':
		payload := strings.TrimSuffix(line[1:], "\r\n")
		if payload == "OK" {
			return true, nil
		}
		return payload, nil
	case '-':
		return nil, errors.New(strings.TrimSpace(line[1:]))
	case ':':
		n, _ := strconv.ParseInt(strings.TrimSpace(line[1:]), 10, 64)
		return n, nil
	case '$':
		n, _ := strconv.Atoi(strings.TrimSpace(line[1:]))
		if n < 0 {
			return nil, ErrNil
		}
		buf := make([]byte, n+2)
		if _, err := io.ReadFull(r, buf); err != nil {
			return nil, err
		}
		return string(buf[:n]), nil
	case '*':
		n, _ := strconv.Atoi(strings.TrimSpace(line[1:]))
		if n < 0 {
			return nil, ErrNil
		}
		arr := make([]any, n)
		for i := 0; i < n; i++ {
			el, err := ReadReply(r)
			if err != nil {
				return nil, err
			}
			arr[i] = el
		}
		return arr, nil
	default:
		return nil, fmt.Errorf("unsupported redis prefix %q", line[0])
	}
}

func readReply(r *bufio.Reader) (any, error) { return ReadReply(r) }
