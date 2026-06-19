# LLM Feature Flags, Provider Config, and Usage Guardrails Design

**Date:** 2026-06-19
**Issue:** #472
**Parent Epic:** #450 (Optional LLM Narrative and Semantic Intelligence)
**Status:** Pending review

---

## Overview

Issue #472 adds the infrastructure layer for optional LLM-powered features in MarketHawk. It is the gating ticket for Epic 3 of the scanner explainability initiative — all downstream features (narrative generation, embeddings, semantic search, analyst Q&A) will import from the config and interface defined here.

The design constraint from the parent epic is absolute: **MarketHawk must remain fully explainable and insight-rich without any LLM provider configured.** This ticket enforces that constraint by making `LLM_ENABLED: bool = False` the default and requiring every LLM call site to check the guardrail before proceeding.

This ticket covers:
- Environment-variable config for LLM settings (extending `Settings`)
- A `BaseLLMProvider` ABC that all concrete providers (Anthropic, OpenAI, etc.) will implement
- A `llm_feature_enabled(area)` helper on `Settings` for two-level flag checks
- Tests for disabled-by-default behavior and config parsing

This ticket does **not** cover:
- Any concrete LLM provider implementation (Anthropic SDK, OpenAI SDK)
- Circuit-breaker wiring (belongs with the first call site in ticket 2)
- Embedding storage or retrieval (Epic 3 tickets 6–7)
- Frontend UI toggles (Epic 3 ticket 11)

---

## Requirements

From the issue acceptance criteria and Q&A:

1. All LLM features are disabled by default (`LLM_ENABLED: bool = False`).
2. A master kill-switch (`LLM_ENABLED`) governs all LLM activity; individual per-feature-area flags are only checked when the master is on.
3. Six feature areas have individual flags, all defaulting to `False`: `narratives`, `alert_copy`, `post_mortems`, `embeddings`, `semantic_search`, `qa`.
4. Provider and model settings are explicit and configured independently of one another (`LLM_PROVIDER`, `LLM_MODEL`). No vendor is hardcoded.
5. Usage guardrails are configured as env vars: max tokens, timeout, max retries, retry delay.
6. A `BaseLLMProvider` ABC defines the interface that all downstream concrete providers implement. It includes `generate_text`, `embed_text`, and a concrete `retry_with_guardrails` helper.
7. When `LLM_ENABLED=True`, a validator enforces that `LLM_PROVIDER` and `LLM_MODEL` are non-empty.
8. Tests cover: disabled-by-default behavior, config parsing, the `llm_feature_enabled` helper (true/false/invalid-area paths), guardrail field parsing, and the validator.

---

## Architecture / Approach

### 1. Settings extension — `backend/app/core/config.py`

Add a new `# ── LLM / AI Provider` block to `Settings`. All fields default to the safe/disabled state:

```python
# ── LLM / AI Provider ─────────────────────────────────────────────────────
# Master kill-switch. When False, every settings.llm_feature_enabled() call
# returns False and no LLM API calls are made anywhere in the application.
LLM_ENABLED: bool = False

# Provider selector. Identifies the concrete BaseLLMProvider subclass to use.
# Must be non-empty when LLM_ENABLED=True. Values are defined by concrete
# provider modules added in downstream tickets (e.g. "anthropic", "openai").
LLM_PROVIDER: str = ""

# Model identifier forwarded to the provider (e.g. "claude-sonnet-4-6").
# Must be non-empty when LLM_ENABLED=True.
LLM_MODEL: str = ""

# Generic API key forwarded to the configured provider (repr=False — never logged).
# Concrete provider modules may define their own named env var in addition to this.
LLM_API_KEY: str = Field(default="", repr=False)

# Usage guardrails ──────────────────────────────────────────────────────────
# Maximum tokens the provider may generate per request.
LLM_MAX_TOKENS: int = 1024
# Per-request wall-clock timeout in seconds.
LLM_TIMEOUT_SECONDS: float = 30.0
# Maximum number of retries after a retryable failure (not counting the first attempt).
LLM_MAX_RETRIES: int = 2
# Seconds to wait between retry attempts.
LLM_RETRY_DELAY_SECONDS: float = 1.0

# Per-feature-area flags — each must be True AND LLM_ENABLED must be True
# for any LLM call in that area to proceed. Use settings.llm_feature_enabled().
LLM_NARRATIVES_ENABLED: bool = False      # Epic 3 tickets 2–3
LLM_ALERT_COPY_ENABLED: bool = False      # Epic 3 ticket 4
LLM_POST_MORTEMS_ENABLED: bool = False    # Epic 3 ticket 5
LLM_EMBEDDINGS_ENABLED: bool = False      # Epic 3 tickets 6–7
LLM_SEMANTIC_SEARCH_ENABLED: bool = False # Epic 3 ticket 8
LLM_QA_ENABLED: bool = False             # Epic 3 ticket 9
```

