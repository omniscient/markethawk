
import ScannerResults from '../../components/ScannerResults';
import SignalReviewStats from '../../components/SignalReviewStats';
import type { ScannerRunResponse } from '../../api/scanner';

export interface ResultsPanelProps {
  scanResults: ScannerRunResponse | null;
  sortBy: string;
  sortOrder: 'asc' | 'desc';
  onSort: (column: string) => void;
}

export function ResultsPanel({ scanResults, sortBy, sortOrder, onSort }: ResultsPanelProps) {
  return (
    <>
      {scanResults && (
        <div className="animate-slide-up">
          <ScannerResults
            results={scanResults}
            sortBy={sortBy}
            sortOrder={sortOrder}
            onSort={onSort}
          />
        </div>
      )}
      <SignalReviewStats />
    </>
  );
}
