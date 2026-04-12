---
name: Database Migrations
description: Manage database schema changes using Alembic — create, apply, check status, and roll back migrations.
---

# Database Migrations

Alembic manages all schema changes. Migration scripts live in `backend/alembic/versions/`. Never modify the database schema directly — always go through Alembic.

## Workflow

### 1. Modify the SQLAlchemy model

Edit or create a model in `backend/app/models/`. If creating a new model file, import it in `backend/app/models/__init__.py` so Alembic's autogenerate can detect it.

### 2. Check current state

```bash
docker-compose exec backend python -m alembic current
```

### 3. Generate the migration script

```bash
docker-compose exec backend python -m alembic revision --autogenerate -m "describe_the_change"
```

Always review the generated file in `backend/alembic/versions/` before applying. Autogenerate can miss some changes (e.g., renamed columns, custom constraints).

### 4. Apply the migration

```bash
docker-compose exec backend python -m alembic upgrade head
```

### 5. Verify

```bash
docker-compose exec backend python -m alembic current
# Should show the new revision hash with (head)
```

## Other Useful Commands

```bash
# Show pending migrations (what would be applied)
docker-compose exec backend python -m alembic upgrade head --sql

# Roll back one migration
docker-compose exec backend python -m alembic downgrade -1

# Roll back to a specific revision
docker-compose exec backend python -m alembic downgrade <revision_id>

# Show full migration history
docker-compose exec backend python -m alembic history --verbose

# Show divergence between DB state and migration files
docker-compose exec backend python -m alembic heads
```

## Running from the Host (without Docker)

The `DATABASE_URL` in `.env` points to `postgres` (the container hostname), which is not resolvable from the host. Override it to `localhost`:

```bash
cd backend
DATABASE_URL="postgresql://postgres:yourpassword@localhost:5432/stockscanner" python -m alembic current
```

## Troubleshooting

**`Target database is not up to date`**
Run `python -m alembic upgrade head` to bring the DB to the latest revision before generating a new one.

**`Can't locate revision`**
The DB references a revision that doesn't exist locally. Check `git log -- backend/alembic/versions/` for the missing file.

**`Connection refused`**
The PostgreSQL container isn't running. Start it with `docker-compose up -d postgres` and wait for its healthcheck to pass.

**Autogenerate produces an empty migration**
Alembic didn't detect the change. Verify the model is imported in `backend/app/models/__init__.py`.
