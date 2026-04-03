"""
Backend Error Tracking Module
==============================
Centralizes the capture and routing of unhandled exceptions.

Architecture (easily switchable):
- ErrorTracker  – structural Protocol every implementation must satisfy.
- StdoutErrorTracker  – logs to Python's stdlib logger only (offline fallback).
- SeqErrorTracker     – sends structured events to a Seq ingestion endpoint AND
                        falls back to stdlib logging so nothing is ever lost.
- ErrorTrackerFactory – reads `settings.SEQ_URL` at startup once and hands out
                        the right implementation. Set SEQ_URL to "" or "disabled"
                        to force stdout-only mode.

To swap to a different backend (e.g. Grafana Loki, Sentry, Datadog):
  1. Implement a class that satisfies the ErrorTracker Protocol.
  2. Register it in ErrorTrackerFactory.get_tracker().
  3. Update the SEQ_URL env var (or add a new env var for the new backend).
"""

import asyncio
import datetime
import logging
from typing import Optional, Protocol

import httpx


# --------------------------------------------------------------------------- #
# Protocol (interface)
# --------------------------------------------------------------------------- #

class ErrorTracker(Protocol):
    """Any error-tracking backend must implement this single method."""

    def log_error(
        self,
        error_id: str,
        exc: Exception,
        tb_string: str,
        path: str,
    ) -> None: ...


# --------------------------------------------------------------------------- #
# Implementations
# --------------------------------------------------------------------------- #

class StdoutErrorTracker:
    """Fallback tracker – logs to Python's stdlib logger only."""

    def log_error(self, error_id: str, exc: Exception, tb_string: str, path: str) -> None:
        logging.error(
            "Unhandled exception [%s] at %s: %s\n%s",
            error_id,
            path,
            exc,
            tb_string,
        )


class SeqErrorTracker:
    """
    Sends structured log events to a Seq ingestion endpoint.

    Seq Raw Events API:
      POST {seq_url}/api/events/raw
      Body: { "Events": [ { "Timestamp", "Level", "MessageTemplate", "Properties", "Exception" } ] }

    Falls back silently to stdlib logging if Seq is unreachable so the app
    never crashes due to its own error-reporting system.
    """

    def __init__(self, seq_url: str = "http://seq:5341") -> None:
        self.ingestion_endpoint = f"{seq_url.rstrip('/')}/api/events/raw"

    def log_error(self, error_id: str, exc: Exception, tb_string: str, path: str) -> None:
        # Always write locally first – guaranteed capture regardless of Seq state.
        logging.error("Unhandled exception [%s] at %s: %s", error_id, path, exc)

        payload = {
            "Events": [
                {
                    "Timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "Level": "Fatal",
                    "MessageTemplate": "Unhandled exception at {Path}. ErrorId: {ErrorId}",
                    "Properties": {
                        "Path": path,
                        "ErrorId": error_id,
                        "ExceptionType": type(exc).__name__,
                        "ExceptionDetail": str(exc),
                    },
                    # Seq renders "Exception" in its own structured panel
                    "Exception": tb_string,
                }
            ]
        }

        async def _send() -> None:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(self.ingestion_endpoint, json=payload)
            except Exception as send_exc:  # noqa: BLE001
                # Never let the tracker bring down the app
                logging.warning("Failed to send [%s] to Seq: %s", error_id, send_exc)

        # Schedule as a background task; don't block the HTTP response.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_send())
        except RuntimeError:
            # No running event loop (e.g., during tests) – run synchronously.
            asyncio.run(_send())


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #

class ErrorTrackerFactory:
    """
    Singleton accessor for the configured ErrorTracker implementation.

    Reads `settings.SEQ_URL` once and caches the tracker.  To swap backends
    at runtime (e.g., in tests), call `ErrorTrackerFactory.reset()` then
    set a fresh tracker via `ErrorTrackerFactory._tracker`.
    """

    _tracker: Optional[ErrorTracker] = None

    @classmethod
    def get_tracker(cls) -> ErrorTracker:
        if cls._tracker is None:
            cls._tracker = cls._build()
        return cls._tracker

    @classmethod
    def reset(cls) -> None:
        """Allow tests (or hot-reload scenarios) to rebuild the tracker."""
        cls._tracker = None

    @classmethod
    def _build(cls) -> ErrorTracker:
        # Import here to avoid circular imports during module load.
        from app.core.config import settings  # noqa: PLC0415

        seq_url = getattr(settings, "SEQ_URL", "")
        if not seq_url or seq_url.lower() in ("disabled", "none", "false", ""):
            logging.info("[ErrorTracking] Seq disabled – using stdout-only tracker.")
            return StdoutErrorTracker()

        logging.info("[ErrorTracking] Using Seq tracker → %s", seq_url)
        return SeqErrorTracker(seq_url=seq_url)
