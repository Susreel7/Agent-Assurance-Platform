package snapshot

import (
	"encoding/hex"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"time"
)

var (
	uuidRe   = regexp.MustCompile(`(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
	digestRe = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
)

var (
	validProviders = map[string]struct{}{
		"openai": {}, "openai_compatible": {}, "azure_openai": {}, "anthropic": {},
		"bedrock": {}, "gemini": {}, "vertex": {},
	}
	validCaps = map[string]struct{}{
		"chat": {}, "responses": {}, "embeddings": {}, "streaming": {}, "tools": {},
		"json_schema": {}, "vision": {}, "reasoning": {}, "responses_stream": {},
	}
	validEnv = map[string]struct{}{
		"dev": {}, "test": {}, "staging": {}, "production": {},
	}
	validStrategy = map[string]struct{}{
		"priority": {}, "weighted": {}, "least_busy": {}, "latency": {}, "lowest_cost": {},
	}
	validEnforcement = map[string]struct{}{
		"advisory": {}, "overrideable": {}, "blocking": {},
	}
)

func ValidateConfig(cfg *Config, now time.Time) error {
	if cfg.SchemaRevision != 1 {
		return fmt.Errorf("unsupported schema_revision %d", cfg.SchemaRevision)
	}
	if !uuidRe.MatchString(cfg.SnapshotID) {
		return fmt.Errorf("invalid snapshot_id")
	}
	if !uuidRe.MatchString(cfg.OrganizationID) || !uuidRe.MatchString(cfg.ProjectID) {
		return fmt.Errorf("invalid organization_id or project_id")
	}
	if !digestRe.MatchString(cfg.RulesDigest) {
		return fmt.Errorf("invalid rules_digest")
	}
	if cfg.ExpiresAt.Before(now) {
		return fmt.Errorf("snapshot expired at %s", cfg.ExpiresAt.UTC().Format(time.RFC3339))
	}
	if cfg.IssuedAt.After(now.Add(5 * time.Minute)) {
		return fmt.Errorf("snapshot issued_at is in the future")
	}
	if len(cfg.Deployments) == 0 || len(cfg.Routes) == 0 || len(cfg.WorkloadBindings) == 0 {
		return fmt.Errorf("snapshot requires deployments, routes, and workload_bindings")
	}
	deployIDs := make(map[string]struct{}, len(cfg.Deployments))
	for i := range cfg.Deployments {
		d := &cfg.Deployments[i]
		if err := validateDeployment(d); err != nil {
			return fmt.Errorf("deployments[%d]: %w", i, err)
		}
		if _, dup := deployIDs[d.ID]; dup {
			return fmt.Errorf("duplicate deployment id %s", d.ID)
		}
		deployIDs[d.ID] = struct{}{}
	}
	for i := range cfg.Routes {
		r := &cfg.Routes[i]
		if err := validateRoute(r, deployIDs); err != nil {
			return fmt.Errorf("routes[%d]: %w", i, err)
		}
	}
	if err := validateWorkloadBindings(cfg, now); err != nil {
		return err
	}
	return nil
}

func validateWorkloadBindings(cfg *Config, now time.Time) error {
	seenGen := map[string]struct{}{}
	seenHash := map[string]struct{}{}
	for i := range cfg.WorkloadBindings {
		b := &cfg.WorkloadBindings[i]
		if !uuidRe.MatchString(b.GenerationID) {
			return fmt.Errorf("workload_bindings[%d]: invalid generation_id", i)
		}
		if _, dup := seenGen[b.GenerationID]; dup {
			return fmt.Errorf("workload_bindings[%d]: duplicate generation_id", i)
		}
		seenGen[b.GenerationID] = struct{}{}
		if !digestRe.MatchString(b.SecretHash) {
			return fmt.Errorf("workload_bindings[%d]: invalid secret_hash", i)
		}
		if _, dup := seenHash[b.SecretHash]; dup {
			return fmt.Errorf("workload_bindings[%d]: duplicate secret_hash", i)
		}
		seenHash[b.SecretHash] = struct{}{}
		if b.OrganizationID != cfg.OrganizationID || b.ProjectID != cfg.ProjectID {
			return fmt.Errorf("workload_bindings[%d]: org/project mismatch", i)
		}
		if b.MemberID != nil && !uuidRe.MatchString(*b.MemberID) {
			return fmt.Errorf("workload_bindings[%d]: invalid member_id", i)
		}
		if _, ok := validEnv[b.Environment]; !ok {
			return fmt.Errorf("workload_bindings[%d]: invalid environment", i)
		}
		if b.RevokedAt != nil && !b.RevokedAt.After(now) {
			return fmt.Errorf("workload_bindings[%d]: revoked", i)
		}
		if b.ExpiresAt != nil && b.ExpiresAt.Before(now) {
			return fmt.Errorf("workload_bindings[%d]: expired", i)
		}
		hasRouter := false
		for _, m := range b.Modules {
			if m == "router" {
				hasRouter = true
			}
		}
		if !hasRouter {
			return fmt.Errorf("workload_bindings[%d]: router module required", i)
		}
		if len(b.Scopes) == 0 {
			return fmt.Errorf("workload_bindings[%d]: scopes required", i)
		}
	}
	return nil
}

func validateDeployment(d *Deployment) error {
	if !uuidRe.MatchString(d.ID) {
		return fmt.Errorf("invalid deployment id")
	}
	if _, ok := validProviders[d.Provider]; !ok {
		return fmt.Errorf("unknown provider %q", d.Provider)
	}
	if d.Model == "" || len(d.Model) > 256 {
		return fmt.Errorf("invalid model")
	}
	u, err := url.Parse(d.Endpoint)
	if err != nil || u.Scheme == "" || u.Host == "" {
		return fmt.Errorf("invalid endpoint")
	}
	if d.CredentialRef == "" {
		return fmt.Errorf("credential_ref required")
	}
	if d.Region == "" || d.Jurisdiction == "" {
		return fmt.Errorf("region and jurisdiction required")
	}
	if len(d.Capabilities) == 0 {
		return fmt.Errorf("capabilities required")
	}
	for _, c := range d.Capabilities {
		if _, ok := validCaps[c]; !ok {
			return fmt.Errorf("unknown capability %q", c)
		}
	}
	if d.Priority < 0 || d.Priority > 10000 || d.Weight < 1 || d.Weight > 10000 {
		return fmt.Errorf("priority/weight out of range")
	}
	return nil
}

func validateRoute(r *Route, deployIDs map[string]struct{}) error {
	if !uuidRe.MatchString(r.ID) || !uuidRe.MatchString(r.AgentID) {
		return fmt.Errorf("invalid route or agent id")
	}
	if r.AgentVersionID != nil && !uuidRe.MatchString(*r.AgentVersionID) {
		return fmt.Errorf("invalid agent_version_id")
	}
	if _, ok := validEnv[r.Environment]; !ok {
		return fmt.Errorf("invalid environment %q", r.Environment)
	}
	if r.Alias == "" {
		return fmt.Errorf("alias required")
	}
	if _, ok := validStrategy[r.Strategy]; !ok {
		return fmt.Errorf("invalid strategy %q", r.Strategy)
	}
	if _, ok := validEnforcement[r.Enforcement]; !ok {
		return fmt.Errorf("invalid enforcement %q", r.Enforcement)
	}
	if len(r.DeploymentIDs) == 0 {
		return fmt.Errorf("deployment_ids required")
	}
	seen := map[string]struct{}{}
	for _, id := range r.DeploymentIDs {
		if !uuidRe.MatchString(id) {
			return fmt.Errorf("invalid deployment id in route")
		}
		if _, ok := deployIDs[id]; !ok {
			return fmt.Errorf("route references unknown deployment %s", id)
		}
		if _, dup := seen[id]; dup {
			return fmt.Errorf("duplicate deployment id in route")
		}
		seen[id] = struct{}{}
	}
	if r.MaxAttempts == 0 {
		r.MaxAttempts = 1
	}
	if r.MaxAttempts < 1 || r.MaxAttempts > 10 {
		return fmt.Errorf("max_attempts out of range")
	}
	return nil
}

func BuildIndexes(cfg Config) *ActivatedSnapshot {
	byDeploy := make(map[string]Deployment, len(cfg.Deployments))
	for _, d := range cfg.Deployments {
		byDeploy[d.ID] = d
	}
	byRoute := make(map[string][]Route)
	for _, r := range cfg.Routes {
		key := routeKey(r.AgentID, r.Environment, r.Alias)
		byRoute[key] = append(byRoute[key], r)
	}
	byGen := make(map[[32]byte]WorkloadBinding)
	for _, b := range cfg.WorkloadBindings {
		hexPart := strings.TrimPrefix(b.SecretHash, "sha256:")
		raw, err := hex.DecodeString(hexPart)
		if err != nil || len(raw) != 32 {
			continue
		}
		var h [32]byte
		copy(h[:], raw)
		byGen[h] = b
	}
	return &ActivatedSnapshot{
		Config:    cfg,
		LoadedAt:  time.Now().UTC(),
		ByDeploy:  byDeploy,
		ByRoute:   byRoute,
		ByGenHash: byGen,
	}
}

func routeKey(agent, env, alias string) string {
	return agent + "|" + env + "|" + alias
}

func RouteLookup(s *ActivatedSnapshot, agent, env, alias string) []Route {
	return s.ByRoute[routeKey(agent, env, alias)]
}

// DeploymentAllowed reports whether depID is still in the filtered allow set.
func DeploymentAllowed(s *ActivatedSnapshot, route Route, depID, op, dataClass, regionHint string) bool {
	for _, d := range FilterDeploymentsList(s, route, op, dataClass, regionHint) {
		if d.ID == depID {
			return true
		}
	}
	return false
}

// FilterDeploymentsList is exported for handler recheck of the selected candidate.
func FilterDeploymentsList(s *ActivatedSnapshot, route Route, op, dataClass, regionHint string) []Deployment {
	out := make([]Deployment, 0, len(route.DeploymentIDs))
	permRegions := toSet(route.PermittedRegions)
	dataClasses := toSet(route.DataClasses)
	for _, id := range route.DeploymentIDs {
		d, ok := s.ByDeploy[id]
		if !ok {
			continue
		}
		if !hasCap(d, op) {
			continue
		}
		if len(permRegions) > 0 {
			if _, ok := permRegions[d.Region]; !ok {
				continue
			}
		}
		if regionHint != "" && d.Region != regionHint {
			continue
		}
		if dataClass != "" && len(d.DataClasses) > 0 {
			if _, ok := toSet(d.DataClasses)[dataClass]; !ok {
				continue
			}
		}
		if len(dataClasses) > 0 && len(d.DataClasses) > 0 {
			if !intersects(dataClasses, toSet(d.DataClasses)) {
				continue
			}
		}
		out = append(out, d)
	}
	return out
}

func hasCap(d Deployment, op string) bool {
	for _, c := range d.Capabilities {
		if c == op || (op == "chat" && c == "chat") || (op == "responses" && c == "responses") {
			return true
		}
	}
	return false
}

func toSet(items []string) map[string]struct{} {
	m := make(map[string]struct{}, len(items))
	for _, v := range items {
		m[v] = struct{}{}
	}
	return m
}

func intersects(a, b map[string]struct{}) bool {
	for k := range a {
		if _, ok := b[k]; ok {
			return true
		}
	}
	return false
}
