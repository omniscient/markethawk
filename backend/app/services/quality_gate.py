"""
Quality Gate Service stub.

The real implementation lives in issue #492 and will replace this stub when merged.
This module exists so the data_quality router (issue #493) can import QualityGateService
at module level without raising ImportError before #492 lands.
"""

from sqlalchemy.orm import Session


class QualityGateService:
    @staticmethod
    def assess(db: Session, request):
        raise NotImplementedError("QualityGateService.assess() is implemented in #492")
