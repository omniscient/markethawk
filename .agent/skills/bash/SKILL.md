---
name: Bash (Git Bash on Windows)
description: Shell patterns for this repository. The environment runs bash (Git Bash) on Windows 11. Use Unix syntax throughout.
---

# Bash — Git Bash on Windows

This project runs in **bash** (Git Bash), not PowerShell. Use Unix shell syntax in all commands.

## Path Conventions

Use forward slashes. Git Bash translates them for Windows automatically.

```bash
cd /c/git/trading/OKComputer_Custom\ Stock\ Scanner\ System
```

Or use the absolute Windows path with forward slashes:
```bash
cd "C:/git/trading/OKComputer_Custom Stock Scanner System"
```

## Command Chaining

`&&` and `||` work normally in bash:

```bash
cd backend && python -m pytest
docker-compose down && docker-compose up -d
```

## Multi-Line Commands

Use backslash continuation:

```bash
docker exec stockscanner-api \
  python -m alembic revision \
  --autogenerate \
  -m "add_asset_class_column"
```

## Environment Variables

```bash
# Read
echo $POLYGON_API_KEY

# Set for current session
export POLYGON_API_KEY=abc123

# Set inline for a single command
DATABASE_URL="postgresql://postgres:pw@localhost:5432/stockscanner" python -m alembic current
```

## Useful Patterns

### Find text in Python files
```bash
grep -r "calculate_day_metrics" backend/app/
```

### Find a file by name
```bash
find backend/app -name "scanner.py"
```

### Tail logs from a running container
```bash
docker-compose logs -f backend
docker-compose logs -f celery-worker | grep ERROR
```

### Run a command inside a container
```bash
docker-compose exec backend bash
docker-compose exec backend python -m alembic current
docker-compose exec postgres psql -U postgres -d stockscanner
```

### HTTP requests
```bash
curl -s http://localhost:8000/health | python -m json.tool
curl -X POST http://localhost:8000/api/scanner/run
```

### JSON parsing
```bash
curl -s http://localhost:8000/health | python -m json.tool
# Or with python inline:
python -c "import json, sys; d = json.load(sys.stdin); print(d['status'])"
```

## Windows-Specific Notes

- `netstat` works in Git Bash but some flags differ from Linux. Use `netstat -ano | grep :8000` to check port usage.
- Docker Desktop must be running for any `docker` or `docker-compose` commands to work.
- If a script has Windows line endings (`\r\n`), run `dos2unix script.sh` before executing.
- `python` and `python3` both resolve to the same interpreter. Prefer `python` in this project (matches Dockerfile).
