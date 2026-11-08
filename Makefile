.PHONY: setup up down logs migrate revision test lint fmt psql

setup:          ## cria .env a partir do exemplo
	@test -f .env || cp .env.example .env && echo ".env pronto: edite os segredos"

up:             ## sobe toda a stack
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api n8n

migrate:        ## aplica migrations
	docker compose exec api alembic upgrade head

revision:       ## nova migration: make revision m="descricao"
	docker compose exec api alembic revision --autogenerate -m "$(m)"

test:           ## testes (local, precisa de venv com requirements-dev)
	cd api && pytest -q

lint:
	cd api && ruff check .

fmt:
	cd api && ruff check --fix . && ruff format .

psql:
	docker compose exec postgres sh -c 'psql -U $$POSTGRES_USER -d $$POSTGRES_DB'
