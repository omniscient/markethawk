---
name: Backend Tests
description: Run the backend test suite using pytest to verify API and database logic.
---

# Backend Tests

This skill allows you to run the backend test suite. Use this when you modify backend code (API endpoints, services, schemas) and want to ensure you haven't introduced regressions.

## Instructions

1.  **Navigate to the backend directory**:
    The tests must be run from the `backend` directory where `pytest.ini` (or configuration) and `tests/` folder are located.
    Current Root: `c:\git\trading\OKComputer_Custom Stock Scanner System`
    Target: `backend`

2.  **Run the tests**:
    Use `python -m pytest` to run all tests.

    ```powershell
    cd backend
    python -m pytest
    ```

## Common Options

-   **Run a specific test file**:
    ```powershell
    python -m pytest tests/test_specific_file.py
    ```

-   **Run a specific test function**:
    ```powershell
    python -m pytest tests/test_file.py::test_function_name
    ```

-   **Fail fast (stop on first error)**:
    ```powershell
    python -m pytest -x
    ```

## error Handling

-   **`ModuleNotFoundError`**: Ensure you are in the `backend` directory and that dependencies are installed.
-   **Database connection errors**: Ensure the database container is running (`docker compose up -d db`).
