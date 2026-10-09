package snapshot

import (
	"crypto/ecdsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/pem"
	"errors"
	"fmt"
)

// VerifyDetachedECDSA checks a P-256 detached signature over exact payload bytes.
func VerifyDetachedECDSA(publicKeyPEM string, payload []byte, signatureB64 string) error {
	if publicKeyPEM == "" {
		return errors.New("config public key not configured")
	}
	sig, err := base64.StdEncoding.DecodeString(signatureB64)
	if err != nil {
		return fmt.Errorf("decode signature: %w", err)
	}
	pub, err := parseECDSAPublicKey(publicKeyPEM)
	if err != nil {
		return err
	}
	sum := sha256.Sum256(payload)
	if !ecdsa.VerifyASN1(pub, sum[:], sig) {
		return errors.New("signature verification failed")
	}
	return nil
}

func parseECDSAPublicKey(pemBytes string) (*ecdsa.PublicKey, error) {
	block, _ := pem.Decode([]byte(pemBytes))
	if block == nil {
		return nil, errors.New("invalid PEM public key")
	}
	switch block.Type {
	case "PUBLIC KEY":
		pub, err := x509.ParsePKIXPublicKey(block.Bytes)
		if err != nil {
			return nil, err
		}
		ec, ok := pub.(*ecdsa.PublicKey)
		if !ok || ec.Curve.Params().Name != "P-256" {
			return nil, errors.New("public key must be ECDSA P-256")
		}
		return ec, nil
	default:
		return nil, fmt.Errorf("unsupported PEM type %q", block.Type)
	}
}
