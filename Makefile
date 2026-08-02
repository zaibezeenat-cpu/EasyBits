.PHONY: bootstrap dev-backend dev-frontend test \
        build up down restart logs ps deploy

bootstrap:
	bash scripts/bootstrap.sh

dev-backend:
	cd backend && uvicorn app.main:app --reload

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && pytest tests/unit tests/integration

# --- Production (Docker) ----------------------------------------------------
# Requires backend/.env to exist with DOMAIN set to the real hostname.
build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

# One-shot deploy: pull latest, rebuild, and roll the stack. Safe to re-run.
deploy:
	git pull --ff-only
	docker compose build
	docker compose up -d
	docker compose ps
