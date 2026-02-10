package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	_ "github.com/lib/pq"

	"github.com/CoastalDigitalResearch/Orchestack/services/policy-evaluator/internal/handler"
	"github.com/CoastalDigitalResearch/Orchestack/services/policy-evaluator/internal/policy"
	"github.com/CoastalDigitalResearch/Orchestack/services/policy-evaluator/internal/store"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8082"
	}

	databaseURL := os.Getenv("DATABASE_URL")
	natsURL := os.Getenv("NATS_URL")
	_ = natsURL // reserved for future NATS integration

	// Connect to Postgres.
	var db *sql.DB
	var policyStore *store.PostgresPolicyStore
	if databaseURL != "" {
		var err error
		db, err = sql.Open("postgres", databaseURL)
		if err != nil {
			log.Fatalf("failed to open database: %v", err)
		}
		db.SetMaxOpenConns(10)
		db.SetMaxIdleConns(5)
		db.SetConnMaxLifetime(5 * time.Minute)

		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := db.PingContext(ctx); err != nil {
			log.Fatalf("failed to ping database: %v", err)
		}
		log.Println("connected to Postgres")
		policyStore = store.NewPostgresPolicyStore(db)
	} else {
		log.Println("WARNING: DATABASE_URL not set; running without database (health-only mode)")
	}

	// Build the policy engine.
	var engine *policy.PolicyEngine
	if policyStore != nil {
		engine = policy.NewPolicyEngine(policyStore)

		// Pre-load policies for the default tenant.
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := engine.LoadPolicies(ctx, "tenant-default"); err != nil {
			log.Printf("WARNING: failed to pre-load default tenant policies: %v", err)
		}
	}

	// Set up HTTP mux.
	mux := http.NewServeMux()

	// Health endpoints.
	dbReady := db != nil
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		if dbReady {
			ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
			defer cancel()
			if err := db.PingContext(ctx); err != nil {
				w.WriteHeader(http.StatusServiceUnavailable)
				fmt.Fprintf(w, "database not ready: %v", err)
				return
			}
		}
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})

	// Policy evaluation endpoint.
	if engine != nil {
		evalHandler := handler.NewEvaluateHandler(engine)
		mux.Handle("/v1/evaluate", evalHandler)
	} else {
		mux.HandleFunc("/v1/evaluate", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusServiceUnavailable)
			fmt.Fprint(w, `{"error":"policy evaluator not configured: DATABASE_URL is required"}`)
		})
	}

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Graceful shutdown.
	done := make(chan struct{})
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		sig := <-sigCh
		log.Printf("received signal %v, shutting down...", sig)

		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if err := srv.Shutdown(ctx); err != nil {
			log.Printf("HTTP server shutdown error: %v", err)
		}
		if db != nil {
			if err := db.Close(); err != nil {
				log.Printf("database close error: %v", err)
			}
		}
		close(done)
	}()

	log.Printf("policy-evaluator listening on :%s", port)
	if err := srv.ListenAndServe(); err != http.ErrServerClosed {
		log.Fatalf("HTTP server error: %v", err)
	}
	<-done
	log.Println("policy-evaluator stopped")
}
