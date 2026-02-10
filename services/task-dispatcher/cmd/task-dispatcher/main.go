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
	"github.com/nats-io/nats.go/jetstream"

	"github.com/CoastalDigitalResearch/Orchestack/services/task-dispatcher/internal/handler"
	"github.com/CoastalDigitalResearch/Orchestack/services/task-dispatcher/internal/store"
)

func main() {
	// Read configuration from environment variables.
	port := envOrDefault("PORT", "8081")
	natsURL := envOrDefault("NATS_URL", nats.DefaultURL)
	databaseURL := envOrDefault("DATABASE_URL", "postgres://orchestack:orchestack@localhost:5432/orchestack?sslmode=disable")
	policyEvaluatorURL := envOrDefault("POLICY_EVALUATOR_URL", "http://policy-evaluator:8082")

	// Connect to PostgreSQL.
	pgStore, err := store.NewPostgresStore(databaseURL)
	if err != nil {
		log.Fatalf("fatal: failed to connect to postgres: %v", err)
	}
	defer pgStore.Close()
	log.Println("info: connected to postgres")

	// Connect to NATS.
	nc, err := nats.Connect(natsURL,
		nats.Name("task-dispatcher"),
		nats.RetryOnFailedConnect(true),
		nats.MaxReconnects(-1),
		nats.ReconnectWait(2*time.Second),
		nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
			if err != nil {
				log.Printf("warn: nats disconnected: %v", err)
			}
		}),
		nats.ReconnectHandler(func(_ *nats.Conn) {
			log.Println("info: nats reconnected")
		}),
	)
	if err != nil {
		log.Fatalf("fatal: failed to connect to nats: %v", err)
	}
	defer nc.Close()
	log.Printf("info: connected to nats at %s", natsURL)

	// Create JetStream context.
	js, err := jetstream.New(nc)
	if err != nil {
		log.Fatalf("fatal: failed to create jetstream context: %v", err)
	}

	// Ensure the STREAM_TASKS stream exists (create or bind).
	ctx := context.Background()
	_, err = js.CreateOrUpdateStream(ctx, jetstream.StreamConfig{
		Name:      "STREAM_TASKS",
		Subjects:  []string{"tasks.>"},
		Retention: jetstream.WorkQueuePolicy,
		MaxAge:    24 * time.Hour,
		Storage:   jetstream.FileStorage,
		Replicas:  1,
	})
	if err != nil {
		log.Fatalf("fatal: failed to ensure STREAM_TASKS stream: %v", err)
	}
	log.Println("info: STREAM_TASKS stream ready")

	// Create the dispatcher handler.
	dispatcher := handler.NewDispatcher(pgStore, js, policyEvaluatorURL)

	// Create a durable consumer for tasks.created.
	consumer, err := js.CreateOrUpdateConsumer(ctx, "STREAM_TASKS", jetstream.ConsumerConfig{
		Durable:       "task-dispatcher",
		FilterSubject: "tasks.created",
		AckPolicy:     jetstream.AckExplicitPolicy,
		AckWait:       30 * time.Second,
		MaxDeliver:    5,
		BackOff: []time.Duration{
			2 * time.Second,
			5 * time.Second,
			10 * time.Second,
			30 * time.Second,
		},
	})
	if err != nil {
		log.Fatalf("fatal: failed to create consumer: %v", err)
	}

	// Start consuming messages.
	consCtx, err := consumer.Consume(dispatcher.HandleMessage)
	if err != nil {
		log.Fatalf("fatal: failed to start consuming: %v", err)
	}
	defer consCtx.Stop()
	log.Println("info: consuming from tasks.created")

	// Set up the HTTP health/readiness endpoints.
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		// Check that NATS is still connected.
		if !nc.IsConnected() {
			http.Error(w, "nats not connected", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})

	server := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
	}

	// Start HTTP server in a goroutine.
	go func() {
		log.Printf("info: task-dispatcher HTTP server listening on :%s", port)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("fatal: http server error: %v", err)
		}
	}()

	// Wait for termination signal.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigCh
	log.Printf("info: received signal %s, shutting down", sig)

	// Graceful shutdown.
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	// Stop the NATS consumer first so no new messages arrive.
	consCtx.Stop()

	// Shut down the HTTP server.
	if err := server.Shutdown(shutdownCtx); err != nil {
		log.Printf("error: http server shutdown: %v", err)
	}

	// Drain NATS connection (flushes pending messages).
	if err := nc.Drain(); err != nil {
		log.Printf("error: nats drain: %v", err)
	}

	log.Println("info: task-dispatcher shut down cleanly")
}

// envOrDefault returns the value of the named environment variable, or the
// given default if it is empty.
func envOrDefault(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}
