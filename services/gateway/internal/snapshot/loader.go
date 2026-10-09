package snapshot

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"time"
)

const (
	configFileName    = "router.json"
	signatureFileName = "router.json.sig"
)

type Store struct {
	publicKeyPEM string
	val          atomic.Pointer[ActivatedSnapshot]
	lastErr      atomic.Value
}

func NewStore(publicKeyPEM string) *Store {
	return &Store{publicKeyPEM: publicKeyPEM}
}

func (s *Store) Current() *ActivatedSnapshot {
	return s.val.Load()
}

func (s *Store) LastError() string {
	v := s.lastErr.Load()
	if v == nil {
		return ""
	}
	return v.(string)
}

func (s *Store) ReloadFromDir(dir string) error {
	cfgBytes, err := os.ReadFile(filepath.Join(dir, configFileName))
	if err != nil {
		return fmt.Errorf("read router config: %w", err)
	}
	sigBytes, err := os.ReadFile(filepath.Join(dir, signatureFileName))
	if err != nil {
		return fmt.Errorf("read signature: %w", err)
	}
	sig := strings.TrimSpace(string(sigBytes))
	return s.ActivateExact(cfgBytes, sig)
}

// RemoteResponseMeta is metadata from a gateway-config HTTP response (never used for keys).
type RemoteResponseMeta struct {
	ConfigDigest string
	RulesDigest  string
	KeyID        string
	SnapshotID   string
}

// ActivateExact verifies a detached standard-base64 ASN.1 ES256 signature, parses and
// validates the config, then atomically activates it. Failures preserve the last good snapshot.
func (s *Store) ActivateExact(configBytes []byte, signatureB64 string) error {
	return s.activateExact(configBytes, signatureB64, nil)
}

// ActivateExactWithHeaders is ActivateExact plus checks that response headers match the parsed config.
func (s *Store) ActivateExactWithHeaders(configBytes []byte, signatureB64 string, meta RemoteResponseMeta) error {
	return s.activateExact(configBytes, signatureB64, &meta)
}

func (s *Store) activateExact(configBytes []byte, signatureB64 string, meta *RemoteResponseMeta) error {
	if err := VerifyDetachedECDSA(s.publicKeyPEM, configBytes, signatureB64); err != nil {
		s.lastErr.Store(err.Error())
		return err
	}
	var cfg Config
	if err := json.Unmarshal(configBytes, &cfg); err != nil {
		s.lastErr.Store(err.Error())
		return fmt.Errorf("parse config: %w", err)
	}
	if meta != nil {
		sum := sha256.Sum256(configBytes)
		actualConfigDigest := fmt.Sprintf("sha256:%x", sum)
		if actualConfigDigest != meta.ConfigDigest {
			err := fmt.Errorf("remote config: config_digest header mismatch")
			s.lastErr.Store(err.Error())
			return err
		}
		if err := verifyConfigMatchesHeaders(&cfg, meta.RulesDigest, meta.KeyID, meta.SnapshotID); err != nil {
			s.lastErr.Store(err.Error())
			return err
		}
	}
	now := time.Now().UTC()
	if err := ValidateConfig(&cfg, now); err != nil {
		s.lastErr.Store(err.Error())
		return err
	}
	s.val.Store(BuildIndexes(cfg))
	s.lastErr.Store("")
	return nil
}

func (s *Store) TryReloadFromDir(dir string) {
	_ = s.ReloadFromDir(dir)
}
