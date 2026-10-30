import hashlib
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.decisions.request import (
    EMPTY_SHA256,
    DecisionMarketSnapshot,
    DecisionRequest,
    DecisionRunLineage,
    QualityGateRef,
    persisted_assessment_sha256,
)
from tests.decisions.factories import (
    AS_OF,
    RUN_UUID,
    make_gate,
    make_request,
    make_snapshot,
)


def test_valid_request_constructs():
    request = make_request()
    assert request.quality_gate.verdict == "trusted"


def test_rejects_missing_feature_provenance_ref():
    with pytest.raises(ValidationError):
        DecisionRunLineage(scanner_run_uuid=RUN_UUID)


def test_rejects_missing_quality_gate():
    payload = make_request().model_dump()
    del payload["quality_gate"]
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)


def test_rejects_missing_observed_at():
    payload = make_snapshot().model_dump()
    del payload["observed_at"]
    with pytest.raises(ValidationError):
        DecisionMarketSnapshot.model_validate(payload)


def test_rejects_naive_as_of():
    with pytest.raises(ValidationError):
        make_request(as_of=AS_OF.replace(tzinfo=None))


def test_snapshot_has_no_free_text_fields():
    request = make_request()
    with pytest.raises(ValidationError):
        make_snapshot(headline="Buy now")
    with pytest.raises(ValidationError):
        make_snapshot(ticker="buy 1000 shares")
    assert request.market_snapshot.ticker == "ACME"


def test_no_assessment_ref_is_the_designated_shape():
    ref = QualityGateRef.no_assessment(as_of=AS_OF, source_run_uuid=RUN_UUID)
    assert ref.verdict == "skipped"
    assert ref.trusted is False
    assert ref.issue_codes == ("no_assessment",)
    assert ref.assessment_sha256 == hashlib.sha256(b"").hexdigest() == EMPTY_SHA256
    assert ref.generated_at == AS_OF
    assert make_request(quality_gate=ref).quality_gate == ref


def test_no_assessment_code_cannot_be_reused_on_other_shapes():
    with pytest.raises(ValidationError):
        make_gate(issue_codes=("no_assessment",))


def test_rejects_unknown_issue_code():
    with pytest.raises(ValidationError):
        make_gate(issue_codes=("vibes_off",))


def test_persisted_assessment_sha256_matches_canonical_jsonb():
    persisted = json.loads(
        json.dumps(
            {
                "schema_version": "quality_gate.v1",
                "verdict": "warning",
                "generated_at": datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc),
                "issues": [],
            },
            default=str,
        )
    )
    expected = hashlib.sha256(
        json.dumps(
            persisted, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()
    assert persisted_assessment_sha256(persisted) == expected
    reordered = dict(reversed(list(persisted.items())))
    assert persisted_assessment_sha256(reordered) == expected


def test_frozen_request_rejects_mutation():
    request = make_request()
    with pytest.raises(ValidationError):
        request.as_of = AS_OF
    with pytest.raises(ValidationError):
        request.quality_gate.verdict = "trusted"
