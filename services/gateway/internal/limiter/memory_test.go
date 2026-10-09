package limiter_test

import (
	"context"
	"testing"
	"time"

	"agent-assurance/services/gateway/internal/limiter"
)

func TestMemoryConcurrencyAndBudgetUTC(t *testing.T) {
	m := limiter.NewMemoryLimiter().(limiter.InFlightLimiter)
	ctx := context.Background()
	maxC := 1
	budget := int64(1000)
	dim := limiter.LimitDimensions{MaxConcurrency: &maxC, DailyBudgetMicros: &budget}
	r1, err := m.TryAcquire(ctx, "d", dim, 10, 400)
	if err != nil {
		t.Fatal(err)
	}
	_, err = m.TryAcquire(ctx, "d", dim, 10, 400)
	if err != limiter.ErrConcurrencyExceeded {
		t.Fatalf("err=%v", err)
	}
	m.Release(r1)
	r2, err := m.TryAcquire(ctx, "d", dim, 10, 700)
	if err != nil {
		t.Fatalf("err=%v", err)
	}
	m.Reconcile(r2, 10, 700)
	_, err = m.TryAcquire(ctx, "d", dim, 10, 400)
	if err != limiter.ErrBudgetExceeded {
		t.Fatalf("err=%v", err)
	}
	if m.InFlight() != 0 {
		t.Fatalf("leak=%d", m.InFlight())
	}
}

func TestMemoryReconcileAdjustsSpend(t *testing.T) {
	m := limiter.NewMemoryLimiter().(limiter.InFlightLimiter)
	ctx := context.Background()
	budget := int64(10000)
	dim := limiter.LimitDimensions{DailyBudgetMicros: &budget}
	r, _ := m.TryAcquire(ctx, "d", dim, 100, 500)
	m.Reconcile(r, 100, 800)
	if m.InFlight() != 0 {
		t.Fatal("leak")
	}
	_, err := m.TryAcquire(ctx, "d", dim, 1, 9500)
	if err != limiter.ErrBudgetExceeded {
		t.Fatalf("expected budget err got %v", err)
	}
	_ = time.Now()
}

func TestReservationLeakInvariant(t *testing.T) {
	m := limiter.NewMemoryLimiter().(limiter.InFlightLimiter)
	ctx := context.Background()
	r, _ := m.TryAcquire(ctx, "x", limiter.LimitDimensions{}, 1, 0)
	if m.InFlight() != 1 {
		t.Fatal()
	}
	m.Release(r)
	if m.InFlight() != 0 {
		t.Fatal("leak after release")
	}
}
