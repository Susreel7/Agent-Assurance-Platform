package limiter

import "context"

// ReconcilingLimiter extends global limits with dimensional acquire/reconcile.
type ReconcilingLimiter interface {
	GlobalLimiter
	Acquire(ctx context.Context, req AcquireRequest, orgLim, credLim, depLim LimitDimensions) (ReservationToken, error)
	Reconcile(ctx context.Context, tok ReservationToken, actualTokens, actualCostMicros int64) error
}
