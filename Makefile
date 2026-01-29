# =============================================================================
# Freight Forwarder Microservices - Makefile
# =============================================================================
# Quick commands:
#   make up        - Start all services
#   make down      - Stop all services
#   make logs      - View logs
#   make restart   - Restart all services
#   make status    - Check service status
# =============================================================================

.PHONY: help up down logs restart status build clean db-init migrate

# Default target
help:
	@echo "Freight Forwarder Microservices"
	@echo "================================"
	@echo ""
	@echo "Usage:"
	@echo "  make up        - Start all services (detached)"
	@echo "  make down      - Stop all services"
	@echo "  make logs      - Follow logs from all services"
	@echo "  make restart   - Restart all services"
	@echo "  make status    - Show service status"
	@echo "  make build     - Build/rebuild all images"
	@echo "  make clean     - Stop services and remove volumes"
	@echo "  make db-init   - Initialize databases"
	@echo ""
	@echo "Individual service logs:"
	@echo "  make logs-gateway"
	@echo "  make logs-auth"
	@echo "  make logs-ai"
	@echo "  make logs-rate"
	@echo ""

# =============================================================================
# Main commands
# =============================================================================

up:
	@echo "Starting all services..."
	docker-compose up -d
	@echo ""
	@echo "Services started! Access points:"
	@echo "  API Gateway:        http://localhost:8000"
	@echo "  Authentication:     http://localhost:8001"
	@echo "  AI Service:         http://localhost:8003"
	@echo "  Vector DB:          http://localhost:8004"
	@echo "  Email Service:      http://localhost:8005"
	@echo "  User Service:       http://localhost:8006"
	@echo "  Rate Sheet Service: http://localhost:8010"
	@echo "  Knowledge Graph:    http://localhost:8011"
	@echo "  Intent Classifier:  http://localhost:8012"
	@echo "  Orchestrator:       http://localhost:8013"
	@echo "  Decision Engine:    http://localhost:8014"
	@echo ""
	@echo "Databases:"
	@echo "  PostgreSQL:         localhost:5432"
	@echo "  ChromaDB:           localhost:8500"
	@echo "  ArangoDB:           http://localhost:8529"

down:
	@echo "Stopping all services..."
	docker-compose down

logs:
	docker-compose logs -f

restart:
	@echo "Restarting all services..."
	docker-compose restart

status:
	@echo "Service Status:"
	docker-compose ps

build:
	@echo "Building all images..."
	docker-compose build

clean:
	@echo "Stopping services and removing volumes..."
	docker-compose down -v
	@echo "Cleaned up!"

# =============================================================================
# Database commands
# =============================================================================

db-init:
	@echo "Initializing databases..."
	docker-compose exec postgres psql -U postgres -c "SELECT datname FROM pg_database;"

db-shell:
	docker-compose exec postgres psql -U postgres

# =============================================================================
# Individual service logs
# =============================================================================

logs-gateway:
	docker-compose logs -f api_gateway

logs-auth:
	docker-compose logs -f authentication

logs-ai:
	docker-compose logs -f ai_service

logs-vector:
	docker-compose logs -f vector_db

logs-email:
	docker-compose logs -f email_service

logs-user:
	docker-compose logs -f user_service

logs-rate:
	docker-compose logs -f rate_sheet_service

logs-graph:
	docker-compose logs -f knowledge_graph_service

logs-intent:
	docker-compose logs -f intent_classifier_service

logs-orchestrator:
	docker-compose logs -f orchestrator_service

logs-decision:
	docker-compose logs -f decision_engine

# =============================================================================
# Development helpers
# =============================================================================

shell-auth:
	docker-compose exec authentication /bin/bash

shell-rate:
	docker-compose exec rate_sheet_service /bin/bash

# Rebuild and restart a single service
rebuild-%:
	docker-compose build $*
	docker-compose up -d --no-deps $*
