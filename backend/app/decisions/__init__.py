"""Provider-neutral typed decision contracts (epic #871, child C1 / #872).

Standard library + Pydantic only. See tests/decisions/test_architecture_boundary.py.
"""

from app.decisions.policy import (
    DecisionContractViolation,
    PolicyOutcome,
    decide,
    validate_request,
    validate_result,
)
from app.decisions.provider import (
    DecisionProvider,
    DecisionProviderCapabilities,
    DecisionProviderError,
    DecisionProviderUnavailableError,
    DecisionSchemaRejectedError,
    DecisionTimeoutError,
)
from app.decisions.request import (
    DecisionMarketSnapshot,
    DecisionRequest,
    DecisionRunLineage,
    QualityGateRef,
)
from app.decisions.result import (
    DecisionAnswer,
    DecisionDistribution,
    DecisionResult,
    DecisionUsage,
    DistributionPoint,
)
from app.decisions.schema import (
    BoundedNumericAnswerSpace,
    CategoricalAnswerSpace,
    DecisionQuestionDef,
    DecisionSchema,
    UntrustedText,
)

__all__ = [
    "BoundedNumericAnswerSpace",
    "CategoricalAnswerSpace",
    "DecisionAnswer",
    "DecisionContractViolation",
    "DecisionDistribution",
    "DecisionMarketSnapshot",
    "DecisionProvider",
    "DecisionProviderCapabilities",
    "DecisionProviderError",
    "DecisionProviderUnavailableError",
    "DecisionQuestionDef",
    "DecisionRequest",
    "DecisionResult",
    "DecisionRunLineage",
    "DecisionSchema",
    "DecisionSchemaRejectedError",
    "DecisionTimeoutError",
    "DecisionUsage",
    "DistributionPoint",
    "PolicyOutcome",
    "QualityGateRef",
    "UntrustedText",
    "decide",
    "validate_request",
    "validate_result",
]
