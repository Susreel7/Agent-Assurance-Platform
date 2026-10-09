package limiter

import (
	"context"
	"sync"
	"sync/atomic"
	"time"
)

type memoryLimiter struct {
	mu      sync.Mutex
	windows map[string]*window
	busy    map[string]int64
	latency map[string]*ewma
	spend   map[string]*daySpend
	active  int64
}

type window struct {
	minuteStart time.Time
	requests    int
	tokens      int64
}

type daySpend struct {
	dayUTC string
	micros int64
}

type ewma struct {
	value float64
	n     int
}

func NewMemoryLimiter() LocalLimiter {
	return &memoryLimiter{
		windows: map[string]*window{},
		busy:    map[string]int64{},
		latency: map[string]*ewma{},
		spend:   map[string]*daySpend{},
	}
}

func utcDay(now time.Time) string {
	return now.UTC().Format("20060102")
}

func (m *memoryLimiter) TryAcquire(_ context.Context, deploymentID string, dim LimitDimensions, tokens int64, costMicros int64) (Reservation, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	now := time.Now().UTC()
	w := m.windows[deploymentID]
	if w == nil || now.Sub(w.minuteStart) >= time.Minute {
		w = &window{minuteStart: now.Truncate(time.Minute)}
		m.windows[deploymentID] = w
	}
	if dim.RPM != nil && w.requests >= *dim.RPM {
		return Reservation{}, ErrRateExceeded
	}
	if dim.TPM != nil && w.tokens+tokens > int64(*dim.TPM) {
		return Reservation{}, ErrRateExceeded
	}
	if dim.MaxConcurrency != nil && m.busy[deploymentID] >= int64(*dim.MaxConcurrency) {
		return Reservation{}, ErrConcurrencyExceeded
	}
	day := utcDay(now)
	ds := m.spend[deploymentID]
	if ds == nil || ds.dayUTC != day {
		ds = &daySpend{dayUTC: day}
		m.spend[deploymentID] = ds
	}
	if dim.DailyBudgetMicros != nil && costMicros > 0 {
		if ds.micros+costMicros > *dim.DailyBudgetMicros {
			return Reservation{}, ErrBudgetExceeded
		}
	}
	w.requests++
	w.tokens += tokens
	m.busy[deploymentID]++
	if costMicros > 0 {
		ds.micros += costMicros
	}
	atomic.AddInt64(&m.active, 1)
	return Reservation{DeploymentID: deploymentID, Tokens: tokens, CostMicrosHeld: costMicros}, nil
}

func (m *memoryLimiter) Release(res Reservation) {
	if res.Released || res.Reconciled {
		return
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.releaseLocked(res.DeploymentID, res.Tokens, res.CostMicrosHeld)
	res.Released = true
	atomic.AddInt64(&m.active, -1)
}

func (m *memoryLimiter) Reconcile(res Reservation, actualTokens, actualCostMicros int64) {
	if res.Released || res.Reconciled {
		return
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	tokenAdj := actualTokens - res.Tokens
	costAdj := actualCostMicros - res.CostMicrosHeld
	if w := m.windows[res.DeploymentID]; w != nil && tokenAdj != 0 {
		w.tokens += tokenAdj
		if w.tokens < 0 {
			w.tokens = 0
		}
	}
	if costAdj != 0 {
		day := utcDay(time.Now().UTC())
		ds := m.spend[res.DeploymentID]
		if ds != nil && ds.dayUTC == day {
			ds.micros += costAdj
			if ds.micros < 0 {
				ds.micros = 0
			}
		}
	}
	if m.busy[res.DeploymentID] > 0 {
		m.busy[res.DeploymentID]--
	}
	res.Reconciled = true
	atomic.AddInt64(&m.active, -1)
}

func (m *memoryLimiter) InFlight() int64 {
	return atomic.LoadInt64(&m.active)
}

func (m *memoryLimiter) releaseLocked(deploymentID string, tokens, costMicros int64) {
	if m.busy[deploymentID] > 0 {
		m.busy[deploymentID]--
	}
	if w := m.windows[deploymentID]; w != nil {
		if w.requests > 0 {
			w.requests--
		}
		if tokens > 0 && w.tokens >= tokens {
			w.tokens -= tokens
		}
	}
	if costMicros > 0 {
		day := utcDay(time.Now().UTC())
		if ds := m.spend[deploymentID]; ds != nil && ds.dayUTC == day && ds.micros >= costMicros {
			ds.micros -= costMicros
		}
	}
}

func (m *memoryLimiter) RecordLatency(deploymentID string, d time.Duration) {
	m.mu.Lock()
	defer m.mu.Unlock()
	e := m.latency[deploymentID]
	if e == nil {
		e = &ewma{}
		m.latency[deploymentID] = e
	}
	ms := float64(d.Milliseconds())
	if e.n == 0 {
		e.value = ms
	} else {
		e.value = 0.2*ms + 0.8*e.value
	}
	e.n++
}

func (m *memoryLimiter) BusyCount(deploymentID string) int64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.busy[deploymentID]
}

func (m *memoryLimiter) LatencyEWMA(deploymentID string) float64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	if e := m.latency[deploymentID]; e != nil {
		return e.value
	}
	return 0
}
