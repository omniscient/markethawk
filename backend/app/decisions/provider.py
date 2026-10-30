"""DecisionProvider — the provider-neutral answerer protocol and its error taxonomy.

Deliberately unrelated to ``app.providers.base.BaseDataProvider`` (a market-data ABC
wired into the broker/vendor registry).
"""

from __future__ import annotations

from typing import Annotated, Protocol, runtime_checkable

from pydantic import Field

from app.decisions.request import DecisionRequest
from app.decisions.result import DecisionResult
from app.decisions.schema import MAX_QUESTIONS, DecisionSchema, FrozenContract


class DecisionProviderCapabilities(FrozenContract):
    max_questions_per_request: Annotated[int, Field(ge=1, le=MAX_QUESTIONS)]
    supports_distributions: bool
    supports_bounded_numeric: bool
    timeout_ms: Annotated[int, Field(ge=1, le=600_000)]


@runtime_checkable
class DecisionProvider(Protocol):
    provider_name: str
    model_version: str
    capabilities: DecisionProviderCapabilities

    def answer(
        self, request: DecisionRequest, schema: DecisionSchema
    ) -> DecisionResult: ...


class DecisionProviderError(Exception):
    """Base for every provider failure; catchable without importing outside app.decisions."""


class DecisionTimeoutError(DecisionProviderError):
    """The provider did not answer within ``capabilities.timeout_ms``."""


class DecisionSchemaRejectedError(DecisionProviderError):
    """The provider cannot satisfy the schema (unsupported question type, too many questions)."""


class DecisionProviderUnavailableError(DecisionProviderError):
    """The provider is down, rate-limited, or not configured."""
