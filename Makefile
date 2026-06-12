.PHONY: demo demo-down demo-logs demo-seed

DEMO_PROJECT := markethawk_demo
DEMO_COMPOSE := docker compose -p $(DEMO_PROJECT) -f docker-compose.demo.yml
DEMO_RUN_BACKEND := $(DEMO_COMPOSE) run --rm --entrypoint ""

demo:
	$(DEMO_COMPOSE) down -v --remove-orphans
	$(DEMO_COMPOSE) up -d --build postgres redis
	$(DEMO_RUN_BACKEND) backend python -m alembic upgrade head
	$(DEMO_RUN_BACKEND) backend python /demo/seed/seed_demo.py
	$(DEMO_COMPOSE) up -d --build backend frontend
	@echo "MarketHawk demo is starting."
	@echo "Frontend: http://localhost:3333"
	@echo "API:      http://localhost:8000"
	@echo "Docs:     http://localhost:8000/docs"
	@echo "Login:    demo / markethawk-demo"

demo-seed:
	$(DEMO_RUN_BACKEND) backend python -m alembic upgrade head
	$(DEMO_RUN_BACKEND) backend python /demo/seed/seed_demo.py

demo-logs:
	$(DEMO_COMPOSE) logs -f backend frontend

demo-down:
	$(DEMO_COMPOSE) down -v --remove-orphans
