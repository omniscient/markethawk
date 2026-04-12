---
name: Backend Tests
description: Run the backend test suite using pytest to verify API and database logic.
---

# Backend Tests

Run this after modifying any backend code (routers, services, models, schemas) to check for regressions.

## Run All Tests

```bash
docker-compose exec backend python -m pytest
```

## Common Options

```bash
# Run a specific test file
docker-compose exec backend python -m pytest tests/api/test_scanner.py

# Run a specific test function
docker-compose exec backend python -m pytest tests/api/test_scanner.py::test_run_scan

# Stop on first failure
docker-compose exec backend python -m pytest -x

# Verbose output
docker-compose exec backend python -m pytest -v

# With coverage report
docker-compose exec backend python -m pytest --cov
```

## Running from the Host

With a virtual environment activated and `DATABASE_URL` pointing to `localhost`:

```bash
cd backend
source venv/bin/activate
DATABASE_URL="postgresql://postgres:yourpassword@localhost:5432/stockscanner" python -m pytest
```

## Troubleshooting

**`ModuleNotFoundError`** — Run from inside the container (`docker-compose exec backend`) or ensure the virtual environment is activated and dependencies are installed (`pip install -r requirements.txt`).

**Database connection errors** — The `postgres` container must be running and healthy. Check with `docker-compose ps`.

**Import errors after adding a new model** — Ensure the model is imported in `backend/app/models/__init__.py`.
