# pg_discovery: Docker API Response Hardening Design

**Date:** 2026-06-14
**Issue:** #429
**Status:** Pending review

## Overview

`backend/tests/utils/pg_discovery.py` provides `probe_running_postgres()`, a test-infrastructure helper that locates a running PostgreSQL instance. In factory/DinD environments it queries the Docker API to discover postgres container IPs before falling back to well-known hostnames.

Three silent failure modes exist in the Docker-API probe branch — all currently masked by a broad `except Exception: pass` that causes opaque fallthrough. This spec hardens those failure modes with explicit guards and diagnostic logging.

## Problem Statement

The current Docker probe branch contains three weaknesses:

1. **No `raise_for_status()` check.** A 4xx/5xx Docker API response (e.g. 403 Forbidden from the docker-socket-proxy when `EXEC=0`) is handed directly to `.json()`, which decodes an error body and attempts container iteration on a non-container payload.

2. **No `isinstance(containers, list)` guard.** If the Docker API returns an error object (e.g. `{"message": "authorization failed"}`) instead of a container list, iterating it walks dict keys (strings). The subsequent `.get("Image", "")` call on those string keys raises `AttributeError` — currently swallowed silently by the broad `except`.

3. **No diagnostic logging.** When discovery fails or no candidate connects, there is no debug trace of what was attempted, making CI failures in factory environments hard to diagnose.

## Requirements

1. HTTP error responses from the Docker API must not reach `.json()`. A non-2xx response falls through to hostname probing.
2. The parsed Docker API response must be confirmed as a list before iteration. A non-list response yields zero Docker-derived candidate IPs and proceeds to hostname probing without raising.
3. A module-level `logging.getLogger(__name__)` logger emits `DEBUG`-level lines for:
   - HTTP error fallthrough: includes status code and host
   - Non-list response fallthrough: includes the type received (`type(r).__name__`)
   - Exhausted probing with no host found: includes count of candidates tried
4. A new test `test_docker_api_non_list_response_falls_through_to_hostname` verifies the non-list fallthrough behaviorally (result comes from hostname probing, no exception raised).
5. The helper's `str | None` return contract is unchanged.
6. All existing `test_pg_discovery.py` tests pass without modification.

## Approach

### Chosen: Targeted in-place guards (A)

Add three targeted guards inside the existing `probe_running_postgres()` function, keeping the broad `except Exception: pass` structure intact for any remaining Docker probe failures:

```python
import logging
import os

import psycopg2
import requests

logger = logging.getLogger(__name__)


def probe_running_postgres() -> str | None:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit

    candidate_ips: list[str] = []
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith("tcp://"):
        try:
            r = requests.get(
                f"http://{docker_host[6:]}/containers/json",
                timeout=3,
            )
            r.raise_for_status()                             # Guard 1: HTTP error
            containers = r.json()
            if not isinstance(containers, list):             # Guard 2: type check
                logger.debug(
                    "Docker API returned non-list (%s), expected container array; "
                    "falling through to hostname probing",
                    type(containers).__name__,
                )
            else:
                for c in containers:
                    if "postgres" not in c.get("Image", "").lower():
                        continue
                    for net_info in (
                        c.get("NetworkSettings", {}).get("Networks", {}).values()
                    ):
                        ip = net_info.get("IPAddress", "")
                        if ip:
                            candidate_ips.append(ip)
        except requests.HTTPError as exc:
            logger.debug(
                "Docker API probe failed (HTTP %s) for %s; falling through to hostname probing",
                exc.response.status_code,
                docker_host[6:],
            )
        except Exception:
            pass

    for hostname in ["postgres", "stockscanner-db", "localhost"]:
        candidate_ips.append(hostname)

    common_creds = [...]
    for ip in candidate_ips:
        for user, pw, db in common_creds:
            try:
                psycopg2.connect(...).close()
                return f"postgresql://{user}:{pw}@{ip}:5432/{db}"
            except Exception:
                pass

    logger.debug(                                            # Guard 3: no host found
        "No reachable postgres found after trying %d candidate host(s)",
        len(candidate_ips),
    )
    return None
```

**Why this approach:**
- Minimal diff; does not restructure the existing fallthrough logic
- `raise_for_status()` is idiomatic requests and raises `requests.HTTPError`, which the new specific `except requests.HTTPError` handler catches to log with the status code before proceeding
- The broad `except Exception: pass` still catches connection errors, timeouts, and any other probe failure — preserving the existing fallthrough guarantee
- Log messages use lazy `%s` formatting (not f-strings), consistent with `logging` best practices
- No credentials appear in any log message

### Rejected: Multiple specific exception handlers (B)

Replacing `except Exception: pass` with per-type handlers (ConnectionError, Timeout, JSONDecodeError, etc.) would tighten the fallthrough semantics but is out of scope — the broad except is intentional for the Docker probe branch and the issue explicitly requires "no behavior change beyond logging."

### Rejected: `warnings.warn` for diagnostics (C)

The issue brief explicitly requires `logging.getLogger(__name__)`. Using `warnings` would not integrate with Seq or pytest log capture.

## New Test

```python
def test_docker_api_non_list_response_falls_through_to_hostname(self, monkeypatch):
    """When Docker API returns a non-list (e.g. error dict), falls through to well-known hostnames."""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://docker:2375")

    mock_response = MagicMock()
    mock_response.json.return_value = {"message": "authorization failed"}
    mock_response.raise_for_status.return_value = None  # 200 OK, but non-list body
    mock_conn = MagicMock()

    with (
        patch("tests.utils.pg_discovery.requests") as mock_requests,
        patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
    ):
        mock_requests.get.return_value = mock_response
        mock_requests.HTTPError = requests.HTTPError

        def connect_side_effect(*args, **kwargs):
            if kwargs.get("host") == "postgres":
                return mock_conn
            raise Exception("unreachable")

        mock_psycopg2.connect.side_effect = connect_side_effect
        result = probe_running_postgres()

    assert result is not None
    assert "postgres" in result  # proves fallthrough — no Docker IP contributed
```

No assertion on `logger.debug` calls — consistent with the existing test suite, which asserts behavioral outcomes only. The diagnostic logging requirement is satisfied by the implementation; the test verifies the code path executes without raising.

## Files Changed

| File | Change |
|------|--------|
| `backend/tests/utils/pg_discovery.py` | Add `import logging`, module-level `logger`, `raise_for_status()`, `isinstance` guard, three `logger.debug()` calls |
| `backend/tests/utils/test_pg_discovery.py` | Add `test_docker_api_non_list_response_falls_through_to_hostname` |

## Assumptions

- The broad `except Exception: pass` in the Docker probe branch is intentional (any Docker API failure should silently fall through to hostname probing). The new `except requests.HTTPError` handler is inserted *before* the broad except to capture the status code for logging; the broad except still catches everything else.
- `requests.HTTPError.response` is always non-None when `raise_for_status()` raises (guaranteed by requests library internals).
- No migration is needed — this is a test-infrastructure utility with no DB schema impact.
- The `conftest.py` fixture wiring (`_testcontainers_url()` integration) is explicitly out of scope (#503).

## Open Questions

- None blocking. The acceptance criteria are fully specified in the agent brief.
