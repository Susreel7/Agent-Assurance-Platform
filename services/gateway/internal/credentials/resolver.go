package credentials

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// Resolver maps credential_ref to secret material without logging values.
type Resolver struct {
	byRef map[string]string
}

func LoadFromFile(path string) (*Resolver, error) {
	if path == "" {
		return &Resolver{byRef: map[string]string{}}, nil
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var raw map[string]string
	if err := json.Unmarshal(b, &raw); err != nil {
		return nil, err
	}
	return &Resolver{byRef: raw}, nil
}

func (r *Resolver) Resolve(ref string) (string, error) {
	if v, ok := r.byRef[ref]; ok && v != "" {
		return v, nil
	}
	envKey := "GATEWAY_CRED_" + strings.ToUpper(strings.NewReplacer("-", "_", ".", "_").Replace(ref))
	if v := strings.TrimSpace(os.Getenv(envKey)); v != "" {
		return v, nil
	}
	return "", fmt.Errorf("credential_ref %q not found", ref)
}
