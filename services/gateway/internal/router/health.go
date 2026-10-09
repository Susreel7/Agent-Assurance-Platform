package router

import (
	"math"
	"sync"
	"time"

	"agent-assurance/services/gateway/internal/snapshot"
)

type HealthRegistry struct {
	mu    sync.RWMutex
	state map[string]*healthState
}

type healthState struct {
	failures      int
	cooldownUntil time.Time
	cooldownMS    int
	ewmaMS        float64
	halfOpen      bool
}

func NewHealthRegistry() *HealthRegistry {
	return &HealthRegistry{state: map[string]*healthState{}}
}

func (h *HealthRegistry) RecordSuccess(depID string, upstream time.Duration) {
	h.mu.Lock()
	defer h.mu.Unlock()
	st := h.get(depID)
	st.failures = 0
	st.halfOpen = false
	ms := float64(upstream.Milliseconds())
	if st.ewmaMS == 0 {
		st.ewmaMS = ms
	} else {
		st.ewmaMS = 0.2*ms + 0.8*st.ewmaMS
	}
}

func (h *HealthRegistry) RecordFailure(depID string, pol snapshot.CooldownPolicy) {
	h.mu.Lock()
	defer h.mu.Unlock()
	st := h.get(depID)
	st.failures++
	thr := pol.FailureThreshold
	if thr <= 0 {
		thr = 3
	}
	if st.failures >= thr {
		if st.cooldownMS == 0 {
			st.cooldownMS = pol.InitialCooldownMS
		}
		if st.cooldownMS <= 0 {
			st.cooldownMS = 500
		}
		max := pol.MaxCooldownMS
		if max <= 0 {
			max = 60000
		}
		st.cooldownMS = int(math.Min(float64(st.cooldownMS*2), float64(max)))
		st.cooldownUntil = time.Now().UTC().Add(time.Duration(st.cooldownMS) * time.Millisecond)
		st.halfOpen = false
	}
}

func (h *HealthRegistry) Available(dep snapshot.Deployment, now time.Time) bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	st, ok := h.state[dep.ID]
	if !ok {
		return true
	}
	if now.Before(st.cooldownUntil) {
		return false
	}
	if st.failures >= dep.Cooldown.FailureThreshold && dep.Cooldown.FailureThreshold > 0 {
		if st.halfOpen {
			return false
		}
		st.halfOpen = true
		return true
	}
	return true
}

func (h *HealthRegistry) EWMA(depID string) float64 {
	h.mu.RLock()
	defer h.mu.RUnlock()
	if st, ok := h.state[depID]; ok {
		return st.ewmaMS
	}
	return 0
}

func (h *HealthRegistry) get(depID string) *healthState {
	st, ok := h.state[depID]
	if !ok {
		st = &healthState{}
		h.state[depID] = st
	}
	return st
}
