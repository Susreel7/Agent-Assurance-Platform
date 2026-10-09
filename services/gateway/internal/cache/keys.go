package cache

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
)

var ErrMiss = errors.New("cache_miss")

func CacheKey(org, credGen, routeID, operation, configDigest, requestDigest string) string {
	h := sha256.New()
	for _, p := range []string{org, credGen, routeID, operation, configDigest, requestDigest} {
		_, _ = h.Write([]byte(p))
		_, _ = h.Write([]byte{0})
	}
	return "gw:rc:" + hex.EncodeToString(h.Sum(nil))
}
