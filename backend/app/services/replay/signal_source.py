"""Signal loading helpers for replay execution."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent


@dataclass
class LoadedSignals:
    signals: list[ScannerEvent]
    signal_source: str
    days_missing: int = 0
    days_unsupported: int = 0


class SignalSource:
    def __init__(self, db: Session):
        self._db = db

    def load_existing(self, scanner_type: str, tickers: list[str], start_date, end_date) -> LoadedSignals:
        signals = (
            self._db.query(ScannerEvent)
            .filter(
                ScannerEvent.scanner_type == scanner_type,
                ScannerEvent.ticker.in_(tickers),
                ScannerEvent.event_date >= start_date,
                ScannerEvent.event_date <= end_date,
            )
            .order_by(ScannerEvent.event_date.asc(), ScannerEvent.ticker.asc())
            .all()
        )
        return LoadedSignals(signals=signals, signal_source="db")
