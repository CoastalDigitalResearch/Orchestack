// Extension Controller — Orchestack G-002
//
// Reconciles extension manifests from a GitOps config repo against the
// persistent registry and exposes an HTTP management API.
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/CoastalDigitalResearch/Orchestack/services/extension-controller/internal/handler"
	"github.com/CoastalDigitalResearch/Orchestack/services/extension-controller/internal/reconciler"
	"github.com/CoastalDigitalResearch/Orchestack/services/extension-controller/internal/registry"
	"github.com/nats-io/nats.go"
)

func main() {
	// -----------------------------------------------------------------------
	// Configuration (env vars with sensible defaults)
	// -----------------------------------------------------------------------
	port := envOrDefault("PORT", "8084")
	pgDSN := envOrDefault("DATABASE_URL", "postgres://orchestack:orchestack@localhost:5432/orchestack?sslmode=disable")
	natsURL := envOrDefault("NATS_URL", nats.DefaultURL)
	repoPath := envOrDefault("GIT_REPO_PATH", "/data/config-repo")

	// -----------------------------------------------------------------------
	// Postgres
	// -----------------------------------------------------------------------
	store, err := registry.NewPostgresExtensionStore(pgDSN)
	if err != nil {
		log.Fatalf("postgres: %v", err)
	}
	defer store.Close()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := store.EnsureSchema(ctx); err != nil {
		log.Fatalf("ensure schema: %v", err)
	}
	log.Println("postgres connected, schema ready")

	// -----------------------------------------------------------------------
	// NATS
	// -----------------------------------------------------------------------
	nc, err := nats.Connect(natsURL,
		nats.RetryOnFailedConnect(true),
		nats.MaxReconnects(-1),
		nats.ReconnectWait(2*time.Second),
	)
	if err != nil {
		log.Fatalf("nats: %v", err)
	}
	defer nc.Close()
	log.Printf("nats connected (%s)", natsURL)

	// -----------------------------------------------------------------------
	// Reconciler (background)
	// -----------------------------------------------------------------------
	rec := reconciler.New(store, nc, repoPath)
	go rec.ReconcileLoop(ctx)

	// -----------------------------------------------------------------------
	// HTTP server
	// -----------------------------------------------------------------------
	api := handler.NewAPI(store)

	mux := http.NewServeMux()

	// Health probes.
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})

	// Extension API.
	mux.Handle("/v1/", api)

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// -----------------------------------------------------------------------
	// Graceful shutdown
	// -----------------------------------------------------------------------
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		log.Printf("extension-controller listening on :%s", port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("http: %v", err)
		}
	}()

	sig := <-sigCh
	log.Printf("received %s, shutting down", sig)
	cancel() // stop reconciler

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("http shutdown: %v", err)
	}
	nc.Drain()
	log.Println("extension-controller stopped")
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
