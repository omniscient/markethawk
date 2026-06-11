import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.stock_metric import StockMetric
from app.models.ticker_reference import TickerReference

logger = logging.getLogger(__name__)


class StockScreener:
    @staticmethod
    def screen(db: Session, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        data_source = criteria.get("data_source_stocks", "massive")
        has_metric_filters = "min_volume" in criteria and criteria["min_volume"] > 0

        if has_metric_filters:
            query = db.query(TickerReference, StockMetric).join(
                StockMetric, TickerReference.ticker == StockMetric.ticker
            )
        else:
            query = db.query(TickerReference)

        if "min_market_cap" in criteria and criteria["min_market_cap"] > 0:
            query = query.filter(
                TickerReference.market_cap >= criteria["min_market_cap"]
            )

        if "max_market_cap" in criteria and criteria["max_market_cap"] > 0:
            query = query.filter(
                TickerReference.market_cap <= criteria["max_market_cap"]
            )

        if (
            "min_outstanding_shares" in criteria
            and criteria["min_outstanding_shares"] > 0
        ):
            query = query.filter(
                TickerReference.outstanding_shares >= criteria["min_outstanding_shares"]
            )

        if "sector" in criteria and criteria["sector"]:
            if isinstance(criteria["sector"], list):
                if len(criteria["sector"]) > 0:
                    query = query.filter(TickerReference.sector.in_(criteria["sector"]))
            elif criteria["sector"]:
                query = query.filter(TickerReference.sector == criteria["sector"])

        if "primary_exchange" in criteria and criteria["primary_exchange"]:
            if isinstance(criteria["primary_exchange"], list):
                if len(criteria["primary_exchange"]) > 0:
                    query = query.filter(
                        TickerReference.primary_exchange.in_(
                            criteria["primary_exchange"]
                        )
                    )
            elif criteria["primary_exchange"]:
                query = query.filter(
                    TickerReference.primary_exchange == criteria["primary_exchange"]
                )

        if "sic_code" in criteria and criteria["sic_code"]:
            query = query.filter(TickerReference.sic_code == criteria["sic_code"])

        if "description_contains" in criteria and criteria["description_contains"]:
            query = query.filter(
                TickerReference.description.ilike(
                    f"%{criteria['description_contains']}%"
                )
            )

        if "min_employees" in criteria and criteria["min_employees"] > 0:
            query = query.filter(
                TickerReference.total_employees >= criteria["min_employees"]
            )

        if "max_employees" in criteria and criteria["max_employees"] > 0:
            query = query.filter(
                TickerReference.total_employees <= criteria["max_employees"]
            )

        if (
            "min_share_class_shares" in criteria
            and criteria["min_share_class_shares"] > 0
        ):
            query = query.filter(
                TickerReference.share_class_shares_outstanding
                >= criteria["min_share_class_shares"]
            )

        if (
            "max_share_class_shares" in criteria
            and criteria["max_share_class_shares"] > 0
        ):
            query = query.filter(
                TickerReference.share_class_shares_outstanding
                <= criteria["max_share_class_shares"]
            )

        if has_metric_filters:
            if "min_volume" in criteria and criteria["min_volume"] > 0:
                query = query.filter(StockMetric.volume >= criteria["min_volume"])

        if settings.LOG_LEVEL == "DEBUG":
            try:
                statement = query.statement.compile(
                    compile_kwargs={"literal_binds": True}
                )
                logger.info(f"🔍 Discovery Screen Query: {statement}")
            except Exception as e:
                logger.error(f"Failed to log debug query: {e}")

        results = query.all()

        output = []
        for row in results:
            if has_metric_filters:
                ref, metric = row
            else:
                ref = row
                metric = None

            output.append(
                {
                    "ticker": ref.ticker,
                    "name": ref.name,
                    "market_cap": ref.market_cap,
                    "close_price": metric.close_price if metric else None,
                    "volume": metric.volume if metric else None,
                    "sector": ref.sector,
                    "primary_exchange": ref.primary_exchange,
                    "employees": ref.total_employees,
                    "sic_code": ref.sic_code,
                    "description": ref.description,
                    "asset_class": "stocks",
                    "data_source": data_source,
                }
            )
        return output


from app.services.discovery_service import register_screener  # noqa: E402

register_screener("stocks", StockScreener.screen)
