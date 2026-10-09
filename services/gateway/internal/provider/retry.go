package provider

import (
	"context"
	"errors"
	"math/rand"
	"net"
	"net/http"
	"strconv"
	"time"
)

var ErrNonRetryable = errors.New("non_retryable_upstream")

func RetryableHTTPStatus(code int) bool {
	switch code {
	case http.StatusRequestTimeout, 409, 425, http.StatusTooManyRequests:
		return true
	default:
		return code >= 500
	}
}

func NonRetryableHTTPStatus(code int) bool {
	switch code {
	case http.StatusBadRequest, http.StatusUnauthorized, http.StatusForbidden,
		http.StatusNotFound, http.StatusUnprocessableEntity:
		return true
	default:
		return false
	}
}

func TransportRetryable(err error) bool {
	if err == nil {
		return false
	}
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return true
	}
	return errors.Is(err, context.DeadlineExceeded)
}

func RetryAfterDelay(h http.Header, attempt int) time.Duration {
	if ra := h.Get("Retry-After"); ra != "" {
		if sec, err := strconv.Atoi(ra); err == nil && sec > 0 {
			return time.Duration(sec) * time.Second
		}
	}
	base := time.Duration(attempt*attempt) * 100 * time.Millisecond
	jitter := time.Duration(rand.Intn(100)) * time.Millisecond
	return base + jitter
}

func Sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}
