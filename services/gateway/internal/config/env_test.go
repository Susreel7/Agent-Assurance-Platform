package config_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agent-assurance/services/gateway/internal/config"
)

func TestConfigPublicKeyPEMResolvedFromFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "pub.pem")
	const pem = "-----BEGIN PUBLIC KEY-----\nTEST\n-----END PUBLIC KEY-----\n"
	if err := os.WriteFile(path, []byte(pem), 0o600); err != nil {
		t.Fatal(err)
	}
	s := config.Settings{ConfigPublicKeyFile: path}
	got, err := s.ConfigPublicKeyPEMResolved()
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	if got != strings.TrimSpace(pem) {
		t.Fatalf("got %q", got)
	}
}

func TestConfigPublicKeyPEMResolvedMissing(t *testing.T) {
	s := config.Settings{}
	if _, err := s.ConfigPublicKeyPEMResolved(); err == nil {
		t.Fatal("expected error when neither PEM nor file configured")
	}
}
