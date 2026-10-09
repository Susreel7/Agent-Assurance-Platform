package snapshot

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const (
	headerConfigDigest    = "X-AAP-Config-Digest"
	headerRulesDigest     = "X-AAP-Rules-Digest"
	headerConfigKeyID     = "X-AAP-Config-Key-Id"
	headerConfigSignature = "X-AAP-Config-Signature"
	headerSnapshotID      = "X-AAP-Snapshot-Id"
)

// RemoteClient fetches signed router configuration from a control-plane HTTP endpoint.
type RemoteClient struct {
	HTTPClient    *http.Client
	URL           string
	Authorization string
	OrgID         string
	MaxBodyBytes  int64
	Store         *Store
}

// SyncOnce performs one conditional GET. On 304 the etag pointer is unchanged and the store
// is not modified. On 200 the response is verified and activated. etag may be nil.
func (c *RemoteClient) SyncOnce(ctx context.Context, etag *string) error {
	if c.Store == nil {
		return fmt.Errorf("remote config: store not configured")
	}
	if strings.TrimSpace(c.URL) == "" {
		return fmt.Errorf("remote config: URL not configured")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.URL, nil)
	if err != nil {
		return err
	}
	if etag != nil && *etag != "" {
		req.Header.Set("If-None-Match", *etag)
	}
	if c.Authorization != "" {
		req.Header.Set("Authorization", c.Authorization)
	}
	if c.OrgID != "" {
		req.Header.Set("X-Org-Id", c.OrgID)
	}
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	switch resp.StatusCode {
	case http.StatusNotModified:
		if etag != nil {
			if v := strings.TrimSpace(resp.Header.Get("ETag")); v != "" {
				*etag = v
			}
		}
		return nil
	case http.StatusOK:
		return c.activateFromResponse(resp, etag)
	default:
		_, _ = io.Copy(io.Discard, resp.Body)
		return fmt.Errorf("remote config: unexpected status %d", resp.StatusCode)
	}
}

func (c *RemoteClient) activateFromResponse(resp *http.Response, etag *string) error {
	max := c.MaxBodyBytes
	if max < 1 {
		max = 4 << 20
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, max+1))
	if err != nil {
		return fmt.Errorf("remote config: read body: %w", err)
	}
	if int64(len(body)) > max {
		return fmt.Errorf("remote config: body exceeds %d bytes", max)
	}

	sig := strings.TrimSpace(resp.Header.Get(headerConfigSignature))
	keyID := strings.TrimSpace(resp.Header.Get(headerConfigKeyID))
	configDigest := strings.TrimSpace(resp.Header.Get(headerConfigDigest))
	digest := strings.TrimSpace(resp.Header.Get(headerRulesDigest))
	snapID := strings.TrimSpace(resp.Header.Get(headerSnapshotID))
	if sig == "" || keyID == "" || configDigest == "" || digest == "" || snapID == "" {
		return fmt.Errorf("remote config: missing required response headers")
	}

	meta := RemoteResponseMeta{
		ConfigDigest: configDigest,
		RulesDigest:  digest,
		KeyID:        keyID,
		SnapshotID:   snapID,
	}
	if err := c.Store.ActivateExactWithHeaders(body, sig, meta); err != nil {
		return err
	}

	if etag != nil {
		if v := strings.TrimSpace(resp.Header.Get("ETag")); v != "" {
			*etag = v
		} else {
			*etag = fmt.Sprintf(`"%s"`, configDigest)
		}
	}
	return nil
}

func verifyConfigMatchesHeaders(cfg *Config, rulesDigest, keyID, snapshotID string) error {
	if cfg.RulesDigest != rulesDigest {
		return fmt.Errorf("remote config: rules_digest header mismatch")
	}
	if cfg.KeyID != keyID {
		return fmt.Errorf("remote config: key_id header mismatch")
	}
	if cfg.SnapshotID != snapshotID {
		return fmt.Errorf("remote config: snapshot_id header mismatch")
	}
	return nil
}

// PollRemote runs SyncOnce immediately, then on each tick until ctx is cancelled.
func PollRemote(ctx context.Context, client *RemoteClient, interval time.Duration) {
	if interval < time.Second {
		interval = time.Second
	}
	var etag string
	_ = client.SyncOnce(ctx, &etag)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			_ = client.SyncOnce(ctx, &etag)
		}
	}
}

// NewRemoteHTTPClient returns an HTTP client with strict timeouts for config polling.
func NewRemoteHTTPClient(timeout time.Duration) *http.Client {
	if timeout < time.Second {
		timeout = 30 * time.Second
	}
	return &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			ResponseHeaderTimeout: timeout,
			MaxIdleConns:          2,
			IdleConnTimeout:       90 * time.Second,
		},
	}
}
