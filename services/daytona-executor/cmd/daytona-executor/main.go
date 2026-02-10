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

	"github.com/nats-io/nats.go"

	"github.com/CoastalDigitalResearch/Orchestack/services/daytona-executor/internal/handler"
	"github.com/CoastalDigitalResearch/Orchestack/services/daytona-executor/internal/sandbox"
)

func main() {
	port := envOr("PORT", "8083")
	natsURL := envOr("NATS_URL", nats.DefaultURL)

	// ── Sandbox manager ───────────────────────────────────────────────
	store := sandbox.NewInMemoryStore()
	cfg := sandbox.DefaultManagerConfig()
	mgr := sandbox.NewSandboxManager(store, cfg)

	// ── NATS connection ───────────────────────────────────────────────
	var toolHandler *handler.ToolHandler

	nc, err := nats.Connect(natsURL,
		nats.Name("daytona-executor"),
		nats.ReconnectWait(2*time.Second),
		nats.MaxReconnects(-1),
		nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
			log.Printf("[nats] disconnected: %v", err)
		}),
		nats.ReconnectHandler(func(nc *nats.Conn) {
			log.Printf("[nats] reconnected to %s", nc.ConnectedUrl())
		}),
	)
	if err != nil {
		log.Printf("[nats] connection failed (continuing without NATS): %v", err)
	} else {
		log.Printf("[nats] connected to %s", nc.ConnectedUrl())

		toolHandler = handler.NewToolHandler(nc, mgr)
		if err := toolHandler.Subscribe(); err != nil {
			log.Printf("[nats] tool subscribe failed: %v", err)
		}
	}

	// ── HTTP server ───────────────────────────────────────────────────
	mux := http.NewServeMux()

	// Health endpoints
	natsConnected := func() bool {
		return nc != nil && nc.IsConnected()
	}

	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})

	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		if !natsConnected() {
			w.WriteHeader(http.StatusServiceUnavailable)
			fmt.Fprint(w, "nats not connected")
			return
		}
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})

	// API endpoints
	apiHandler := handler.NewAPIHandler(mgr)
	apiHandler.RegisterRoutes(mux)

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// ── Background cleanup ────────────────────────────────────────────
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go func() {
		ticker := time.NewTicker(cfg.CleanupInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				mgr.CleanupExpired()
			case <-ctx.Done():
				return
			}
		}
	}()

	// ── Start HTTP server ─────────────────────────────────────────────
	go func() {
		log.Printf("[http] daytona-executor listening on :%s", port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("[http] server error: %v", err)
		}
	}()

	// ── Graceful shutdown ─────────────────────────────────────────────
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	log.Println("[main] shutting down...")

	cancel() // stop cleanup goroutine

	if toolHandler != nil {
		_ = toolHandler.Unsubscribe()
	}
	if nc != nil {
		nc.Close()
	}

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("[http] shutdown error: %v", err)
	}

	log.Println("[main] stopped")
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
