package handler

import (
	"context"
	"errors"

	"agent-assurance/services/gateway/internal/auth"
	"agent-assurance/services/gateway/internal/limiter"
	"agent-assurance/services/gateway/internal/normalize"
	"agent-assurance/services/gateway/internal/snapshot"
)

type limitHold struct {
	local        limiter.Reservation
	globalTok    limiter.ReservationToken
	globalLegacy limiter.Reservation
	globalHeld   bool
	legacyGlobal bool
	estIn        int64
	estOut       int64
}

func (s *Server) acquireAll(ctx context.Context, snap *snapshot.ActivatedSnapshot, bind snapshot.WorkloadBinding, principal auth.Principal, dep snapshot.Deployment, body []byte) (limitHold, error) {
	tIn, tOut := estimateTokensInOut(body)
	effective := limiter.EffectiveDimensions(snap.Config.OrganizationLimits, bind, dep)
	costEst := limiter.EstimateCostMicros(dep, tIn, tOut)
	orgLim, credLim, depLim := limiter.TierLimits(snap, bind, dep)
	var hold limitHold
	hold.estIn, hold.estOut = tIn, tOut
	if s.Settings.RequireGlobalLimiter && !s.Settings.DevAllowInsecureLimiter {
		if rl, ok := s.GlobalLimit.(limiter.ReconcilingLimiter); ok {
			req := limiter.BuildAcquireRequest(snap, bind, dep, principal.OrganizationID, principal.GenerationID, tIn, tOut)
			tok, err := rl.Acquire(ctx, req, orgLim, credLim, depLim)
			if err != nil {
				return hold, err
			}
			hold.globalTok = tok
			hold.globalHeld = true
		} else {
			gr, err := s.GlobalLimit.TryAcquire(ctx, dep.ID, effective.RPM, effective.TPM, tIn+tOut)
			if err != nil {
				return hold, err
			}
			hold.globalHeld = true
			hold.legacyGlobal = true
			hold.globalLegacy = gr
		}
	}
	res, err := s.LocalLimit.TryAcquire(ctx, dep.ID, effective, tIn+tOut, costEst)
	if err != nil {
		s.releaseAll(ctx, hold, dep.ID, principal.OrganizationID, tIn+tOut, costEst)
		return limitHold{}, err
	}
	hold.local = res
	return hold, nil
}

func (s *Server) releaseAll(ctx context.Context, hold limitHold, depID, orgID string, tokens, cost int64) {
	if !hold.local.Released && !hold.local.Reconciled {
		s.LocalLimit.Release(hold.local)
	}
	if !hold.globalHeld {
		return
	}
	if rl, ok := s.GlobalLimit.(limiter.ReconcilingLimiter); ok && hold.globalTok.DeploymentID != "" {
		_ = rl.Reconcile(ctx, hold.globalTok, tokens, cost)
		return
	}
	if hold.legacyGlobal {
		_ = s.GlobalLimit.Release(ctx, hold.globalLegacy)
		return
	}
	_ = s.GlobalLimit.Release(ctx, limiter.Reservation{DeploymentID: depID, OrgID: orgID, Tokens: tokens})
}

func (s *Server) finishSuccess(ctx context.Context, hold limitHold, dep snapshot.Deployment, principal auth.Principal, usage normalize.TokenUsage) {
	tIn, tOut := usage.PromptTokens, usage.CompletionTokens
	if usage.EstimateOnly {
		tIn, tOut = hold.estIn, hold.estOut
	}
	tokens := tIn + tOut + usage.CachedPrompt + usage.ReasoningTokens
	cost := limiter.EstimateCostMicros(dep, tIn+usage.CachedPrompt, tOut+usage.ReasoningTokens)
	if rl, ok := s.GlobalLimit.(limiter.ReconcilingLimiter); ok && hold.globalTok.DeploymentID != "" {
		_ = rl.Reconcile(ctx, hold.globalTok, tokens, cost)
	} else if hold.legacyGlobal {
		_ = s.GlobalLimit.Release(ctx, hold.globalLegacy)
	} else if hold.globalHeld {
		_ = s.GlobalLimit.Release(ctx, limiter.Reservation{DeploymentID: dep.ID, OrgID: principal.OrganizationID, Tokens: tokens})
	}
	if !hold.local.Released && !hold.local.Reconciled {
		s.LocalLimit.Reconcile(hold.local, tokens, cost)
	}
}

func limitDenied(err error) bool {
	return errors.Is(err, limiter.ErrLimitDenied) || errors.Is(err, limiter.ErrRateExceeded) ||
		errors.Is(err, limiter.ErrConcurrencyExceeded) || errors.Is(err, limiter.ErrBudgetExceeded)
}

func routeAttemptBudget(route snapshot.Route, deploySlots int) int {
	n := deploySlots * 4
	if route.MaxAttempts > 0 {
		n = route.MaxAttempts * 6
	}
	if n < 4 {
		n = 4
	}
	if n > 32 {
		n = 32
	}
	return n
}
