package limiter_test

import (
	"testing"

	"agent-assurance/services/gateway/internal/limiter"
	"agent-assurance/services/gateway/internal/snapshot"
)

func TestMergeStrictest(t *testing.T) {
	rpm5, rpm10, rpm3 := 5, 10, 3
	a := limiter.LimitDimensions{RPM: &rpm10}
	b := limiter.LimitDimensions{RPM: &rpm5}
	c := limiter.MergeStrictest(a, b)
	if *c.RPM != 5 {
		t.Fatalf("rpm=%d", *c.RPM)
	}
	d := limiter.MergeStrictest(c, limiter.LimitDimensions{RPM: &rpm3})
	if *d.RPM != 3 {
		t.Fatalf("rpm=%d", *d.RPM)
	}
}

func TestEffectiveDimensions(t *testing.T) {
	rpm100, rpm50 := 100, 50
	org := snapshot.RateLimits{RPM: &rpm100}
	bind := snapshot.WorkloadBinding{RPM: &rpm50}
	dep := snapshot.Deployment{}
	eff := limiter.EffectiveDimensions(org, bind, dep)
	if *eff.RPM != 50 {
		t.Fatalf("rpm=%d", *eff.RPM)
	}
}
