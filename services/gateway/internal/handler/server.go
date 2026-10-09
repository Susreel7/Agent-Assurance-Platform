package handler

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"

	"agent-assurance/services/gateway/internal/audit"
	"agent-assurance/services/gateway/internal/auth"
	"agent-assurance/services/gateway/internal/cache"
	"agent-assurance/services/gateway/internal/config"
	"agent-assurance/services/gateway/internal/credentials"
	"agent-assurance/services/gateway/internal/dataprotection"
	"agent-assurance/services/gateway/internal/limiter"
	"agent-assurance/services/gateway/internal/openai"
	"agent-assurance/services/gateway/internal/provider"
	"agent-assurance/services/gateway/internal/router"
	"agent-assurance/services/gateway/internal/snapshot"
	"agent-assurance/services/gateway/internal/telemetry"
)

type Server struct {
	Settings      config.Settings
	Snapshots     *snapshot.Store
	Credentials   *credentials.Resolver
	LocalLimit    limiter.LocalLimiter
	GlobalLimit   limiter.GlobalLimiter
	Selector      *router.Selector
	Audit         *audit.Queue
	ResponseCache *cache.ResponseCache
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /readyz", s.readyz)
	mux.HandleFunc("GET /version", s.version)
	mux.HandleFunc("GET /v1/models", s.models)
	mux.HandleFunc("POST /v1/chat/completions", s.chatCompletions)
	mux.HandleFunc("POST /v1/responses", s.responses)
	mux.HandleFunc("POST /v1/embeddings", s.embeddings)
	return s.withBounds(mux)
}

func (s *Server) withBounds(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, s.Settings.MaxRequestBodyBytes)
		next.ServeHTTP(w, r)
	})
}

func (s *Server) healthz(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ok"))
}

func (s *Server) readyz(w http.ResponseWriter, _ *http.Request) {
	type dep struct {
		Name   string `json:"name"`
		Status string `json:"status"`
		Detail string `json:"detail,omitempty"`
	}
	deps := []dep{{Name: "snapshot", Status: "ok"}}
	status := "ok"
	if snap := s.Snapshots.Current(); snap == nil {
		deps[0] = dep{Name: "snapshot", Status: "not_ready", Detail: s.Snapshots.LastError()}
		status = "not_ready"
	}
	if s.Settings.RequireGlobalLimiter && !s.Settings.DevAllowInsecureLimiter {
		ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
		defer cancel()
		if err := s.GlobalLimit.Ready(ctx); err != nil {
			deps = append(deps, dep{Name: "global_limiter", Status: "not_ready", Detail: err.Error()})
			status = "not_ready"
		}
	}
	w.Header().Set("Content-Type", "application/json")
	if status != "ok" {
		w.WriteHeader(http.StatusServiceUnavailable)
	} else {
		w.WriteHeader(http.StatusOK)
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"status": status, "dependencies": deps})
}

func (s *Server) version(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"service": "gateway", "build_revision": s.Settings.BuildRevision,
		"router_schema": 1, "openapi_compatible": "v1",
	})
}

func (s *Server) models(w http.ResponseWriter, r *http.Request) {
	principal, ok := s.authenticate(w, r, "router:models")
	if !ok {
		return
	}
	snap := s.Snapshots.Current()
	if snap == nil {
		openai.WriteError(w, http.StatusServiceUnavailable, openai.TypeServer, "snapshot not loaded", "snapshot_unavailable")
		return
	}
	agentID := r.Header.Get("X-AAP-Agent-Id")
	env := r.Header.Get("X-AAP-Environment")
	if env == "" {
		env = principal.Environment
	}
	type model struct {
		ID, Object, OwnedBy string
	}
	var data []model
	seen := map[string]struct{}{}
	for _, route := range snap.Config.Routes {
		if agentID != "" && route.AgentID != agentID {
			continue
		}
		if env != "" && route.Environment != env {
			continue
		}
		if _, ok := seen[route.Alias]; ok {
			continue
		}
		seen[route.Alias] = struct{}{}
		data = append(data, model{ID: route.Alias, Object: "model", OwnedBy: principal.OrganizationID})
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"object": "list", "data": data})
}

type dispatchOpts struct {
	operation provider.Operation
	scope     string
}

func (s *Server) chatCompletions(w http.ResponseWriter, r *http.Request) {
	s.dispatch(w, r, dispatchOpts{operation: provider.OpChat, scope: "router:chat"})
}

