package limiter

import (
	"agent-assurance/services/gateway/internal/snapshot"
)

func TierLimits(snap *snapshot.ActivatedSnapshot, bind snapshot.WorkloadBinding, dep snapshot.Deployment) (org, cred, depLim LimitDimensions) {
	return snapshotToLimits(snap.Config.OrganizationLimits), bindingToLimits(bind), deploymentToLimits(dep)
}

func EffectiveDimensions(org snapshot.RateLimits, bind snapshot.WorkloadBinding, dep snapshot.Deployment) LimitDimensions {
	var d LimitDimensions
	d = MergeStrictest(d, snapshotToLimits(org))
	d = MergeStrictest(d, bindingToLimits(bind))
	d = MergeStrictest(d, deploymentToLimits(dep))
	return d
}

func snapshotToLimits(r snapshot.RateLimits) LimitDimensions {
	return LimitDimensions{RPM: r.RPM, TPM: r.TPM, MaxConcurrency: r.MaxConcurrency, DailyBudgetMicros: r.DailyBudgetMicros}
}

func bindingToLimits(b snapshot.WorkloadBinding) LimitDimensions {
	return LimitDimensions{RPM: b.RPM, TPM: b.TPM, MaxConcurrency: b.MaxConcurrency, DailyBudgetMicros: b.DailyBudgetMicros}
}

func deploymentToLimits(d snapshot.Deployment) LimitDimensions {
	return LimitDimensions{RPM: d.RPM, TPM: d.TPM, MaxConcurrency: d.MaxConcurrency, DailyBudgetMicros: d.DailyBudgetMicros}
}

func EstimateCostMicros(dep snapshot.Deployment, tokensIn, tokensOut int64) int64 {
	in := dep.InputPriceMicrosPerM
	out := dep.OutputPriceMicrosPerM
	if in == 0 && out == 0 {
		return 0
	}
	return (tokensIn*in + tokensOut*out) / 1_000_000
}
