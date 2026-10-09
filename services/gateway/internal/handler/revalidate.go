package handler

import (
	"net/http"
	"time"

	"agent-assurance/services/gateway/internal/auth"
	"agent-assurance/services/gateway/internal/openai"
	"agent-assurance/services/gateway/internal/provider"
	"agent-assurance/services/gateway/internal/snapshot"
)

type RevalidateInput struct {
	Snap        *snapshot.ActivatedSnapshot
	Route       snapshot.Route
	Principal   auth.Principal
	Binding     snapshot.WorkloadBinding
	AgentID     string
	Environment string
	ModelAlias  string
	Scope       string
	Operation   provider.Operation
	Stream      bool
	DataClass   string
	RegionHint  string
	DepID       string
}

// RevalidateFallbackAttempt checks credential, entitlement, routing, and allow-set before each deployment try.
func RevalidateFallbackAttempt(w http.ResponseWriter, in RevalidateInput) bool {
	now := time.Now().UTC()
	if in.Binding.RevokedAt != nil && !in.Binding.RevokedAt.After(now) {
		openai.WriteError(w, http.StatusUnauthorized, openai.TypeAuth, "credential revoked", "unauthorized")
		return false
	}
	if in.Binding.ExpiresAt != nil && in.Binding.ExpiresAt.Before(now) {
		openai.WriteError(w, http.StatusUnauthorized, openai.TypeAuth, "credential expired", "unauthorized")
		return false
	}
	if in.Binding.OrganizationID != in.Snap.Config.OrganizationID {
		openai.WriteError(w, http.StatusForbidden, openai.TypePermission, "organization mismatch", "binding_mismatch")
		return false
	}
	if err := in.Principal.RequireScope(in.Scope); err != nil {
		openai.WriteError(w, http.StatusForbidden, openai.TypePermission, err.Error(), "scope_denied")
		return false
	}
	if _, ok := in.Principal.Modules["router"]; !ok {
		openai.WriteError(w, http.StatusForbidden, openai.TypePermission, "module not entitled", "module_denied")
		return false
	}
	if err := in.Principal.RequireAgent(in.AgentID); err != nil {
		openai.WriteError(w, http.StatusForbidden, openai.TypePermission, err.Error(), "agent_binding")
		return false
	}
	if !in.Principal.ModelAllowed("alias", in.ModelAlias) {
		openai.WriteError(w, http.StatusForbidden, openai.TypePermission, "model not allowed for workload", "model_not_allowed")
		return false
	}
	if in.Route.AgentID != "" && in.Route.AgentID != in.AgentID {
		return false
	}
	if in.Route.Environment != "" && in.Route.Environment != in.Environment {
		return false
	}
	opName := string(in.Operation)
	if !snapshot.DeploymentAllowed(in.Snap, in.Route, in.DepID, opName, in.DataClass, in.RegionHint) {
		return false
	}
	return true
}
