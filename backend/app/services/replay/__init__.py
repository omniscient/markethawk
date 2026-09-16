"""Replay engine services."""

from app.services.replay.benchmark import BenchmarkIngestionError, BenchmarkIngestor
from app.services.replay.classifier import (
    RegimeClassifier,
    ReplayRegime,
    get_benchmark_regime,
)
from app.services.replay.manifest import (
    ManifestResolver,
    ResolvedManifest,
    compute_data_hash,
)
from app.services.replay.metrics import MetricsComputer, MetricsResult
from app.services.replay.protocols import (
    ExitSimulator,
    SignalRecord,
    SimulatedTrade,
    StrategyParams,
)

__all__ = [
    "ExitSimulator",
    "BenchmarkIngestionError",
    "BenchmarkIngestor",
    "ManifestResolver",
    "MetricsComputer",
    "MetricsResult",
    "RegimeClassifier",
    "ResolvedManifest",
    "ReplayRegime",
    "SignalRecord",
    "SimulatedTrade",
    "StrategyParams",
    "compute_data_hash",
    "get_benchmark_regime",
]
