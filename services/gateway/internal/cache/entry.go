package cache

import (
	"context"
	"encoding/json"
	"errors"
	"sync"
	"sync/atomic"
	"time"

	"agent-assurance/services/gateway/internal/redis"
)

const defaultMaxTTL = 24 * time.Hour

var ErrCacheClosed = errors.New("cache closed")

// CachedResponse stores exact normalized response bytes and metadata for exact replay.
type CachedResponse struct {
	Status       int               `json:"status"`
	Headers      map[string]string `json:"headers"`
	Body         []byte            `json:"body"`
	ConfigDigest string            `json:"config_digest"`
}

type ResponseCache struct {
	client      *redis.Client
	maxBody     int
	maxTTL      time.Duration
	writeQ      chan writeJob
	writeWg     sync.WaitGroup
	closed      bool
	closeMu     sync.Mutex
	dropped     int64
	enqueueFail int64
}

type writeJob struct {
	key string
	val []byte
	ttl time.Duration
}

func NewResponseCache(url string, maxBody int) (*ResponseCache, error) {
	if url == "" {
		return nil, errors.New("redis url required for cache")
	}
	c, err := redis.ParseURL(url)
	if err != nil {
		return nil, err
	}
	if maxBody <= 0 {
		maxBody = 256 * 1024
	}
	rc := &ResponseCache{
		client:  c,
		maxBody: maxBody,
		maxTTL:  defaultMaxTTL,
		writeQ:  make(chan writeJob, 512),
	}
	rc.startWriter()
	return rc, nil
}

func (c *ResponseCache) startWriter() {
	c.writeWg.Add(1)
	go func() {
		defer c.writeWg.Done()
		for job := range c.writeQ {
			c.writeOne(job)
		}
	}()
}

func (c *ResponseCache) writeOne(job writeJob) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_, _ = c.client.Do(ctx, "SET", job.key, string(job.val), "EX", clampTTL(job.ttl, c.maxTTL))
}

func clampTTL(ttl, max time.Duration) int {
	if ttl <= 0 {
		ttl = 60 * time.Second
	}
	if ttl > max {
		ttl = max
	}
	sec := int(ttl.Seconds())
	if sec < 1 {
		sec = 1
	}
	return sec
}

func (c *ResponseCache) DroppedWrites() int64 {
	return atomic.LoadInt64(&c.dropped)
}

func (c *ResponseCache) EnqueueFailures() int64 {
	return atomic.LoadInt64(&c.enqueueFail)
}

// Flush drains pending async writes synchronously (for shutdown/tests).
func (c *ResponseCache) Flush(ctx context.Context) error {
	if c == nil {
		return nil
	}
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		select {
		case job, ok := <-c.writeQ:
			if !ok {
				return nil
			}
			c.writeOne(job)
		default:
			return nil
		}
	}
}

func (c *ResponseCache) Close() {
	c.closeMu.Lock()
	defer c.closeMu.Unlock()
	if c.closed {
		return
	}
	_ = c.Flush(context.Background())
	c.closed = true
	close(c.writeQ)
	c.writeWg.Wait()
}

func (c *ResponseCache) Get(ctx context.Context, key string) (*CachedResponse, error) {
	if c == nil || c.client == nil {
		return nil, ErrMiss
	}
	res, err := c.client.Do(ctx, "GET", key)
	if err != nil {
		if errors.Is(err, redis.ErrNil) {
			return nil, ErrMiss
		}
		return nil, err
	}
	s, ok := res.(string)
	if !ok || s == "" {
		return nil, ErrMiss
	}
	if len(s) > c.maxBody {
		return nil, ErrMiss
	}
	var entry CachedResponse
	if err := json.Unmarshal([]byte(s), &entry); err != nil {
		return nil, ErrMiss
	}
	if len(entry.Body) > c.maxBody {
		return nil, ErrMiss
	}
	return &entry, nil
}

func (c *ResponseCache) PutAsync(key string, entry CachedResponse, ttl time.Duration) error {
	if c == nil || c.client == nil {
		return errors.New("cache unavailable")
	}
	c.closeMu.Lock()
	closed := c.closed
	c.closeMu.Unlock()
	if closed {
		atomic.AddInt64(&c.dropped, 1)
		return ErrCacheClosed
	}
	if len(entry.Body) > c.maxBody {
		atomic.AddInt64(&c.enqueueFail, 1)
		return errors.New("body too large for cache")
	}
	b, err := json.Marshal(entry)
	if err != nil {
		atomic.AddInt64(&c.enqueueFail, 1)
		return err
	}
	if len(b) > c.maxBody {
		atomic.AddInt64(&c.enqueueFail, 1)
		return errors.New("entry too large for cache")
	}
	select {
	case c.writeQ <- writeJob{key: key, val: b, ttl: ttl}:
		return nil
	default:
		atomic.AddInt64(&c.dropped, 1)
		return errors.New("cache write queue full")
	}
}

func (c *ResponseCache) Set(ctx context.Context, key string, entry CachedResponse, ttl time.Duration) error {
	if len(entry.Body) > c.maxBody {
		return errors.New("body too large for cache")
	}
	b, err := json.Marshal(entry)
	if err != nil {
		return err
	}
	_, err = c.client.Do(ctx, "SET", key, string(b), "EX", clampTTL(ttl, c.maxTTL))
	return err
}
