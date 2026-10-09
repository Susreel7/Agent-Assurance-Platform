package dataprotection

import (
	"encoding/json"
	"regexp"
)

// Finding deliberately contains no matched value or surrounding text. A security
// control must not turn the secret it blocked into a second copy in telemetry.
type Finding struct {
	Kind string
}

type secretPattern struct {
	kind string
	re   *regexp.Regexp
}

var secretPatterns = []secretPattern{
	{kind: "private_key", re: regexp.MustCompile(`-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----`)},
	{kind: "aws_access_key", re: regexp.MustCompile(`\b(?:AKIA|ASIA)[A-Z0-9]{16}\b`)},
	{kind: "github_token", re: regexp.MustCompile(`\b(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{40,255})\b`)},
	{kind: "openai_api_key", re: regexp.MustCompile(`\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,255}\b`)},
	{kind: "anthropic_api_key", re: regexp.MustCompile(`\bsk-ant-[A-Za-z0-9_-]{20,255}\b`)},
	{kind: "google_api_key", re: regexp.MustCompile(`\bAIza[0-9A-Za-z_-]{35}\b`)},
	{kind: "slack_token", re: regexp.MustCompile(`\bxox[baprs]-[A-Za-z0-9-]{10,255}\b`)},
	{kind: "jwt", re: regexp.MustCompile(`\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b`)},
	{kind: "authorization_bearer", re: regexp.MustCompile(`(?i)\bauthorization\s*["']?\s*[:=]\s*["']?bearer\s+[A-Za-z0-9._~+/-]{12,}`)},
	{kind: "azure_storage_key", re: regexp.MustCompile(`(?i)\bAccountKey\s*=\s*[A-Za-z0-9+/]{40,}={0,2}`)},
	{kind: "credential_in_url", re: regexp.MustCompile(`\b[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]{1,128}:[^/\s@]{4,256}@`)},
	{
		kind: "labelled_secret",
		re: regexp.MustCompile(
			`(?i)\b(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|password|passwd|secret[_ -]?key)` +
				`\s*["']?\s*[:=]\s*["']?[A-Za-z0-9._~+/-]{8,512}`,
		),
	},
}

// Scan returns one finding per secret kind. It scans the bounded request bytes before
// JSON decoding so malformed requests cannot evade the egress control.
func Scan(body []byte) []Finding {
	if len(body) == 0 {
		return nil
	}

	found := make(map[string]struct{}, 2)
	scanBytes(body, found)

	// JSON escaping must not become a bypass. A body containing "sk-\u0070roj-..."
	// reaches the provider as "sk-proj-..." after decoding, so inspect decoded scalar
	// values as well as the original bytes. If decoding fails, the raw scan above still
	// protects malformed requests.
	var decoded any
	if json.Unmarshal(body, &decoded) == nil {
		scanJSON(decoded, "", found)
	}

	findings := make([]Finding, 0, len(found))
	for _, pattern := range secretPatterns {
		if _, ok := found[pattern.kind]; ok {
			findings = append(findings, Finding{Kind: pattern.kind})
		}
	}
	return findings
}

func scanBytes(value []byte, found map[string]struct{}) {
	for _, pattern := range secretPatterns {
		if _, exists := found[pattern.kind]; !exists && pattern.re.FindIndex(value) != nil {
			found[pattern.kind] = struct{}{}
		}
	}
}

func scanJSON(value any, label string, found map[string]struct{}) {
	switch typed := value.(type) {
	case string:
		scanBytes([]byte(typed), found)
		if label != "" {
			scanBytes([]byte(label+"="+typed), found)
		}
	case []any:
		for _, child := range typed {
			scanJSON(child, label, found)
		}
	case map[string]any:
		for key, child := range typed {
			scanJSON(child, key, found)
		}
	}
}

func Kinds(findings []Finding) []string {
	kinds := make([]string, len(findings))
	for i, finding := range findings {
		kinds[i] = finding.Kind
	}
	return kinds
}
