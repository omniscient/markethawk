from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session


def get_or_404(db: Session, model: type, record_id: Any, name: str) -> Any:
    obj = db.query(model).filter(model.id == record_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj
