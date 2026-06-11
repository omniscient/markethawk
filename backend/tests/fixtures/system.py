"""
System config seed helpers.
Each function inserts rows and flushes; the caller's transaction provides rollback.
"""

from sqlalchemy.orm import Session

from app.models.system_config import SystemConfig


def seed_system_config(db: Session) -> list[SystemConfig]:
    """
    Creates 3 SystemConfig entries covering typical scanner settings.
    Returns the list of created rows.
    """
    entries = [
        SystemConfig(key="scan_enabled", value="true"),
        SystemConfig(key="volume_threshold", value="4.0"),
        SystemConfig(key="gap_threshold", value="1.0"),
    ]
    for entry in entries:
        db.add(entry)
    db.flush()
    return entries