Cross-field validator (add after existing validators):

```python
@model_validator(mode="after")
def _validate_llm_config(self) -> "Settings":
    if self.LLM_ENABLED:
        if not self.LLM_PROVIDER:
            raise ValueError(
                "LLM_PROVIDER must be set when LLM_ENABLED=True. "
                "Example: LLM_PROVIDER=anthropic"
            )
        if not self.LLM_MODEL:
            raise ValueError(
                "LLM_MODEL must be set when LLM_ENABLED=True. "
                "Example: LLM_MODEL=claude-sonnet-4-6"
            )
    return self
```

Helper method on `Settings` (add as an instance method):

```python
_LLM_FEATURE_AREAS = frozenset({
    "narratives", "alert_copy", "post_mortems",
    "embeddings", "semantic_search", "qa",
})

def llm_feature_enabled(self, area: str) -> bool:
    """Return True only if LLM_ENABLED is on AND this feature area's flag is on."""
    if area not in self._LLM_FEATURE_AREAS:
        raise ValueError(
            f"Unknown LLM feature area: {area!r}. "
            f"Valid areas: {sorted(self._LLM_FEATURE_AREAS)}"
        )
    flag_map = {
        "narratives": self.LLM_NARRATIVES_ENABLED,
        "alert_copy": self.LLM_ALERT_COPY_ENABLED,
        "post_mortems": self.LLM_POST_MORTEMS_ENABLED,
        "embeddings": self.LLM_EMBEDDINGS_ENABLED,
        "semantic_search": self.LLM_SEMANTIC_SEARCH_ENABLED,
        "qa": self.LLM_QA_ENABLED,
    }
    return self.LLM_ENABLED and flag_map[area]
```

Downstream call sites use this exclusively:

```python
if not settings.llm_feature_enabled("narratives"):
    return None  # LLM disabled — return deterministic result
```

### 2. BaseLLMProvider ABC — `backend/app/providers/llm_base.py`

Mirrors the existing `BaseDataProvider` ABC pattern:

```python
from abc import ABC, abstractmethod
from typing import Any, Callable


class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.

    Concrete subclasses (added in downstream tickets) implement generate_text
    and embed_text. The retry_with_guardrails helper is provided here so all
    providers get consistent retry behaviour without reimplementing it.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier matching the LLM_PROVIDER config value (e.g. 'anthropic')."""
        ...

    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """Return (available, status_message). Called before routing requests."""
        ...

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        """
        Generate text from a prompt.

        Args:
            prompt: The input prompt string.
            max_tokens: Override LLM_MAX_TOKENS for this call. None = use settings default.
            timeout: Override LLM_TIMEOUT_SECONDS for this call. None = use settings default.

        Returns:
            Generated text string.

        Raises:
            LLMProviderError: on non-retryable failure.
            LLMTimeoutError: when the request exceeds the timeout.
        """
        ...

    @abstractmethod
    def embed_text(
        self,
        text: str,
        timeout: float | None = None,
    ) -> list[float]:
        """
        Embed text into a float vector.

        Args:
            text: The input text to embed.
            timeout: Override LLM_TIMEOUT_SECONDS for this call. None = use settings default.

        Returns:
            Embedding vector as a list of floats.
        """
        ...

    def retry_with_guardrails(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Retry fn up to LLM_MAX_RETRIES times with LLM_RETRY_DELAY_SECONDS between attempts.

        Raises the last exception if all retries are exhausted.
        """
        import time

        from app.core.config import settings

        last_exc: Exception | None = None
        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < settings.LLM_MAX_RETRIES:
                    time.sleep(settings.LLM_RETRY_DELAY_SECONDS)
        raise last_exc  # type: ignore[misc]
```

Two provider-specific exception types (added in the same file):

```python
class LLMProviderError(Exception):
    """Non-retryable error from an LLM provider."""
    def __init__(self, message: str, is_retryable: bool = False) -> None:
        super().__init__(message)
        self.is_retryable = is_retryable

class LLMTimeoutError(LLMProviderError):
    """Request to LLM provider exceeded the configured timeout."""
```

### 3. Providers package — `backend/app/providers/__init__.py`

