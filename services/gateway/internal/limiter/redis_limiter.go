package limiter

import (
	"context"
	"errors"
	"fmt"
	"time"

	"agent-assurance/services/gateway/internal/redis"
	"agent-assurance/services/gateway/internal/snapshot"
)

var (
	ErrRedisNotConfigured = errors.New("redis_limiter_not_configured")
	ErrLimitDenied        = errors.New("rate_limit_exceeded")
)

type RedisLimiter struct {
	client *redis.Client
}

func NewRedisLimiterFromURL(url string) (*RedisLimiter, error) {
	if url == "" {
		return nil, ErrRedisNotConfigured
	}
	c, err := redis.ParseURL(url)
	if err != nil {
		return nil, err
	}
	return &RedisLimiter{client: c}, nil
}

func NewRedisLimiter(addr string) *RedisLimiter {
	if addr == "" {
		return &RedisLimiter{}
	}
	c, err := redis.ParseURL(addr)
	if err != nil {
		return &RedisLimiter{}
	}
	return &RedisLimiter{client: c}
}

func (r *RedisLimiter) Ready(ctx context.Context) error {
	if r.client == nil {
		return ErrRedisNotConfigured
	}
	return r.client.Ping(ctx)
}

func (r *RedisLimiter) Acquire(ctx context.Context, req AcquireRequest, orgLim, credLim, depLim LimitDimensions) (ReservationToken, error) {
	if r.client == nil {
		return ReservationToken{}, ErrRedisNotConfigured
	}
	minute := time.Now().UTC().Format("200601021504")
	day := time.Now().UTC().Format("20060102")
	keys := append(tierKeys(OrgPrefix(req.OrgID), minute, day),
		tierKeys(CredPrefix(req.OrgID, req.CredentialGen), minute, day)...)
	keys = append(keys, tierKeys(DepPrefix(req.OrgID, req.CredentialGen, req.DeploymentID), minute, day)...)
	res, err := r.client.Eval(ctx, acquireScript, keys,
		ptrInt(orgLim.MaxConcurrency), ptrInt(orgLim.RPM), ptrInt(orgLim.TPM), ptrInt64(orgLim.DailyBudgetMicros),
		ptrInt(credLim.MaxConcurrency), ptrInt(credLim.RPM), ptrInt(credLim.TPM), ptrInt64(credLim.DailyBudgetMicros),
		ptrInt(depLim.MaxConcurrency), ptrInt(depLim.RPM), ptrInt(depLim.TPM), ptrInt64(depLim.DailyBudgetMicros),
		req.TokensEstimate, req.CostMicrosEst, 90, 86400)
	if err != nil {
		return ReservationToken{}, err
	}
	code, _ := res.(int64)
	if code != 1 {
		return ReservationToken{}, ErrLimitDenied
	}
	return ReservationToken{
		OrgID: req.OrgID, CredentialGen: req.CredentialGen, DeploymentID: req.DeploymentID,
		TokensHeld: req.TokensEstimate, CostMicrosHeld: req.CostMicrosEst,
	}, nil
}

func (r *RedisLimiter) Reconcile(ctx context.Context, tok ReservationToken, actualTokens, actualCostMicros int64) error {
	if r.client == nil {
		return nil
	}
	minute := time.Now().UTC().Format("200601021504")
	day := time.Now().UTC().Format("20060102")
	keys := append(tierKeys(OrgPrefix(tok.OrgID), minute, day),
		tierKeys(CredPrefix(tok.OrgID, tok.CredentialGen), minute, day)...)
	keys = append(keys, tierKeys(DepPrefix(tok.OrgID, tok.CredentialGen, tok.DeploymentID), minute, day)...)
	tokenAdj := actualTokens - tok.TokensHeld
	costAdj := actualCostMicros - tok.CostMicrosHeld
	_, err := r.client.Eval(ctx, releaseScript, keys, tokenAdj, costAdj)
	return err
}

func (r *RedisLimiter) TryAcquire(ctx context.Context, key string, rpm, tpm *int, tokens int64) (Reservation, error) {
	tok, err := r.Acquire(ctx, AcquireRequest{
		OrgID: "legacy", CredentialGen: "legacy", DeploymentID: key,
		TokensEstimate: tokens,
	}, LimitDimensions{}, LimitDimensions{RPM: rpm, TPM: tpm}, LimitDimensions{RPM: rpm, TPM: tpm})
	if err != nil {
		return Reservation{}, err
	}
	return Reservation{DeploymentID: tok.DeploymentID, OrgID: tok.OrgID, Tokens: tok.TokensHeld}, nil
}

func (r *RedisLimiter) Release(ctx context.Context, res Reservation) error {
	if res.Released {
		return nil
	}
	res.Released = true
	return r.Reconcile(ctx, ReservationToken{
		OrgID: res.OrgID, CredentialGen: "legacy", DeploymentID: res.DeploymentID, TokensHeld: res.Tokens,
	}, res.Tokens, 0)
}

func BuildAcquireRequest(snap *snapshot.ActivatedSnapshot, bind snapshot.WorkloadBinding, dep snapshot.Deployment, principalOrg, credGen string, tokensIn, tokensOut int64) AcquireRequest {
	effective := EffectiveDimensions(snap.Config.OrganizationLimits, bind, dep)
	cost := EstimateCostMicros(dep, tokensIn, tokensOut)
	return AcquireRequest{
		OrgID: principalOrg, CredentialGen: credGen, DeploymentID: dep.ID,
		Dimensions: effective, TokensEstimate: tokensIn + tokensOut, CostMicrosEst: cost,
	}
}

func ptrInt(p *int) int {
	if p == nil {
		return 0
	}
	return *p
}

func ptrInt64(p *int64) int64 {
	if p == nil {
		return 0
	}
	return *p
}

func FormatLimitError(err error) string {
	if errors.Is(err, ErrLimitDenied) {
		return "rate_limit_exceeded"
	}
	return fmt.Sprint(err)
}
