package auth

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"agent-assurance/services/gateway/internal/snapshot"
)

const secretPrefix = "aap_wk_"

var (
	ErrInvalidCredential = errors.New("invalid workload credential")
	ErrModuleDenied      = errors.New("module_not_entitled")
	ErrScopeDenied       = errors.New("scope_denied")
	ErrAgentBinding      = errors.New("agent_binding_violation")
	ErrModelDenied       = errors.New("model_not_allowed")
	ErrExpired           = errors.New("credential_expired")
)

// Principal is the authenticated workload identity from snapshot bindings.
type Principal struct {
	GenerationID   string
	OrganizationID string
	ProjectID      string
	AgentID        *string
	MemberID       *string
	Environment    string
	Modules        map[string]struct{}
	Scopes         map[string]struct{}
	AllowedModels  []string
	ExpiresAt      *time.Time
}

func ParseBearer(token string) (orgID, generationID string, secret []byte, err error) {
	if !strings.HasPrefix(token, secretPrefix) {
		return "", "", nil, ErrInvalidCredential
	}
	body := token[len(secretPrefix):]
	parts := strings.SplitN(body, ".", 3)
	if len(parts) != 3 {
		return "", "", nil, ErrInvalidCredential
	}
	orgID, generationID = parts[0], parts[1]
	raw, decErr := base64.RawURLEncoding.DecodeString(parts[2])
	if decErr != nil {
		padding := strings.Repeat("=", (-len(parts[2]) % 4))
		raw, decErr = base64.URLEncoding.DecodeString(parts[2] + padding)
	}
	if decErr != nil || len(raw) != 32 {
		return "", "", nil, ErrInvalidCredential
	}
	return orgID, generationID, raw, nil
}

func Authenticate(snap *snapshot.ActivatedSnapshot, bearer string) (Principal, error) {
	orgID, genID, secret, err := ParseBearer(bearer)
	if err != nil {
		return Principal{}, err
	}
	sum := sha256.Sum256(secret)
	bind, ok := snap.ByGenHash[sum]
	if !ok {
		return Principal{}, ErrInvalidCredential
	}
	if bind.GenerationID != genID || bind.OrganizationID != orgID {
		return Principal{}, ErrInvalidCredential
	}
	if bind.OrganizationID != snap.Config.OrganizationID {
		return Principal{}, ErrInvalidCredential
	}
	if bind.RevokedAt != nil && !bind.RevokedAt.After(time.Now().UTC()) {
		return Principal{}, ErrInvalidCredential
	}
	if bind.ExpiresAt != nil && bind.ExpiresAt.Before(time.Now().UTC()) {
		return Principal{}, ErrExpired
	}
	modules := map[string]struct{}{}
	for _, m := range bind.Modules {
		modules[m] = struct{}{}
	}
	if _, ok := modules["router"]; !ok {
		return Principal{}, ErrModuleDenied
	}
	scopes := map[string]struct{}{}
	for _, sc := range bind.Scopes {
		scopes[sc] = struct{}{}
	}
	return Principal{
		GenerationID:   bind.GenerationID,
		OrganizationID: bind.OrganizationID,
		ProjectID:      bind.ProjectID,
		AgentID:        bind.AgentID,
		MemberID:       bind.MemberID,
		Environment:    bind.Environment,
		Modules:        modules,
		Scopes:         scopes,
		AllowedModels:  append([]string(nil), bind.AllowedModelPatterns...),
		ExpiresAt:      bind.ExpiresAt,
	}, nil
}

func (p Principal) RequireScope(scope string) error {
	if _, ok := p.Scopes[scope]; !ok {
		return ErrScopeDenied
	}
	return nil
}

func (p Principal) RequireAgent(agentID string) error {
	if p.AgentID == nil {
		return nil
	}
	if *p.AgentID != agentID {
		return ErrAgentBinding
	}
	return nil
}

func (p Principal) ModelAllowed(provider, model string) bool {
	if len(p.AllowedModels) == 0 {
		return true
	}
	ref := provider + "/" + model
	for _, pattern := range p.AllowedModels {
		if patternMatch(pattern, ref) || patternMatch(pattern, model) {
			return true
		}
	}
	return false
}

func patternMatch(pattern, value string) bool {
	if pattern == value {
		return true
	}
	ok, _ := filepath.Match(pattern, value)
	return ok
}

func SecretHashHex(secret []byte) string {
	sum := sha256.Sum256(secret)
	return "sha256:" + hex.EncodeToString(sum[:])
}

func FormatTestToken(orgID, generationID string, secret []byte) string {
	enc := base64.RawURLEncoding.EncodeToString(secret)
	return fmt.Sprintf("%s%s.%s.%s", secretPrefix, orgID, generationID, enc)
}
