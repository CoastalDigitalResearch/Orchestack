package telemetry

import "log"

// Init initializes OpenTelemetry for a service
func Init(serviceName string) func() {
	log.Printf("telemetry: initialized for %s (stub)", serviceName)
	return func() {
		log.Printf("telemetry: shutdown for %s", serviceName)
	}
}