Export `BaseLLMProvider` and the two exception types. No factory registration yet — an `LLMProviderFactory` (parallel to `DataProviderFactory`) is added when the first concrete provider arrives in downstream ticket 2.

```python
from app.providers.llm_base import BaseLLMProvider, LLMProviderError, LLMTimeoutError

__all__ = [
    # ... existing exports ...
    "BaseLLMProvider",
    "LLMProviderError",
    "LLMTimeoutError",
]
```

### 4. Tests — `backend/tests/test_llm_config.py`

Following the pattern from `test_settings.py`:

```
TestLLMDefaults
  test_llm_disabled_by_default
  test_all_feature_areas_disabled_by_default
  test_llm_provider_empty_by_default
  test_llm_model_empty_by_default

TestLLMFeatureEnabledHelper
  test_feature_disabled_when_master_off
  test_feature_disabled_when_only_area_on_but_master_off
  test_feature_enabled_when_both_master_and_area_on
  test_feature_invalid_area_raises_value_error
  test_all_six_areas_reachable

TestLLMGuardrailFields
  test_guardrail_defaults
  test_max_tokens_overridable
  test_timeout_overridable
  test_max_retries_overridable
  test_retry_delay_overridable

TestLLMEnabledValidator
  test_enabled_true_without_provider_raises
  test_enabled_true_without_model_raises
  test_enabled_true_with_provider_and_model_succeeds
```

All tests construct `Settings(DATABASE_URL=..., POLYGON_API_KEY=..., ...)` directly, following the existing `test_settings.py` pattern. No `.env` file required.

---

## Alternatives Considered

### Alt 1: Include first concrete Anthropic provider in this ticket

Rejected. This ticket is the infrastructure layer; downstream ticket 2 ("Add cached scanner event narrative generation") is the first to make real LLM API calls. Pulling the Anthropic SDK in here adds a new dependency before any call site exists. The circuit-breaker wiring (`LLM_BREAKER` singleton) belongs alongside the first actual usage, mirroring how `POLYGON_BREAKER` and `IBKR_BREAKER` in `circuit_breakers.py` live with their respective providers.

### Alt 2: Runtime-editable DB config table for feature flags

Rejected. No DB-backed config table exists anywhere in the codebase. Every comparable toggle (`LIVE_WEBSOCKET_ENABLED`, `RATE_LIMITING_ENABLED`, `DOCS_ENABLED`) uses env vars. The AC says "can be enabled by config" — not "without restart." A runtime toggle is a separate UI/ops concern and would be a distinct issue.

### Alt 3: CSV allowlist for feature areas (`LLM_ALLOWED_FEATURES: str = ""`)

Rejected. No precedent in `Settings` — the only list-type field (`CORS_ORIGINS`) uses a JSON array, not comma-split, so a CSV allowlist would introduce a novel parsing convention plus a validator to reject unknown area names. Individual boolean flags follow the existing pattern (`LIVE_WEBSOCKET_ENABLED: bool = True`) and get free pydantic type validation.

---

## Open Questions (non-blocking)

1. **Per-provider API key naming**: Should `LLM_API_KEY` be the canonical env var for all providers, or should each concrete provider define its own (e.g., `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)? This is a naming decision deferred to the first concrete provider ticket. `LLM_API_KEY` exists here as a generic placeholder.

2. **Async support in `retry_with_guardrails`**: The current implementation is synchronous (`time.sleep`). If the first concrete provider uses `async`/`await`, `BaseLLMProvider` will need an `async_retry_with_guardrails` variant. Deferred to ticket 2 once the async/sync shape of the first provider is known.

---

## Assumptions

- **A** — The `BaseLLMProvider` ABC is sufficient for ticket 2 to add a concrete provider without modifying `config.py` (aside from adding provider-specific fields like the API key).
- **B** — `retry_with_guardrails` is sync-only in this ticket. Concrete providers that need async retries will extend the base class in their own ticket.
- **C** — The `_validate_llm_config` model_validator (enforcing non-empty provider/model when enabled) is the right strictness level. Individual feature area flags do not need cross-field validation against one another.
- **D** — `conftest.py` does not need changes: `LLM_ENABLED` defaults to `False`, so existing tests that construct `Settings(DATABASE_URL=..., POLYGON_API_KEY=...)` continue to work without setting any LLM env vars.
- **E** — `LLM_MAX_TOKENS=1024` is a conservative default appropriate for narrative-length text. Embedding calls typically do not use this parameter; concrete embedding providers may ignore it or use a separate tokens-per-request limit.
