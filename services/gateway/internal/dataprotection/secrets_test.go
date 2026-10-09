package dataprotection

import (
	"strings"
	"testing"
)

func TestScanDetectsSecretsWithoutReturningValues(t *testing.T) {
	t.Parallel()

	cases := []struct {
		name string
		body string
		kind string
	}{
		{"private key", `{"content":"-----BEGIN PRIVATE KEY-----\nabc"}`, "private_key"},
		{"aws access key", `{"content":"AKIAIOSFODNN7EXAMPLE"}`, "aws_access_key"},
		{"github token", `{"content":"ghp_012345678901234567890123456789012345"}`, "github_token"},
		{"openai key", `{"content":"sk-proj-012345678901234567890123456789"}`, "openai_api_key"},
		{"google key", `{"content":"AIza01234567890123456789012345678901234"}`, "google_api_key"},
		{"jwt", `{"content":"eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlMTIz"}`, "jwt"},
		{"bearer", `{"content":"Authorization: Bearer opaque-secret-token-value"}`, "authorization_bearer"},
		{"storage key", `{"content":"AccountKey=YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXphYmNkZWZnaGlqaw=="}`, "azure_storage_key"},
		{"credential url", `{"content":"https://alice:not-for-a-model@example.test/path"}`, "credential_in_url"},
		{"labelled password", `{"content":"password = correct-horse-battery-staple"}`, "labelled_secret"},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			findings := Scan([]byte(tc.body))
			if !contains(Kinds(findings), tc.kind) {
				t.Fatalf("expected %q in findings %#v", tc.kind, findings)
			}
			for _, finding := range findings {
				if strings.Contains(tc.body, finding.Kind) {
					continue
				}
				if strings.Contains(finding.Kind, "012345") {
					t.Fatalf("finding leaked matched material: %#v", finding)
				}
			}
		})
	}
}

func TestScanAllowsOrdinaryAgentPayload(t *testing.T) {
	t.Parallel()

	body := []byte(`{
		"model":"coding",
		"messages":[
			{"role":"system","content":"Review this patch for correctness."},
			{"role":"user","content":"Use OAuth and keep credentials in the vault."}
		]
	}`)
	if findings := Scan(body); len(findings) != 0 {
		t.Fatalf("unexpected findings: %#v", findings)
	}
}

func TestScanDeduplicatesRepeatedKinds(t *testing.T) {
	t.Parallel()

	body := []byte(`{"content":"password=first-secret password=second-secret"}`)
	findings := Scan(body)
	if got := Kinds(findings); len(got) != 1 || got[0] != "labelled_secret" {
		t.Fatalf("unexpected findings: %#v", got)
	}
}

func TestScanCannotBeBypassedWithJSONEscapes(t *testing.T) {
	t.Parallel()

	body := []byte(`{"content":"sk-\u0070roj-012345678901234567890123456789"}`)
	if got := Kinds(Scan(body)); !contains(got, "openai_api_key") {
		t.Fatalf("escaped key was not detected: %#v", got)
	}

	labelled := []byte(`{"pass\u0077ord":"correct-horse-battery-staple"}`)
	if got := Kinds(Scan(labelled)); !contains(got, "labelled_secret") {
		t.Fatalf("escaped secret label was not detected: %#v", got)
	}
}

func BenchmarkScanTypicalRequest(b *testing.B) {
	body := []byte(`{"model":"coding","messages":[{"role":"user","content":"Explain why this Go handler returns 403 and propose a safe unit test."}]}`)
	b.ReportAllocs()
	b.SetBytes(int64(len(body)))
	for i := 0; i < b.N; i++ {
		_ = Scan(body)
	}
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
