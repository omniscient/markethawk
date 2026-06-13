.PHONY: demo demo-down demo-logs demo-seed

DEMO_PROJECT := markethawk_demo
DEMO_COMPOSE := docker compose -p $(DEMO_PROJECT) -f docker-compose.demo.yml
DEMO_RUN_PYTHON := $(DEMO_COMPOSE) run --rm --entrypoint python
DEMO_BACKEND_PORT ?= 8000
DEMO_FRONTEND_PORT ?= 3333
export DEMO_BACKEND_PORT
export DEMO_FRONTEND_PORT

demo:
	$(DEMO_COMPOSE) down -v --remove-orphans
	$(DEMO_COMPOSE) up -d --build postgres redis
	$(DEMO_RUN_PYTHON) backend -m alembic upgrade head
	$(DEMO_RUN_PYTHON) backend /demo/seed/seed_demo.py
	$(DEMO_COMPOSE) up -d --build backend frontend
	@echo "MarketHawk demo is starting."
	@echo "Frontend: http://localhost:$(DEMO_FRONTEND_PORT)"
	@echo "API:      http://localhost:$(DEMO_BACKEND_PORT)"
	@echo "Docs:     http://localhost:$(DEMO_BACKEND_PORT)/docs"
	@echo "Login:    demo / markethawk-demo"

demo-seed:
	$(DEMO_RUN_PYTHON) backend -m alembic upgrade head
	$(DEMO_RUN_PYTHON) backend /demo/seed/seed_demo.py

demo-logs:
	$(DEMO_COMPOSE) logs -f backend frontend

demo-down:
	$(DEMO_COMPOSE) down -v --remove-orphans
