package limiter

import (
	"context"
	"errors"
	"time"
)

var ErrBudgetExceeded = errors.New("budget_exceeded")
var ErrConcurrencyExceeded = errors.New("concurrency_exceeded")
var ErrRateExceeded = errors.New("rate_limit_exceeded")

// InFlightLimiter exposes reservation leak invariant for tests.
type InFlightLimiter interface {
	LocalLimiter
	InFlight() int64
}

// Reservation tracks in-flight limit consumption for reconciliation.
type Reservation struct {
	DeploymentID   string
	OrgID          string
	Tokens         int64
	CostMicrosHeld int64
	Released       bool
	Reconciled     bool
}

// GlobalLimiter coordinates cross-instance limits (Redis implementation boundary).
type GlobalLimiter interface {
	Ready(ctx context.Context) error
	TryAcquire(ctx context.Context, key string, rpm, tpm *int, tokens int64) (Reservation, error)
	Release(ctx context.Context, res Reservation) error
}

// LocalLimiter handles per-process RPM/TPM/concurrency/budget when no Redis is configured.
type LocalLimiter interface {
	TryAcquire(ctx context.Context, deploymentID string, dim LimitDimensions, tokens int64, costMicros int64) (Reservation, error)
	Release(res Reservation)
	Reconcile(res Reservation, actualTokens, actualCostMicros int64)
	RecordLatency(deploymentID string, d time.Duration)
	BusyCount(deploymentID string) int64
	LatencyEWMA(deploymentID string) float64
}
