.PHONY: config build up down logs test lint typecheck architecture quality

config:
	docker compose config

build:
	docker compose build

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs --tail=200

test:
	docker compose run --rm backend pytest

lint:
	docker compose run --rm backend ruff check backend scripts
	docker compose run --rm frontend npm run lint:frontend

typecheck:
	docker compose run --rm backend mypy backend/src scripts/check_architecture.py
	docker compose run --rm frontend npm run typecheck:frontend

architecture:
	docker compose run --rm backend python scripts/check_architecture.py

quality: lint typecheck test architecture

