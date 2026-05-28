"""SystemService — extracted business logic from routers/system.py."""

import json
import socket
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = __import__("logging").getLogger(__name__)

ET = zoneinfo.ZoneInfo("America/New_York")


def _now_et() -> datetime:
    """Return current datetime in ET. Module-level so tests can monkeypatch it."""
    return datetime.now(ET)


class SystemService:
    @staticmethod
    def get_market_status() -> str:
        now_et = _now_et()
        if now_et.weekday() >= 5:
            return "closed"
        t = now_et.hour * 60 + now_et.minute
        if 240 <= t < 570:  # 04:00–09:30
            return "pre_market"
        if 570 <= t < 960:  # 09:30–16:00
            return "open"
        if 960 <= t < 1200:  # 16:00–20:00
            return "post_market"
        return "closed"

    @staticmethod
    def check_ibkr_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True
        except OSError:
            return False

    @staticmethod
    def format_bytes(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    @staticmethod
    def get_storage_stats(db: Session) -> dict[str, Any]:
        table_groups = {
            "scanner": ["volume_events", "scanner_runs"],
            "historical": [
                "stock_aggregates",
                "stock_metrics",
                "ticker_references",
                "news_articles",
            ],
            "settings": ["news_preferences", "scanner_configs"],
        }
        results: dict[str, Any] = {
            "scanner": {"bytes": 0, "formatted": "0.0 B"},
            "historical": {"bytes": 0, "formatted": "0.0 B"},
            "settings": {"bytes": 0, "formatted": "0.0 B"},
            "total": {"bytes": 0, "formatted": "0.0 B"},
        }
        try:
            dialect = db.bind.dialect.name
            if dialect == "postgresql":
                all_tables: list[str] = []
                for group in table_groups.values():
                    all_tables.extend(group)
                query = text("""
                    SELECT relname as table_name,
                           pg_total_relation_size(relid) as total_size
                    FROM pg_catalog.pg_statio_user_tables
                    WHERE relname = ANY(:tables)
                """)
                db_results = db.execute(query, {"tables": all_tables}).fetchall()
                table_sizes = {row.table_name: row.total_size for row in db_results}
                for group_name, tables in table_groups.items():
                    group_size = sum(table_sizes.get(t, 0) for t in tables)
                    results[group_name]["bytes"] = group_size
                    results[group_name]["formatted"] = SystemService.format_bytes(
                        group_size
                    )
                    results["total"]["bytes"] += group_size
            elif dialect == "sqlite":
                import os

                db_url = str(db.bind.url)
                db_path = db_url.replace("sqlite:///", "")
                total_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
                results["historical"]["bytes"] = total_size
                results["historical"]["formatted"] = (
                    f"{SystemService.format_bytes(total_size)} (SQLite)"
                )
                results["total"]["bytes"] = total_size
            else:
                results["total"]["formatted"] = f"Unknown DB ({dialect})"
            results["total"]["formatted"] = SystemService.format_bytes(
                results["total"]["bytes"]
            )
        except Exception as exc:
            logger.error(f"Error fetching storage stats: {exc}", exc_info=True)
            return {
                "scanner": {"bytes": 0, "formatted": "N/A"},
                "historical": {"bytes": 0, "formatted": "N/A"},
                "settings": {"bytes": 0, "formatted": "N/A"},
                "total": {"bytes": 0, "formatted": "Service Error"},
            }
        return results

    @staticmethod
    async def get_active_tasks(
        redis_client: aioredis.Redis,
        db: Session,
    ) -> list[dict]:
        from celery.result import AsyncResult

        from app.core.celery_app import celery_app
        from app.models.stock_universe import StockUniverse
        from app.models.universe_quality_report import UniverseQualityReport

        active_tasks: list[dict] = []

        async def _scan_pattern(pattern: str) -> list[str]:
            keys: list[str] = []
            cursor = "0"
            while True:
                cursor, batch = await redis_client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                keys.extend(batch)
                if str(cursor) == "0":
                    break
            return keys

        def _is_stale(data: dict) -> bool:
            ts_str = data.get("started_at")
            if not ts_str:
                return False
            try:
                started = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - started).total_seconds() / 3600 > 4
            except (ValueError, TypeError):
                return False

        def _has_pending_tasks(data: dict) -> bool:
            tids = data.get("task_ids") or []
            return any(
                AsyncResult(tid, app=celery_app).state
                in ("PENDING", "STARTED", "RETRY")
                for tid in tids
            )

        # universe:*:sync
        for key in await _scan_pattern("universe:*:sync"):
            parts = key.split(":")
            if len(parts) < 2 or not parts[1].isdigit():
                continue
            uid = int(parts[1])
            raw = await redis_client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if _is_stale(data):
                await redis_client.delete(key)
                continue
            if not _has_pending_tasks(data):
                await redis_client.delete(key)
                continue
            universe = db.query(StockUniverse).filter(StockUniverse.id == uid).first()
            name = universe.name if universe else f"Universe {uid}"
            active_tasks.append(
                {
                    "id": f"sync_{uid}",
                    "type": "sync",
                    "title": f"Syncing Data: {name}",
                    "status": "running",
                }
            )

        # ticker:*:sync
        for key in await _scan_pattern("ticker:*:sync"):
            parts = key.split(":")
            if len(parts) < 2:
                continue
            ticker = parts[1]
            raw = await redis_client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if _is_stale(data):
                await redis_client.delete(key)
                continue
            if not _has_pending_tasks(data):
                await redis_client.delete(key)
                continue
            active_tasks.append(
                {
                    "id": f"sync_ticker_{ticker}",
                    "type": "sync",
                    "title": f"Syncing Data: {ticker}",
                    "status": "running",
                }
            )

        # scan:*:range
        for key in await _scan_pattern("scan:*:range"):
            parts = key.split(":")
            ticker_name = parts[1] if len(parts) >= 2 else "?"
            raw = await redis_client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if _is_stale(data):
                await redis_client.delete(key)
                continue
            if not _has_pending_tasks(data):
                await redis_client.delete(key)
                continue
            active_tasks.append(
                {
                    "id": f"scan_{ticker_name}",
                    "type": "scan",
                    "title": f"Range Scan: {ticker_name}",
                    "status": "running",
                }
            )

        # universe:*:scan:*
        for key in await _scan_pattern("universe:*:scan:*"):
            parts = key.split(":")
            if len(parts) < 4 or not parts[1].isdigit():
                continue
            uid = int(parts[1])
            scanner_type = parts[3]
            raw = await redis_client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if _is_stale(data):
                await redis_client.delete(key)
                continue
            if not _has_pending_tasks(data):
                await redis_client.delete(key)
                continue
            universe = db.query(StockUniverse).filter(StockUniverse.id == uid).first()
            universe_name = universe.name if universe else f"Universe {uid}"
            day_idx = data.get("day_index", 0) if isinstance(data, dict) else 0
            total_days = data.get("total_days", 0) if isinstance(data, dict) else 0
            active_tasks.append(
                {
                    "id": f"scan_{uid}_{scanner_type}",
                    "type": "scan",
                    "title": (
                        f"Scanning {universe_name}: {scanner_type.replace('_', ' ')}"
                        + (f" — day {day_idx}/{total_days}" if total_days else "")
                    ),
                    "status": "running",
                }
            )

        # DB: quality + normalization tasks
        stale_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            hours=4
        )
        quality_reports = (
            db.query(UniverseQualityReport)
            .filter(
                (UniverseQualityReport.status.in_(["pending", "running"]))
                | (
                    UniverseQualityReport.normalization_status.in_(
                        ["pending", "running"]
                    )
                )
            )
            .all()
        )

        for report in quality_reports:
            is_stale = report.started_at and report.started_at < stale_cutoff
            if is_stale:
                if report.status in ("pending", "running"):
                    report.status = "failed"
                if report.normalization_status in ("pending", "running"):
                    report.normalization_status = "failed"
                db.add(report)
                db.commit()
                continue
            universe = (
                db.query(StockUniverse)
                .filter(StockUniverse.id == report.universe_id)
                .first()
            )
            name = universe.name if universe else f"Universe {report.universe_id}"
            if report.status in ("pending", "running"):
                active_tasks.append(
                    {
                        "id": f"qa_{report.universe_id}",
                        "type": "analysis",
                        "title": f"Quality Analysis: {name}",
                        "status": report.status,
                    }
                )
            if report.normalization_status in ("pending", "running"):
                active_tasks.append(
                    {
                        "id": f"norm_{report.universe_id}",
                        "type": "normalization",
                        "title": f"Normalizing Data: {name}",
                        "status": report.normalization_status,
                    }
                )

        return active_tasks
