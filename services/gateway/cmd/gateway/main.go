package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"agent-assurance/services/gateway/internal/audit"
	"agent-assurance/services/gateway/internal/cache"
	"agent-assurance/services/gateway/internal/config"
	"agent-assurance/services/gateway/internal/credentials"
	"agent-assurance/services/gateway/internal/handler"
	"agent-assurance/services/gateway/internal/limiter"
	"agent-assurance/services/gateway/internal/router"
	"agent-assurance/services/gateway/internal/snapshot"
)

func main() {
	settings := config.Load()
	pubPEM, err := settings.ConfigPublicKeyPEMResolved()
	if err != nil {
		log.Fatalf("config public key: %v", err)
	}
	creds, err := credentials.LoadFromFile(settings.CredentialsFile)
	if err != nil {
		log.Fatalf("credentials: %v", err)
	}
	store := snapshot.NewStore(pubPEM)

	ctx, stopPoll := context.WithCancel(context.Background())
	defer stopPoll()
	configSyncDone := make(chan struct{})

	if settings.ConfigURL != "" {
		remote := &snapshot.RemoteClient{
			HTTPClient:    snapshot.NewRemoteHTTPClient(settings.ConfigHTTPTimeout),
			URL:           settings.ConfigURL,
			Authorization: settings.ConfigAuthorization,
			OrgID:         settings.ConfigOrgID,
			MaxBodyBytes:  settings.ConfigMaxBodyBytes,
			Store:         store,
		}
		if err := remote.SyncOnce(ctx, nil); err != nil {
			if settings.ConfigRequiredAtStartup {
				log.Fatalf("initial remote config load: %v", err)
			}
			log.Printf("initial remote config load failed (will retry): %v", err)
		}
		go func() {
			snapshot.PollRemote(ctx, remote, settings.ConfigPollInterval)
			close(configSyncDone)
		}()
	} else {
		if err := store.ReloadFromDir(settings.ConfigDir); err != nil {
			if settings.ConfigRequiredAtStartup {
				log.Fatalf("initial snapshot load: %v", err)
			}
			log.Printf("initial snapshot load failed (will retry): %v", err)
		}
		go func() {
			reloadLoop(ctx, settings.ConfigDir, store, settings.ConfigPollInterval)
			close(configSyncDone)
		}()
	}

	local := limiter.NewMemoryLimiter()
	global := limiter.NewRedisLimiter(settings.RedisLimiterAddr)
	var respCache *cache.ResponseCache
	if settings.RedisLimiterAddr != "" {
		if c, err := cache.NewResponseCache(settings.RedisLimiterAddr, int(settings.MaxResponseBodyBytes)); err == nil {
			respCache = c
		}
	}
	auditQueue := audit.NewQueue(settings.AuditQueueCapacity)
	auditExporter := &audit.Exporter{
		Queue:         auditQueue,
		URL:           settings.AuditURL,
		Authorization: settings.AuditAuthorization,
	}
	auditExportDone := make(chan struct{})
	go func() {
		auditExporter.Run(ctx, settings.AuditFlushInterval)
		close(auditExportDone)
	}()
	srv := &handler.Server{
		Settings:      settings,
		Snapshots:     store,
		Credentials:   creds,
		LocalLimit:    local,
		GlobalLimit:   global,
		Selector:      router.NewSelector(local),
		Audit:         auditQueue,
		ResponseCache: respCache,
	}
	httpSrv := &http.Server{
		Addr:              settings.ListenAddr,
		Handler:           srv.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       0,
		WriteTimeout:      0,
		IdleTimeout:       120 * time.Second,
	}
	go func() {
		log.Printf("gateway listening on %s", settings.ListenAddr)
		if err := httpSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("listen: %v", err)
		}
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	stopPoll()
	select {
	case <-configSyncDone:
	case <-time.After(5 * time.Second):
		log.Printf("config sync goroutine did not stop within 5s")
	}
	select {
	case <-auditExportDone:
	case <-time.After(5 * time.Second):
		log.Printf("audit exporter did not stop within 5s")
	}
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(shutdownCtx)
	if respCache != nil {
		_ = respCache.Flush(shutdownCtx)
		respCache.Close()
	}
	if err := auditExporter.Flush(shutdownCtx); err != nil {
		log.Printf("final audit flush failed: %v", err)
	}
}

func reloadLoop(ctx context.Context, dir string, store *snapshot.Store, interval time.Duration) {
	if interval < time.Second {
		interval = 5 * time.Second
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			store.TryReloadFromDir(dir)
		}
	}
}
