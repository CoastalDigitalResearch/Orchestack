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

	"github.com/CoastalDigitalResearch/Orchestack/services/session-scheduler/internal/handler"
	"github.com/CoastalDigitalResearch/Orchestack/services/session-scheduler/internal/store"
	_ "github.com/lib/pq"
	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	natsURL := os.Getenv("NATS_URL")
	if natsURL == "" {
		natsURL = "nats://localhost:4222"
	}
	dbURL := os.Getenv("DATABASE_URL")
	if dbURL == "" {
		dbURL = "postgresql://orchestack:orchestack-dev@localhost:5432/orchestack?sslmode=disable"
	}

	// Connect to Postgres
	db, err := sql.Open("postgres", dbURL)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer db.Close()
	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(10)
	db.SetConnMaxLifetime(5 * time.Minute)

	// Connect to NATS
	nc, err := nats.Connect(natsURL,
		nats.RetryOnFailedConnect(true),
		nats.MaxReconnects(-1),
		nats.ReconnectWait(2*time.Second),
	)
	if err != nil {
		log.Fatalf("Failed to connect to NATS: %v", err)
	}
	defer nc.Close()

	js, err := jetstream.New(nc)
	if err != nil {
		log.Fatalf("Failed to create JetStream context: %v", err)
	}

	// Create consumer for ingress events
	pgStore := store.NewPostgresStore(db)
	ingressHandler := handler.NewIngressHandler(js, pgStore)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	consumer, err := js.CreateOrUpdateConsumer(ctx, "STREAM_EVENTS", jetstream.ConsumerConfig{
		Name:          "session-scheduler",
		FilterSubject: "ingress.>",
		AckPolicy:     jetstream.AckExplicitPolicy,
		MaxDeliver:    10,
		AckWait:       30 * time.Second,
	})
	if err != nil {
		log.Fatalf("Failed to create consumer: %v", err)
	}

	// Start consuming
	_, err = consumer.Consume(ingressHandler.HandleMessage)
	if err != nil {
		log.Fatalf("Failed to start consumer: %v", err)
	}

	// HTTP health endpoints
	http.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		if err := db.Ping(); err != nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			fmt.Fprint(w, "db unhealthy")
			return
		}
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})
	http.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		if !nc.IsConnected() {
			w.WriteHeader(http.StatusServiceUnavailable)
			fmt.Fprint(w, "nats disconnected")
			return
		}
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})

	go func() {
		log.Printf("session-scheduler listening on :%s", port)
		log.Fatal(http.ListenAndServe(":"+port, nil))
	}()

	// Graceful shutdown
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh
	log.Println("Shutting down session-scheduler...")
	cancel()
}
