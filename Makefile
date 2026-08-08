.PHONY: dev dev-frontend dev-backend build up down install

install:
	cd frontend && npm install
	cd backend && pip install -e .

dev-frontend:
	cd frontend && npm run dev

dev-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

dev:
	@echo "Run 'make dev-frontend' and 'make dev-backend' in separate terminals"

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

clean:
	docker compose down -v
	rm -rf frontend/dist frontend/node_modules backend/.venv
