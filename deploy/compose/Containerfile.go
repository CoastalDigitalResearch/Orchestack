# Multi-stage build for Go services
FROM golang:1.23-alpine AS builder

ARG SERVICE
WORKDIR /build

# Copy local libs and service module
COPY libs/envelope-go/ libs/envelope-go/
COPY libs/telemetry-go/ libs/telemetry-go/
COPY services/${SERVICE}/ services/${SERVICE}/

ENV GOWORK=off
RUN cd services/${SERVICE} && go build -o /app ./cmd/${SERVICE}

# Runtime
FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=builder /app /app
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["/app"]
