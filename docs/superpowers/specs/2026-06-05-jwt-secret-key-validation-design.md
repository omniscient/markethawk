# JWT_SECRET_KEY Startup Validation

> Tracking issue: [#190](https://github.com/omniscient/markethawk/issues/190)

## Overview

`JWT_SECRET_KEY: str = ""` in `backend/app/core/config.py:53` has no `field_validator`.
`backend/app/core/auth.py:31` signs every access token with it, and `main.py:266-270`
validates incoming tokens against it. A deploy that omits the env var silently signs and
verifies tokens with `""` — anyone can forge a valid `access_token` for any user UUID.
There is no startup guard to prevent this.

## Requirements

- `JWT_SECRET_KEY` with `len < 32` (including the empty string `""`) must raise `ValidationError`
  at `Settings` instantiation time, causing a clean startup failure.
- The error message must be actionable: it must state the minimum length and include a
  one-liner for generating a compliant key with `secrets.token_urlsafe`.
- `.env.example` must be updated so that the key is documented as mandatory with a generation hint.
- One test must assert that `Settings(JWT_SECRET_KEY="")` raises `ValidationError`.
- One test must assert that `Settings(JWT_SECRET_KEY="short")` (< 32 chars) raises `ValidationError`.
- One test must assert that a key of exactly 32 characters is accepted.
- No other behaviour changes — auth logic, middleware, and token creation are untouched.

## Architecture / Approach

**Add a `field_validator` on `JWT_SECRET_KEY`; keep the `= ""` default.**

```python
# backend/app/core/config.py
JWT_SECRET_KEY: str = ""   # unchanged field declaration

@field_validator("JWT_SECRET_KEY")
@classmethod
def validate_jwt_secret_key(cls, v: str) -> str:
    if len(v) < 32:
        raise ValueError(
            "JWT_SECRET_KEY must be a strong secret of at least 32 characters. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    return v
```

The validator is placed after the existing `normalize_environment` validator to maintain
alphabetical grouping by subject. The minimum length of 32 characters is hardcoded; it
covers both the missing env var (empty string) and weak-key cases with one message.

**`.env.example` change:**

```
# Required — generate with: python -c 'import secrets; print(secrets.token_urlsafe(48))'
JWT_SECRET_KEY=<generate-before-deploy>
```

**Test location:** `backend/tests/core/test_config.py` (alongside the existing pool-defaults tests,
which follow the same `Settings(...)` instantiation pattern).

No migration, no schema change, no Docker change needed.

## Alternatives Considered

### Alternative A — Remove the `= ""` default (make it required at field level)

Removing the default would cause pydantic to raise a generic `MissingField` error when the
env var is unset, and a `ValidationError` only when a key is set but weak. This splits the
failure across two error types with different messages, which is harder to communicate to
operators. The issue acceptance criteria specifically says "instantiating `Settings` with an
empty `JWT_SECRET_KEY` raises `ValidationError`", which implies the validator (not field
requiredness) is the primary gate. Rejected in favour of the single-validator approach above.

### Alternative B — Startup check in `main.py` lifespan event

Adding a check in the FastAPI `lifespan` function would also catch the bad key at startup.
However, config validation belongs at the `Settings` layer — it is the correct abstraction
boundary, and it catches the bad key even in tests and CLI scripts that import `settings`
without going through the lifespan. Rejected as wrong layer.

## Assumptions

- The existing test suite runs with a `.env` file or environment variables that supply a valid
  (≥ 32 char) `JWT_SECRET_KEY`, so adding the validator will not break the existing test
  collection. If tests instantiate `Settings()` bare without supplying `JWT_SECRET_KEY`, they
  will start failing — this would be a pre-existing misconfiguration, not a regression.
- 32 characters is the minimum acceptable length (stated in issue). No future configurability
  is required (YAGNI).
- The `= ""` default value itself need not change — it is only a syntactic catch for a
  missing env var; the validator turns it into a clean error.

## Open Questions

None — all acceptance criteria are unambiguous.
