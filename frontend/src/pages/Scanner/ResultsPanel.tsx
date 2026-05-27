import React from 'react';
import ScannerResults from '../../components/ScannerResults';
import SignalReviewStats from '../../components/SignalReviewStats';

export interface ResultsPanelProps {
  scanResults: any;
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
