package provider

import (
	"bytes"
	"context"
	"errors"
	"io"
)

var ErrAttemptBudgetExhausted = errors.New("attempt_budget_exhausted")

func InvokeWithRetry(ctx context.Context, adapter Adapter, req InvokeRequest, maxRetries int) (*InvokeResult, error) {
	res, _, err := InvokeWithRetryBudget(ctx, adapter, req, maxRetries, 0)
	return res, err
}

// InvokeWithRetryBudget retries transport/429/5xx up to maxRetries per deployment but never exceeds maxTotalAttempts when > 0.
func InvokeWithRetryBudget(ctx context.Context, adapter Adapter, req InvokeRequest, maxRetries int, maxTotalAttempts int) (*InvokeResult, int, error) {
	if maxRetries < 0 {
		maxRetries = 0
	}
	var last *InvokeResult
	attempts := 0
	for attempt := 0; attempt <= maxRetries; attempt++ {
		attempts++
		if maxTotalAttempts > 0 && attempts > maxTotalAttempts {
			if last != nil {
				return last, attempts - 1, ErrAttemptBudgetExhausted
			}
			return nil, attempts - 1, ErrAttemptBudgetExhausted
		}
		res, err := adapter.Invoke(ctx, req)
		if err != nil {
			if TransportRetryable(err) && attempt < maxRetries {
				_ = Sleep(ctx, RetryAfterDelay(nil, attempt+1))
				continue
			}
			return nil, attempts, err
		}
		if res.StatusCode >= 200 && res.StatusCode < 300 {
			return res, attempts, nil
		}
		body, _ := io.ReadAll(io.LimitReader(res.Body, 1<<20))
		_ = res.Body.Close()
		res.Body = io.NopCloser(bytes.NewReader(body))
		if NonRetryableHTTPStatus(res.StatusCode) {
			return res, attempts, nil
		}
		if RetryableHTTPStatus(res.StatusCode) && attempt < maxRetries {
			last = res
			_ = Sleep(ctx, RetryAfterDelay(res.Headers, attempt+1))
			continue
		}
		return res, attempts, nil
	}
	if last != nil {
		return last, attempts, nil
	}
	return nil, attempts, context.DeadlineExceeded
}
