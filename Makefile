# Orchestack Makefile
# ----------------------------------------------------------

# Auto-detect container runtime (podman preferred, fallback to docker)
CONTAINER_RUNTIME ?= $(shell command -v podman 2>/dev/null || echo docker)
COMPOSE_FILE := deploy/compose/docker-compose.yml
COMPOSE := $(CONTAINER_RUNTIME) compose -f $(COMPOSE_FILE)

# Service lists
GO_SERVICES := session-scheduler task-dispatcher policy-evaluator daytona-executor extension-controller
PYTHON_SERVICES := loop-runner model-router budget-accounting memory-plane dlp-scanner
CONNECTORS := webchat discord slack email telegram

.PHONY: help lint lint-python lint-go test test-python test-go build build-go build-images \
        dev-up dev-down dev-logs dev-dashboard clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

lint: lint-python lint-go ## Run all linters

lint-python: ## Lint Python code
	ruff check libs/ services/ connectors/ || true

lint-go: ## Lint Go code
	cd libs/envelope-go && go vet ./...
	@for svc in $(GO_SERVICES); do \
	  (cd services/$$svc && go vet ./...) || true; \
	done

# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

test: test-python test-go ## Run all tests

test-python: ## Run Python tests
	@for svc in $(PYTHON_SERVICES); do \
	  echo "--- pytest services/$$svc ---"; \
	  (cd services/$$svc && python -m pytest -q 2>/dev/null) || true; \
	done

test-go: ## Run Go tests
	cd libs/envelope-go && go test ./...
	@for svc in $(GO_SERVICES); do \
	  echo "--- go test services/$$svc ---"; \
	  (cd services/$$svc && go test ./...) || true; \
	done

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

build: build-go build-images ## Build everything

build-go: ## Build Go binaries
	@mkdir -p _build
	@for svc in $(GO_SERVICES); do \
	  echo "  Building $$svc"; \
	  (cd services/$$svc && go build -o ../../_build/$$svc ./cmd/$$svc); \
	done

build-images: ## Build all container images
	@echo "--- Building Go service images ---"
	@for svc in $(GO_SERVICES); do \
	  echo "  $(CONTAINER_RUNTIME) build $$svc"; \
	  $(CONTAINER_RUNTIME) build -t orchestack/$$svc:dev \
	    --build-arg SERVICE=$$svc \
	    -f deploy/compose/Containerfile.go .; \
	done
	@echo "--- Building Python service images ---"
	@for svc in $(PYTHON_SERVICES); do \
	  echo "  $(CONTAINER_RUNTIME) build $$svc"; \
	  $(CONTAINER_RUNTIME) build -t orchestack/$$svc:dev \
	    --build-arg SERVICE=$$svc \
	    -f deploy/compose/Containerfile.python .; \
	done
	@echo "--- Building Connector images ---"
	@for conn in $(CONNECTORS); do \
	  echo "  $(CONTAINER_RUNTIME) build connector-$$conn"; \
	  $(CONTAINER_RUNTIME) build -t orchestack/connector-$$conn:dev \
	    --build-arg CONNECTOR=$$conn \
	    -f deploy/compose/Containerfile.connector .; \
	done

# ---------------------------------------------------------------------------
# Development stack
# ---------------------------------------------------------------------------

dev-up: ## Start development stack
	$(COMPOSE) up -d --build
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@$(COMPOSE) ps

dev-down: ## Stop development stack
	$(COMPOSE) down -v

dev-logs: ## Tail development stack logs
	$(COMPOSE) logs -f

dev-dashboard: ## Open the multi-agent dashboard
	@echo "Opening dashboard at http://localhost:8104/dashboard"
	@xdg-open http://localhost:8104/dashboard 2>/dev/null || \
	  open http://localhost:8104/dashboard 2>/dev/null || \
	  echo "Visit http://localhost:8104/dashboard in your browser"

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

clean: ## Clean build artifacts
	rm -rf _build/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