func (s *Server) responses(w http.ResponseWriter, r *http.Request) {
	s.dispatch(w, r, dispatchOpts{operation: provider.OpResponses, scope: "router:responses"})
}

func (s *Server) embeddings(w http.ResponseWriter, r *http.Request) {
	s.dispatch(w, r, dispatchOpts{operation: provider.OpEmbeddings, scope: "router:embeddings"})
}

func (s *Server) dispatch(w http.ResponseWriter, r *http.Request, opts dispatchOpts) {
	start := time.Now()
	principal, ok := s.authenticate(w, r, opts.scope)
	if !ok {
		return
	}
	body, err := io.ReadAll(r.Body)
	if err != nil {
		openai.WriteError(w, http.StatusBadRequest, openai.TypeInvalidRequest, "invalid request body", "invalid_body")
		return
	}
	secretKinds := []string(nil)
	if s.Settings.SecretPolicy != "off" {
		secretKinds = dataprotection.Kinds(dataprotection.Scan(body))
	}
	if len(secretKinds) > 0 && s.Settings.SecretPolicy != "audit" {
		agentID := r.Header.Get("X-AAP-Agent-Id")
		if agentID == "" && principal.AgentID != nil {
			agentID = *principal.AgentID
		}
		env := r.Header.Get("X-AAP-Environment")
		if env == "" {
			env = principal.Environment
		}
		s.Audit.Enqueue(r.Context(), audit.Event{
			OccurredAt: time.Now().UTC(), OrganizationID: principal.OrganizationID, ProjectID: principal.ProjectID,
			AgentID: agentID, MemberID: principalMemberID(principal), Environment: env, Operation: string(opts.operation), Outcome: "denied",
			ReasonCode: "secret_detected", FindingKinds: secretKinds, HTTPStatus: http.StatusForbidden,
			OverheadMs: time.Since(start).Milliseconds(),
		})
		openai.WriteError(
			w,
			http.StatusForbidden,
			openai.TypePermission,
			"request blocked by data protection policy",
			"secret_detected",
		)
		return
	}
	var modelProbe struct {
		Model  string `json:"model"`
		Stream bool   `json:"stream"`
	}
	_ = json.Unmarshal(body, &modelProbe)
	if modelProbe.Model == "" {
		openai.WriteError(w, http.StatusBadRequest, openai.TypeInvalidRequest, "model is required", "missing_model")
		return
	}
	agentID := r.Header.Get("X-AAP-Agent-Id")
	if agentID == "" && principal.AgentID != nil {
		agentID = *principal.AgentID
	}
	if agentID == "" {
		openai.WriteError(w, http.StatusBadRequest, openai.TypeInvalidRequest, "X-AAP-Agent-Id required", "missing_agent")
		return
	}
	if err := principal.RequireAgent(agentID); err != nil {
		openai.WriteError(w, http.StatusForbidden, openai.TypePermission, err.Error(), "agent_binding")
		return
	}
	env := r.Header.Get("X-AAP-Environment")
	if env == "" {
		env = principal.Environment
	}
	if !principal.ModelAllowed("alias", modelProbe.Model) {
		openai.WriteError(w, http.StatusForbidden, openai.TypePermission, "model not allowed for workload", "model_not_allowed")
		return
	}
	snap := s.Snapshots.Current()
	if snap == nil {
		openai.WriteError(w, http.StatusServiceUnavailable, openai.TypeServer, "snapshot not loaded", "snapshot_unavailable")
		return
	}
	bind, bindOK := snap.BindingByGeneration(principal.GenerationID)
	if !bindOK {
		openai.WriteError(w, http.StatusForbidden, openai.TypePermission, "workload binding missing", "binding_missing")
		return
	}
	routes := snapshot.RouteLookup(snap, agentID, env, modelProbe.Model)
	if len(routes) == 0 {
		openai.WriteError(w, http.StatusNotFound, openai.TypeNotFound, "no route for model alias", "route_not_found")
		return
	}
	route := routes[0]
	dataClass := r.Header.Get("X-AAP-Data-Class")
	regionHint := r.Header.Get("X-AAP-Region-Hint")
	opName := string(opts.operation)
	candidates := router.FilterDeployments(snap, route, opName, dataClass, regionHint)
	if len(candidates) == 0 {
		openai.WriteError(w, http.StatusForbidden, openai.TypePermission, "no deployment satisfies policy filters", "deployment_filtered")
		return
	}
	ordered := s.Selector.Order(route, candidates)
	ctx := r.Context()
	idem := telemetry.IdempotencyKey(r)
	trace := telemetry.TraceParent(r)
	if idem != "" {
		w.Header().Set("Idempotency-Key", idem)
	}
	reqDigest := requestDigest(body)
	if s.cacheLookupEnabled(route, modelProbe.Stream, idem, opts.operation) {
		ckey := cache.CacheKey(principal.OrganizationID, principal.GenerationID, route.ID, opName, snap.Config.RulesDigest, reqDigest)
		if hit, err := s.ResponseCache.Get(ctx, ckey); err == nil && hit != nil {
			s.writeCacheHit(w, hit)
			return
		}
	}
	var firstByteSent bool
	deployAttempts := 0
	maxDeploy := route.MaxAttempts
	if maxDeploy < 1 {
		maxDeploy = len(ordered)
	}
	attemptBudget := routeAttemptBudget(route, maxDeploy)
	totalUpstreamAttempts := 0
	for _, cand := range ordered {
		if deployAttempts >= maxDeploy || totalUpstreamAttempts >= attemptBudget {
			break
		}
		deployAttempts++
		dep := cand.Deployment
		if !RevalidateFallbackAttempt(w, RevalidateInput{
			Snap: snap, Route: route, Principal: principal, Binding: bind,
			AgentID: agentID, Environment: env, ModelAlias: modelProbe.Model,
			Scope: opts.scope, Operation: opts.operation, Stream: modelProbe.Stream,
			DataClass: dataClass, RegionHint: regionHint, DepID: dep.ID,
		}) {
			if w.Header().Get("Content-Type") == "application/json" {
				return
			}
			continue
		}
		adapter := provider.ForProvider(dep.Provider)
		if adapter == nil {
			continue
		}
		if err := provider.RequireCapability(dep.Capabilities, capabilityFor(opts.operation, modelProbe.Stream)); err != nil {
			if route.Enforcement == "blocking" {
				openai.WriteError(w, http.StatusBadRequest, openai.TypeInvalidRequest, err.Error(), "capability_missing")
				return
			}
			continue
		}
		if err := provider.ValidateUnsupported(body, adapter.SupportedParams(opts.operation)); err != nil {
			openai.WriteError(w, http.StatusBadRequest, openai.TypeInvalidRequest, err.Error(), "unsupported_parameter")
			return
		}
		if err := s.checkFeatureCaps(body, dep); err != nil {
			openai.WriteError(w, http.StatusBadRequest, openai.TypeInvalidRequest, err.Error(), "capability_missing")
			return
		}
		apiKey, err := s.Credentials.Resolve(dep.CredentialRef)
		if err != nil {
			openai.WriteError(w, http.StatusServiceUnavailable, openai.TypeServer, "credential unavailable", "credential_missing")
			return
		}
		hold, limErr := s.acquireAll(ctx, snap, bind, principal, dep, body)
		if limErr != nil {
			if limitDenied(limErr) {
				openai.WriteError(w, http.StatusTooManyRequests, openai.TypeRateLimit, "rate limit exceeded", "rate_limit_exceeded")
				return
			}
			if s.Settings.RequireGlobalLimiter && !s.Settings.DevAllowInsecureLimiter {
				openai.WriteError(w, http.StatusServiceUnavailable, openai.TypeServer, "global limiter unavailable", "limiter_unavailable")
				return
			}
			continue
		}
		upStart := time.Now()
		timeout := s.Settings.DefaultUpstreamTimeout
		if dep.TimeoutMS > 0 {
			timeout = time.Duration(dep.TimeoutMS) * time.Millisecond
		}
		upCtx, cancel := context.WithTimeout(ctx, timeout)
		extra := map[string]string{}
		if idem != "" {
			extra["Idempotency-Key"] = idem
		}
		if trace != "" {
			extra["traceparent"] = trace
		}
		maxRetry := dep.MaxRetries
		remaining := attemptBudget - totalUpstreamAttempts
		if remaining < 1 {
			remaining = 1
		}
		result, used, invErr := provider.InvokeWithRetryBudget(upCtx, adapter, provider.InvokeRequest{
			Operation: opts.operation, Deployment: dep, APIKey: apiKey, Body: body,
			Stream: modelProbe.Stream, ExtraHeaders: extra,
		}, maxRetry, remaining)
		totalUpstreamAttempts += used
		cancel()
		if invErr != nil {
			s.releaseAll(ctx, hold, dep.ID, principal.OrganizationID, hold.globalTok.TokensHeld, hold.globalTok.CostMicrosHeld)
			s.Selector.Health.RecordFailure(dep.ID, dep.Cooldown)
			if firstByteSent || !canFallback(route, firstByteSent) {
				openai.WriteError(w, http.StatusBadGateway, openai.TypeServer, invErr.Error(), "upstream_error")
				return
			}
			continue
		}
		if !snapshot.DeploymentAllowed(snap, route, dep.ID, opName, dataClass, regionHint) {
			s.closeResult(result)
			s.releaseAll(ctx, hold, dep.ID, principal.OrganizationID, hold.globalTok.TokensHeld, hold.globalTok.CostMicrosHeld)
			openai.WriteError(w, http.StatusForbidden, openai.TypePermission, "selected deployment left allow set", "allow_set_violation")
			return
		}
		if result.StatusCode < 200 || result.StatusCode >= 300 {
			s.releaseAll(ctx, hold, dep.ID, principal.OrganizationID, hold.globalTok.TokensHeld, hold.globalTok.CostMicrosHeld)
			s.Selector.Health.RecordFailure(dep.ID, dep.Cooldown)
			if provider.NonRetryableHTTPStatus(result.StatusCode) || firstByteSent || !canFallback(route, firstByteSent) {
				s.deliverFailure(w, ctx, dep, opts.operation, result, modelProbe.Stream, modelProbe.Model)
				return
			}
			s.closeResult(result)
			continue
		}
		ttfb := time.Since(start)
		var delivered provider.DeliveryResult
		var delErr error
		switch opts.operation {
		case provider.OpChat:
			delivered, delErr = provider.DeliverChat(ctx, w, dep, result, modelProbe.Stream, modelProbe.Model, s.Settings.MaxResponseBodyBytes)
		case provider.OpEmbeddings:
			bodyOut, readErr := io.ReadAll(io.LimitReader(result.Body, s.Settings.MaxResponseBodyBytes))
			_ = result.Body.Close()
			if readErr != nil {
				delErr = readErr
			} else {
				delivered, delErr = provider.DeliverEmbeddingsResult(w, dep.Provider, result.StatusCode, bodyOut, modelProbe.Model, s.Settings.MaxResponseBodyBytes)
			}
		default:
			delivered, delErr = provider.DeliverResponses(ctx, w, dep, result, modelProbe.Stream, modelProbe.Model, s.Settings.MaxResponseBodyBytes)
		}
		if delErr != nil {
			s.releaseAll(ctx, hold, dep.ID, principal.OrganizationID, hold.globalTok.TokensHeld, hold.globalTok.CostMicrosHeld)
			s.Selector.Health.RecordFailure(dep.ID, dep.Cooldown)
			if firstByteSent || modelProbe.Stream {
				return
			}
			if canFallback(route, firstByteSent) {
				continue
			}
			openai.WriteError(w, http.StatusBadGateway, openai.TypeServer, delErr.Error(), "delivery_error")
			return
		}
		firstByteSent = true
		s.Selector.Health.RecordSuccess(dep.ID, time.Since(upStart))
		s.LocalLimit.RecordLatency(dep.ID, time.Since(start))
		s.finishSuccess(ctx, hold, dep, principal, delivered.Usage)
		if s.cacheLookupEnabled(route, modelProbe.Stream, idem, opts.operation) {
			ckey := cache.CacheKey(principal.OrganizationID, principal.GenerationID, route.ID, opName, snap.Config.RulesDigest, reqDigest)
			s.putCacheAsync(route, ckey, snap.Config.RulesDigest, delivered)
		}
		s.Audit.Enqueue(ctx, audit.Event{
			OccurredAt: time.Now().UTC(), OrganizationID: principal.OrganizationID, ProjectID: principal.ProjectID,
			AgentID: agentID, MemberID: principalMemberID(principal), Environment: env, RouteID: route.ID, DeploymentID: dep.ID, Provider: dep.Provider,
			ModelAlias: modelProbe.Model, Operation: opName, Outcome: "success", HTTPStatus: result.StatusCode,
			ReasonCode: auditReason(secretKinds), FindingKinds: secretKinds,
			Attempts: deployAttempts, TTFBMs: ttfb.Milliseconds(), OverheadMs: time.Since(start).Milliseconds(),
			TraceParent: trace, IdempotencyKey: idem,
		})
		return
	}
	openai.WriteError(w, http.StatusBadGateway, openai.TypeServer, "all deployments failed", "upstream_exhausted")
}

