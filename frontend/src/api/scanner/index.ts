// Facade — re-exports all scanner sub-modules so existing imports keep working.
// Universe symbols are re-exported as @deprecated; prefer importing from '../universe' directly.

export * from './types';
export * from './runs';
export * from './results';
export * from './configs';
export * from './reviews';
export * from './ws';
export * from './misc';

/** @deprecated Import from '../api/universe' instead */
export type {
  StockUniverse,
  UniverseSyncStatus,
  MonitoredStock,
  RefreshUniverseResponse,
  SyncAggregatesOptions,
  UniverseSummary,
  TaskEnqueueResponse,
  ExportAggregatesOptions,
  QualityGapEntry,
  CoveragePartialDay,
  CoverageDetail,
  QualityTickerResult,
  NormalizationProgress,
  QualityReport,
} from '../universe';

/** @deprecated Import from '../api/universe' instead */
export {
  fetchUniversesForTicker,
  fetchStockUniverses,
  refreshUniverseStats,
  createStockUniverse,
  deleteStockUniverse,
  updateStockUniverse,
  syncFundamentals,
  syncMetrics,
  syncTickerDetails,
  stopSync,
  refreshUniverse,
  fetchUniverseStocks,
  syncMissingAggregates,
  fetchUniverseSyncStatus,
  syncUniverseAggregates,
  exportUniverseAggregates,
  deleteTickerAggregates,
  triggerQualityAnalysis,
  triggerNormalization,
  fetchQualityReport,
} from '../universe';
