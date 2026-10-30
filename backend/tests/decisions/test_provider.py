import pytest
from pydantic import ValidationError

from app.decisions.provider import (
    DecisionProvider,
    DecisionProviderCapabilities,
    DecisionProviderError,
    DecisionProviderUnavailableError,
    DecisionSchemaRejectedError,
    DecisionTimeoutError,
)
from app.decisions.request import DecisionRequest
from app.decisions.result import DecisionResult
from app.decisions.schema import DecisionSchema
from tests.decisions.factories import make_request, make_result, make_schema


class DeterministicBaselineProvider:
    """A non-LLM provider: proves the protocol needs no vendor-specific attribute."""

    provider_name = "deterministic_baseline"
    model_version = "0"
    capabilities = DecisionProviderCapabilities(
        max_questions_per_request=4,
        supports_distributions=True,
        supports_bounded_numeric=True,
        timeout_ms=1_000,
    )

    def answer(
        self, request: DecisionRequest, schema: DecisionSchema
    ) -> DecisionResult:
        return make_result(
            schema,
            request_ref=str(request.request_id),
            provider_name=self.provider_name,
            model_version=self.model_version,
        )


def test_baseline_provider_satisfies_protocol():
    provider = DeterministicBaselineProvider()
    assert isinstance(provider, DecisionProvider)
    schema = make_schema()
    result = provider.answer(make_request(schema), schema)
    assert (result.provider_name, result.model_version) == (
        provider.provider_name,
        provider.model_version,
    )


def test_object_without_answer_is_not_a_provider():
    class NotAProvider:
        provider_name = "x"
        model_version = "0"
        capabilities = DeterministicBaselineProvider.capabilities

    assert not isinstance(NotAProvider(), DecisionProvider)


def test_capabilities_are_bounded_and_strict():
    with pytest.raises(ValidationError):
        DecisionProviderCapabilities(
            max_questions_per_request=33,
            supports_distributions=True,
            supports_bounded_numeric=True,
            timeout_ms=1_000,
        )
    with pytest.raises(ValidationError):
        DecisionProviderCapabilities(
            max_questions_per_request=4,
            supports_distributions=1,
            supports_bounded_numeric=True,
            timeout_ms=1_000,
        )


@pytest.mark.parametrize(
    "error",
    [
        DecisionTimeoutError,
        DecisionSchemaRejectedError,
        DecisionProviderUnavailableError,
    ],
)
def test_error_taxonomy_shares_one_base(error):
    with pytest.raises(DecisionProviderError):
        raise error("boom")