func auditReason(secretKinds []string) string {
	if len(secretKinds) > 0 {
		return "secret_detected_audit"
	}
	return ""
}

func principalMemberID(principal auth.Principal) string {
	if principal.MemberID == nil {
		return ""
	}
	return *principal.MemberID
}

func (s *Server) deliverFailure(w http.ResponseWriter, ctx context.Context, dep snapshot.Deployment, op provider.Operation, result *provider.InvokeResult, stream bool, modelAlias string) {
	switch op {
	case provider.OpChat:
		_, _ = provider.DeliverChat(ctx, w, dep, result, stream, modelAlias, s.Settings.MaxResponseBodyBytes)
	default:
		_, _ = provider.DeliverResponses(ctx, w, dep, result, stream, modelAlias, s.Settings.MaxResponseBodyBytes)
	}
}

func (s *Server) writeCacheHit(w http.ResponseWriter, hit *cache.CachedResponse) {
	for k, v := range hit.Headers {
		w.Header().Set(k, v)
	}
	w.Header().Set("X-AAP-Cache", "HIT")
	w.Header().Set("X-AAP-Config-Digest", hit.ConfigDigest)
	w.WriteHeader(hit.Status)
	_, _ = w.Write(hit.Body)
}

func (s *Server) cacheLookupEnabled(route snapshot.Route, stream bool, idem string, op provider.Operation) bool {
	if s.ResponseCache == nil || !route.ResponseCacheEnabled || stream || idem == "" {
		return false
	}
	switch op {
	case provider.OpChat, provider.OpResponses, provider.OpEmbeddings:
		return true
	default:
		return false
	}
}

