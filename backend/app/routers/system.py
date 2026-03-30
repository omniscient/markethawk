"""
System-level information and status router.
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

from app.core.database import get_db

router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger(__name__)

def format_bytes(size: int) -> str:
    """Format bytes into a human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"

@router.get("/storage")
async def get_storage_stats(db: Session = Depends(get_db)):
    """
    Get storage usage statistics for major database tables.
    Returns sizes in bytes and formatted strings.
    """
    try:
        # Define table groups as they appear in the UI
        table_groups = {
            "scanner": ["volume_events", "scanner_runs"],
            "historical": ["stock_aggregates", "stock_metrics", "ticker_references", "news_articles"],
            "settings": ["news_preferences", "scanner_configs"]
        }
        
        results = {
            "scanner": {"bytes": 0, "formatted": "0.0 B"},
            "historical": {"bytes": 0, "formatted": "0.0 B"},
            "settings": {"bytes": 0, "formatted": "0.0 B"},
            "total": {"bytes": 0, "formatted": "0.0 B"}
        }

        dialect = db.bind.dialect.name
        
        if dialect == "postgresql":
            # For PostgreSQL, we can get per-table sizes
            all_tables = []
            for group in table_groups.values():
                all_tables.extend(group)
            
            # Using a safer way to pass the list of tables for Postgres
            query = text("""
                SELECT 
                    relname as table_name,
                    pg_total_relation_size(relid) as total_size
                FROM pg_catalog.pg_statio_user_tables
                WHERE relname = ANY(:tables)
            """)
            
            db_results = db.execute(query, {"tables": all_tables}).fetchall()
            table_sizes = {row.table_name: row.total_size for row in db_results}
            
            for group_name, tables in table_groups.items():
                group_size = sum(table_sizes.get(t, 0) for t in tables)
                results[group_name]["bytes"] = group_size
                results[group_name]["formatted"] = format_bytes(group_size)
                results["total"]["bytes"] += group_size
        
        elif dialect == "sqlite":
            # For SQLite, the entire database is usually one file.
            # We'll get the total file size and label it as SQLITE
            import os
            db_url = str(db.bind.url)
            # Handle sqlite:///test.db or absolute paths
            db_path = db_url.replace("sqlite:///", "")
            
            total_size = 0
            if os.path.exists(db_path):
                total_size = os.path.getsize(db_path)
            
            # Since we can't easily break down SQLite by table group without 
            # complex queries, we'll assign the total to total and historical
            results["historical"]["bytes"] = total_size
            results["historical"]["formatted"] = f"{format_bytes(total_size)} (SQLite)"
            results["total"]["bytes"] = total_size
            results["total"]["formatted"] = f"{format_bytes(total_size)} (Full DB)"
        
        else:
            # Fallback for other dialects
            results["total"]["formatted"] = f"Unknown DB ({dialect})"

        results["total"]["formatted"] = format_bytes(results["total"]["bytes"])
        
        return results

    except Exception as e:
        logger.error(f"Error fetching storage stats: {e}", exc_info=True)
        # Final fallback to avoid 500ing the page
        return {
            "scanner": {"bytes": 0, "formatted": "N/A"},
            "historical": {"bytes": 0, "formatted": "N/A"},
            "settings": {"bytes": 0, "formatted": "N/A"},
            "total": {"bytes": 0, "formatted": "Service Error"}
        }

@router.get("/info", response_model=Dict[str, Any])
async def get_app_info():
    """Get basic application information and configuration status."""
    from app.core.config import settings
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "data_mode": "delayed" if settings.POLYGON_DELAYED else "live",
        "log_level": settings.LOG_LEVEL
    }
