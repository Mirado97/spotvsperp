.PHONY: help build up down logs test lint fmt shell-backend

COMPOSE = docker compose
COMPOSE_PROD = $(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  build          Build all Docker images"
	@echo "  up             Start the full stack (dev)"
	@echo "  down           Stop and remove containers"
	@echo "  logs           Follow logs for all services"
	@echo "  test           Run unit tests"
	@echo "  lint           Run ruff linter"
	@echo "  fmt            Auto-format with ruff"
	@echo "  shell-backend  Open a shell in the backend container"
	@echo "  prod-up        Start the production stack"
	@echo "  prod-down      Stop the production stack"

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

test:
	pytest tests/ -v --tb=short

lint:
	ruff check src/ tests/

fmt:
	ruff format src/ tests/

shell-backend:
	$(COMPOSE) exec backend sh

# ── Production ────────────────────────────────────────────────────────────────

prod-up:
	$(COMPOSE_PROD) up -d

prod-down:
	$(COMPOSE_PROD) down

prod-logs:
	$(COMPOSE_PROD) logs -f

# ── Kubernetes ────────────────────────────────────────────────────────────────

k8s-apply:
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/secrets.yaml
	kubectl apply -f k8s/postgres-statefulset.yaml
	kubectl apply -f k8s/redis-deployment.yaml
	kubectl apply -f k8s/backend-deployment.yaml
	kubectl apply -f k8s/frontend-deployment.yaml

k8s-delete:
	kubectl delete namespace cexvscex
