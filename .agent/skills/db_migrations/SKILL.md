---
name: Database Migrations
description: Manage database schema changes using Alembic (create, apply, and check status).
---

# Database Migrations

This skill helps you manage database schema changes using Alembic. Use this when you modify SQLAlchemy models in `backend/app/models` and need to update the database schema.

## Instructions

1.  **Navigate to the backend directory**:
    Alembic commands must be run from the `backend` directory.

    ```powershell
    cd backend
    ```

    > [!IMPORTANT]
    > **Database Connection**: The `DATABASE_URL` in `.env` often points to `postgres` (the container name) for Docker. When running `alembic` from the host, you may need to override this to `localhost` if the `.env` hasn't been adjusted for local dev.
    > Example: `$env:DATABASE_URL="postgresql://postgres:stockscanner123@localhost:5432/stockscanner"; python -m alembic current`

2.  **Check Status**:
    Before making changes, check the current migration status.

    ```powershell
    python -m alembic current
    ```

3.  **Create a Migration**:
    If you have modified models, generate a new migration script. Always include a descriptive message.

    ```powershell
    python -m alembic revision --autogenerate -m "description of changes"
    ```
    *After running this, review the generated file in `backend/alembic/versions/` to verify it captures your changes correctly.*

4.  **Apply Migrations**:
    Apply pending migrations to the database.

    ```powershell
    python -m alembic upgrade head
    ```

## Troubleshooting

-   **`Target database is not up to date`**: Run `python -m alembic upgrade head` to sync your DB before creating new migrations.
-   **`Can't locate revision`**: You might be missing a migration file locally that the DB expects. Check git history.
-   **Connection Refused**: Ensure the database is running via Docker.