func (s *Server) putCacheAsync(route snapshot.Route, key, configDigest string, delivered provider.DeliveryResult) {
	if !delivered.Cacheable || len(delivered.ResponseBody) == 0 {
		return
	}
	ttl := time.Duration(route.ResponseCacheTTLSeconds) * time.Second
	entry := cache.CachedResponse{
		Status: delivered.Status, Body: delivered.ResponseBody, ConfigDigest: configDigest,
		Headers: map[string]string{"Content-Type": "application/json"},
	}
	_ = s.ResponseCache.PutAsync(key, entry, ttl)
}

func (s *Server) closeResult(res *provider.InvokeResult) {
	if res != nil && res.Body != nil {
		_ = res.Body.Close()
	}
}

func canFallback(route snapshot.Route, firstByteSent bool) bool {
	return route.FallbackBeforeFirstByte && !firstByteSent
}

func (s *Server) checkFeatureCaps(body []byte, dep snapshot.Deployment) error {
	if provider.HasTools(body) {
		if err := provider.RequireCapability(dep.Capabilities, "tools"); err != nil {
			return err
		}
	}
	if provider.HasJSONSchema(body) {
		if err := provider.RequireCapability(dep.Capabilities, "json_schema"); err != nil {
			return err
		}
	}
	if provider.HasVision(body) {
		if err := provider.RequireCapability(dep.Capabilities, "vision"); err != nil {
			return err
		}
	}
	return nil
}

