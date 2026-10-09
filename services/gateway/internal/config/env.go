package config

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Settings are process environment configuration (never read elsewhere).
type Settings struct {
	ListenAddr              string
	ConfigDir               string
	ConfigURL               string
	ConfigPublicKeyPEM      string
	ConfigPublicKeyFile     string
	ConfigAuthorization     string
	ConfigOrgID             string
	ConfigPollInterval      time.Duration
	ConfigHTTPTimeout       time.Duration
	ConfigMaxBodyBytes      int64
	ConfigRequiredAtStartup bool
	CredentialsFile         string
	MaxRequestBodyBytes     int64
	MaxResponseBodyBytes    int64
	DefaultUpstreamTimeout  time.Duration
	RequireGlobalLimiter    bool
	RedisLimiterAddr        string
	AuditQueueCapacity      int
	AuditURL                string
	AuditAuthorization      string
	AuditFlushInterval      time.Duration
	SecretPolicy            string
	BuildRevision           string
	DevAllowInsecureLimiter bool
}

func Load() Settings {
	return Settings{
		ListenAddr:              env("GATEWAY_LISTEN", ":8080"),
		ConfigDir:               env("GATEWAY_CONFIG_DIR", "/etc/gateway"),
		ConfigURL:               env("GATEWAY_CONFIG_URL", ""),
		ConfigPublicKeyPEM:      env("GATEWAY_CONFIG_PUBLIC_KEY_PEM", ""),
		ConfigPublicKeyFile:     env("GATEWAY_CONFIG_PUBLIC_KEY_FILE", ""),
		ConfigAuthorization:     env("GATEWAY_CONFIG_AUTHORIZATION", ""),
		ConfigOrgID:             env("GATEWAY_CONFIG_ORG_ID", ""),
		ConfigPollInterval:      envDuration("GATEWAY_CONFIG_POLL_INTERVAL", 30*time.Second),
		ConfigHTTPTimeout:       envDuration("GATEWAY_CONFIG_HTTP_TIMEOUT", 30*time.Second),
		ConfigMaxBodyBytes:      envInt64("GATEWAY_CONFIG_MAX_BYTES", 4<<20),
		ConfigRequiredAtStartup: envBool("GATEWAY_CONFIG_REQUIRED", false),
		CredentialsFile:         env("GATEWAY_CREDENTIALS_FILE", ""),
		MaxRequestBodyBytes:     envInt64("GATEWAY_MAX_REQUEST_BYTES", 8<<20),
		MaxResponseBodyBytes:    envInt64("GATEWAY_MAX_RESPONSE_BYTES", 32<<20),
		DefaultUpstreamTimeout:  envDuration("GATEWAY_UPSTREAM_TIMEOUT", 120*time.Second),
		RequireGlobalLimiter:    envBool("GATEWAY_REQUIRE_GLOBAL_LIMITER", false),
		RedisLimiterAddr:        env("GATEWAY_REDIS_ADDR", ""),
		AuditQueueCapacity:      envInt("GATEWAY_AUDIT_QUEUE_CAPACITY", 4096),
		AuditURL:                env("GATEWAY_AUDIT_URL", ""),
		AuditAuthorization:      env("GATEWAY_AUDIT_AUTHORIZATION", ""),
		AuditFlushInterval:      envDuration("GATEWAY_AUDIT_FLUSH_INTERVAL", time.Second),
		SecretPolicy:            strings.ToLower(env("GATEWAY_SECRET_POLICY", "block")),
		BuildRevision:           env("GATEWAY_BUILD_REVISION", "dev"),
		DevAllowInsecureLimiter: envBool("GATEWAY_DEV_INSECURE_LIMITER", false),
	}
}

// ConfigPublicKeyPEM resolves the pinned verification key from PEM env or file. The gateway
// never uses a public key returned by the config endpoint.
func (s Settings) ConfigPublicKeyPEMResolved() (string, error) {
	if pem := strings.TrimSpace(s.ConfigPublicKeyPEM); pem != "" {
		return pem, nil
	}
	path := strings.TrimSpace(s.ConfigPublicKeyFile)
	if path == "" {
		return "", errors.New("config public key not configured (set GATEWAY_CONFIG_PUBLIC_KEY_PEM or GATEWAY_CONFIG_PUBLIC_KEY_FILE)")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("read config public key file: %w", err)
	}
	pem := strings.TrimSpace(string(raw))
	if pem == "" {
		return "", errors.New("config public key file is empty")
	}
	return pem, nil
}

func env(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}

func envBool(key string, def bool) bool {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		return def
	}
	return b
}

func envInt(key string, def int) int {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}

func envInt64(key string, def int64) int64 {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	n, err := strconv.ParseInt(v, 10, 64)
	if err != nil {
		return def
	}
	return n
}

func envDuration(key string, def time.Duration) time.Duration {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	d, err := time.ParseDuration(v)
	if err != nil {
		return def
	}
	return d
}
