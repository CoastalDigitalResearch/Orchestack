.PHONY: help lint test build dev-up dev-down dev-logs clean

COMPOSE := docker compose -f deploy/compose/docker-compose.yml

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

lint: lint-python lint-go ## Run all linters

lint-python: ## Lint Python code
	ruff check libs/ services/ connectors/
	ruff format --check libs/ services/ connectors/

lint-go: ## Lint Go code
	cd libs/envelope-go && go vet ./...
	cd services/session-scheduler && go vet ./...
	cd services/task-dispatcher && go vet ./...
	cd services/policy-evaluator && go vet ./...
	cd services/daytona-executor && go vet ./...
	cd services/extension-controller && go vet ./...

test: test-python test-go ## Run all tests

test-python: ## Run Python tests
	python -m pytest libs/ services/ connectors/ -v

test-go: ## Run Go tests
	cd libs/envelope-go && go test ./...
	cd services/session-scheduler && go test ./...
	cd services/task-dispatcher && go test ./...
	cd services/policy-evaluator && go test ./...
	cd services/daytona-executor && go test ./...
	cd services/extension-controller && go test ./...

build: build-go build-images ## Build everything

build-go: ## Build Go binaries
	cd services/session-scheduler && go build -o ../../_build/session-scheduler ./cmd
	cd services/task-dispatcher && go build -o ../../_build/task-dispatcher ./cmd
	cd services/policy-evaluator && go build -o ../../_build/policy-evaluator ./cmd
	cd services/daytona-executor && go build -o ../../_build/daytona-executor ./cmd
	cd services/extension-controller && go build -o ../../_build/extension-controller ./cmd

build-images: ## Build container images
	docker build -f deploy/compose/Containerfile.go -t orchestack/session-scheduler --build-arg SERVICE=session-scheduler .
	docker build -f deploy/compose/Containerfile.go -t orchestack/task-dispatcher --build-arg SERVICE=task-dispatcher .
	docker build -f deploy/compose/Containerfile.go -t orchestack/policy-evaluator --build-arg SERVICE=policy-evaluator .
	docker build -f deploy/compose/Containerfile.go -t orchestack/daytona-executor --build-arg SERVICE=daytona-executor .
	docker build -f deploy/compose/Containerfile.go -t orchestack/extension-controller --build-arg SERVICE=extension-controller .
	docker build -f deploy/compose/Containerfile.python -t orchestack/loop-runner --build-arg SERVICE=loop-runner .
	docker build -f deploy/compose/Containerfile.python -t orchestack/model-router --build-arg SERVICE=model-router .
	docker build -f deploy/compose/Containerfile.python -t orchestack/budget-accounting --build-arg SERVICE=budget-accounting .
	docker build -f deploy/compose/Containerfile.python -t orchestack/memory-plane --build-arg SERVICE=memory-plane .
	docker build -f deploy/compose/Containerfile.python -t orchestack/dlp-scanner --build-arg SERVICE=dlp-scanner .

dev-up: ## Start development stack
	$(COMPOSE) up -d
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@$(COMPOSE) ps

dev-down: ## Stop development stack
	$(COMPOSE) down -v

dev-logs: ## Tail development stack logs
	$(COMPOSE) logs -f

clean: ## Clean build artifacts
	rm -rf _build/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
