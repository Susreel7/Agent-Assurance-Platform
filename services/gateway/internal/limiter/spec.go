package limiter

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
)

// LimitDimensions are the effective strictest limits across org, credential, deployment.
type LimitDimensions struct {
	RPM               *int
	TPM               *int
	MaxConcurrency    *int
	DailyBudgetMicros *int64
}

type AcquireRequest struct {
	OrgID          string
	CredentialGen  string
	DeploymentID   string
	Dimensions     LimitDimensions
	TokensEstimate int64
	CostMicrosEst  int64
}

// ReservationToken identifies a held slot for release/reconcile.
type ReservationToken struct {
	OrgID          string
	CredentialGen  string
	DeploymentID   string
	TokensHeld     int64
	CostMicrosHeld int64
	Released       bool
}

func HashKey(parts ...string) string {
	h := sha256.New()
	for i, p := range parts {
		if i > 0 {
			_, _ = h.Write([]byte{0})
		}
		_, _ = h.Write([]byte(p))
	}
	return hex.EncodeToString(h.Sum(nil))[:32]
}

func MergeStrictest(a, b LimitDimensions) LimitDimensions {
	out := a
	if b.RPM != nil && (out.RPM == nil || *b.RPM < *out.RPM) {
		v := *b.RPM
		out.RPM = &v
	}
	if b.TPM != nil && (out.TPM == nil || *b.TPM < *out.TPM) {
		v := *b.TPM
		out.TPM = &v
	}
	if b.MaxConcurrency != nil && (out.MaxConcurrency == nil || *b.MaxConcurrency < *out.MaxConcurrency) {
		v := *b.MaxConcurrency
		out.MaxConcurrency = &v
	}
	if b.DailyBudgetMicros != nil && (out.DailyBudgetMicros == nil || *b.DailyBudgetMicros < *out.DailyBudgetMicros) {
		v := *b.DailyBudgetMicros
		out.DailyBudgetMicros = &v
	}
	return out
}

func KeyPrefix(org, cred, dep string) string {
	return fmt.Sprintf("gw:%s:%s:%s", HashKey(org), HashKey(cred), HashKey(dep))
}