func (s *Server) authenticate(w http.ResponseWriter, r *http.Request, scope string) (auth.Principal, bool) {
	authHeader := r.Header.Get("Authorization")
	if !strings.HasPrefix(authHeader, "Bearer ") {
		openai.WriteError(w, http.StatusUnauthorized, openai.TypeAuth, "missing bearer token", "unauthorized")
		return auth.Principal{}, false
	}
	token := strings.TrimSpace(strings.TrimPrefix(authHeader, "Bearer "))
	snap := s.Snapshots.Current()
	if snap == nil {
		openai.WriteError(w, http.StatusServiceUnavailable, openai.TypeServer, "snapshot not loaded", "snapshot_unavailable")
		return auth.Principal{}, false
	}
	principal, err := auth.Authenticate(snap, token)
	if err != nil {
		openai.WriteError(w, http.StatusUnauthorized, openai.TypeAuth, "invalid workload credential", "unauthorized")
		return auth.Principal{}, false
	}
	if err := principal.RequireScope(scope); err != nil {
		openai.WriteError(w, http.StatusForbidden, openai.TypePermission, err.Error(), "scope_denied")
		return auth.Principal{}, false
	}
	return principal, true
}

func capabilityFor(op provider.Operation, stream bool) string {
	switch op {
	case provider.OpEmbeddings:
		return "embeddings"
	case provider.OpResponses:
		if stream {
			return "streaming"
		}
		return "responses"
	default:
		if stream {
			return "streaming"
		}
		return "chat"
	}
}

func requestDigest(body []byte) string {
	sum := sha256.Sum256(body)
	return hex.EncodeToString(sum[:])
}
