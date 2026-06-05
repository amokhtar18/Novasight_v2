# Analytica — developer convenience targets.
# The local stack reads the repo-root .env (the SAME file the backend reads), passed to
# Compose with --env-file so it is found regardless of the compose file's directory.

COMPOSE := docker compose --env-file .env -f infra/compose/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help env up down stop logs ps health clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example — edit secrets before any real use.")

up: env ## Start the local stack (Postgres, Redis, MinIO, ClickHouse) detached
	$(COMPOSE) up -d

down: ## Stop and remove the stack containers (keeps named volumes / data)
	$(COMPOSE) down

stop: ## Stop the stack without removing containers
	$(COMPOSE) stop

ps: ## Show stack container status
	$(COMPOSE) ps

logs: ## Tail logs for all services
	$(COMPOSE) logs -f

health: ## Probe each service's health from the host
	@bash infra/compose/healthcheck.sh

clean: ## Stop the stack AND delete its data volumes (destructive)
	$(COMPOSE) down -v
