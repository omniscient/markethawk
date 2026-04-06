"""
CLI script to bulk-download historical futures data from IBKR.

Usage:
    python -m scripts.download_futures --symbol ES --exchange CME --timespan day
    python -m scripts.download_futures --symbol GC --exchange COMEX --timespan minute
"""

import sys
import os
import argparse
import asyncio
import logging

# Add the project root to python path so we can import 'app'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal
from app.services.futures_data import FuturesDataService
from app.providers import DataProviderFactory
from app.core.config import settings

# Configure logging for script (console output)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("download_futures")

async def main():
    parser = argparse.ArgumentParser(description="Download Futures History from IBKR")
    parser.add_argument("--symbol", required=True, help="Contract root symbol (e.g., ES)")
    parser.add_argument("--exchange", required=True, help="Exchange (e.g., CME)")
    parser.add_argument("--timespan", default="day", choices=["day", "hour", "minute"], help="Bar timespan")
    parser.add_argument("--multiplier", type=int, default=1, help="Bar multiplier")
    parser.add_argument("--contract", help="Specific contract month (YYYYMMDD). If provided, only downloads this contract.")
    parser.add_argument("--force", action="store_true", help="Force re-download even if already downloaded")
    
    args = parser.parse_args()

    # Check IBKR configuration
    ibkr = DataProviderFactory.get("ibkr")
    if not ibkr.is_available():
        logger.error(
            "IBKR provider is not available. Please ensure your .env file "
            "contains IBKR_HOST and IBKR_PORT, and that you have installed ib_insync."
        )
        sys.exit(1)
        
    db = SessionLocal()
    
    try:
        if args.contract:
            logger.info(f"Downloading single contract: {args.symbol} {args.contract}")
            res = await FuturesDataService.download_contract(
                db=db,
                symbol=args.symbol,
                exchange=args.exchange,
                contract_month=args.contract,
                timespan=args.timespan,
                multiplier=args.multiplier,
                force_refresh=args.force
            )
            logger.info(f"Result: {res}")
            
        else:
            logger.info(f"Downloading full continuous history for: {args.symbol} / {args.exchange}")
            
            def progress(contract_month, current, total):
                logger.info(f"--> Progress: {current}/{total} (Just finished {contract_month})")
                
            res = await FuturesDataService.download_full_history(
                db=db,
                symbol=args.symbol,
                exchange=args.exchange,
                timespan=args.timespan,
                multiplier=args.multiplier,
                force_refresh=args.force,
                progress_callback=progress
            )
            logger.info("\n=== DOWNLOAD COMPLETE ===")
            logger.info(f"Status: {res.get('status')}")
            logger.info(f"Contracts processed: {res.get('contracts_processed')}")
            logger.info(f"Bars added: {res.get('bars_added')}")
            logger.info(f"Rollovers detected: {res.get('rollovers_detected')}")
            
    except Exception as e:
        logger.error(f"Fatal error during download: {e}", exc_info=True)
    finally:
        db.close()
        # Clean shutdown of IBKR connection
        if ibkr.is_available():
            ibkr.disconnect()

if __name__ == "__main__":
    # Workaround for ProactorEventLoop issue on Windows shutting down asyncpg/ib_insync connections
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(main())
