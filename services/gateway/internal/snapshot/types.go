package snapshot

import "time"

// Config is the signed router snapshot (schema_revision 1 + embedded workload bindings).
type Config struct {
	SchemaRevision     int               `json:"schema_revision"`
	SnapshotID         string            `json:"snapshot_id"`
	OrganizationID     string            `json:"organization_id"`
	ProjectID          string            `json:"project_id"`
	IssuedAt           time.Time         `json:"issued_at"`
	ExpiresAt          time.Time         `json:"expires_at"`
	RulesDigest        string            `json:"rules_digest"`
	KeyID              string            `json:"key_id,omitempty"`
	Signature          string            `json:"signature,omitempty"`
	Deployments        []Deployment      `json:"deployments"`
	Routes             []Route           `json:"routes"`
	WorkloadBindings   []WorkloadBinding `json:"workload_bindings"`
	OrganizationLimits RateLimits        `json:"organization_limits,omitempty"`
}

type RateLimits struct {
	RPM               *int   `json:"rpm,omitempty"`
	TPM               *int   `json:"tpm,omitempty"`
	MaxConcurrency    *int   `json:"max_concurrency,omitempty"`
	DailyBudgetMicros *int64 `json:"daily_budget_micros,omitempty"`
}

type CooldownPolicy struct {
	FailureThreshold  int `json:"failure_threshold"`
	InitialCooldownMS int `json:"initial_cooldown_ms"`
	MaxCooldownMS     int `json:"max_cooldown_ms"`
}

type Deployment struct {
	ID                    string         `json:"id"`
	Provider              string         `json:"provider"`
	Model                 string         `json:"model"`
	Endpoint              string         `json:"endpoint"`
	CredentialRef         string         `json:"credential_ref"`
	Region                string         `json:"region"`
	Jurisdiction          string         `json:"jurisdiction"`
	Capabilities          []string       `json:"capabilities"`
	Priority              int            `json:"priority"`
	Weight                int            `json:"weight"`
	RPM                   *int           `json:"rpm,omitempty"`
	TPM                   *int           `json:"tpm,omitempty"`
	TimeoutMS             int            `json:"timeout_ms,omitempty"`
	MaxRetries            int            `json:"max_retries,omitempty"`
	DataClasses           []string       `json:"data_classes,omitempty"`
	InputPriceMicrosPerM  int64          `json:"input_price_micros_per_m,omitempty"`
	OutputPriceMicrosPerM int64          `json:"output_price_micros_per_m,omitempty"`
	MaxConcurrency        *int           `json:"max_concurrency,omitempty"`
	DailyBudgetMicros     *int64         `json:"daily_budget_micros,omitempty"`
	Cooldown              CooldownPolicy `json:"cooldown"`
}

type Route struct {
	ID                      string   `json:"id"`
	AgentID                 string   `json:"agent_id"`
	AgentVersionID          *string  `json:"agent_version_id"`
	Environment             string   `json:"environment"`
	Alias                   string   `json:"alias"`
	Strategy                string   `json:"strategy"`
	DeploymentIDs           []string `json:"deployment_ids"`
	PermittedRegions        []string `json:"permitted_regions,omitempty"`
	DataClasses             []string `json:"data_classes,omitempty"`
	Enforcement             string   `json:"enforcement"`
	FallbackBeforeFirstByte bool     `json:"fallback_before_first_byte"`
	MaxAttempts             int      `json:"max_attempts,omitempty"`
	ResponseCacheEnabled    bool     `json:"response_cache_enabled"`
	ResponseCacheTTLSeconds int      `json:"response_cache_ttl_seconds,omitempty"`
}

type WorkloadBinding struct {
	GenerationID         string     `json:"generation_id"`
	SecretHash           string     `json:"secret_hash"`
	OrganizationID       string     `json:"organization_id"`
	ProjectID            string     `json:"project_id"`
	AgentID              *string    `json:"agent_id"`
	MemberID             *string    `json:"member_id"`
	Environment          string     `json:"environment"`
	Modules              []string   `json:"modules"`
	Scopes               []string   `json:"scopes"`
	AllowedModelPatterns []string   `json:"allowed_model_patterns"`
	ExpiresAt            *time.Time `json:"expires_at"`
	RevokedAt            *time.Time `json:"revoked_at"`
	RPM                  *int       `json:"rpm,omitempty"`
	TPM                  *int       `json:"tpm,omitempty"`
	MaxConcurrency       *int       `json:"max_concurrency,omitempty"`
	DailyBudgetMicros    *int64     `json:"daily_budget_micros,omitempty"`
}

type ActivatedSnapshot struct {
	Config    Config
	LoadedAt  time.Time
	ByDeploy  map[string]Deployment
	ByRoute   map[string][]Route
	ByGenHash map[[32]byte]WorkloadBinding
}
