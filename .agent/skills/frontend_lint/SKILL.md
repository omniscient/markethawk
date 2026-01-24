---
name: Frontend Lint
description: Check frontend code quality using ESLint.
---

# Frontend Lint

This skill runs the frontend linter (ESLint) to catch syntax errors, type issues, and code style violations. Run this after modifying any files in `frontend/src`.

## Instructions

1.  **Navigate to the frontend directory**:

    ```powershell
    cd frontend
    ```

2.  **Run the Linter**:

    ```powershell
    npm run lint
    ```

## Interpreting Output

-   **No output or "Clean"**: Code is good!
-   **Warnings**: Fix them if possible, but they won't break the build (usually).
-   **Errors**: MUST be fixed. The build will likely fail.

## Fix Command
Some linting errors can be auto-fixed:

```powershell
npm run lint -- --fix
```
