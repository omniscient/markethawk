import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useBackfillMutation } from '../../hooks/useScorecard';

interface BackfillPanelProps {
  scannerType: string;
}

const todayStr = (): string => new Date().toISOString().slice(0, 10);
const thirtyDaysAgoStr = (): string => {
  const d = new Date();
  d.setDate(d.getDate() - 30);
  return d.toISOString().slice(0, 10);
};

const BackfillPanel: React.FC<BackfillPanelProps> = ({ scannerType }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [startDate, setStartDate] = useState(thirtyDaysAgoStr);
  const [endDate, setEndDate] = useState(todayStr);
  const backfill = useBackfillMutation();

  const handleBackfill = () => {
    backfill.mutate({
      scanner_type: scannerType,
      start_date: startDate,
      end_date: endDate,
    });
  };

  return (
    <div className="bg-financial-gray rounded-lg border border-gray-700 overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-800/30 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isOpen ? (
            <ChevronDown className="h-4 w-4 text-gray-400" />
          ) : (
            <ChevronRight className="h-4 w-4 text-gray-400" />
          )}
          <span className="text-sm font-semibold text-financial-light">Backfill Outcomes</span>
        </div>
        <span className="text-xs text-gray-500">Populate historical outcome data</span>
      </button>

      {isOpen && (
        <div className="px-4 pb-4 pt-2 border-t border-gray-700">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Start Date</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="bg-financial-dark border border-gray-700 text-financial-light rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-financial-blue"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">End Date</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="bg-financial-dark border border-gray-700 text-financial-light rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-financial-blue"
              />
            </div>
            <button
              onClick={handleBackfill}
              disabled={backfill.isPending}
              className="px-4 py-1.5 bg-financial-blue text-white text-sm font-medium rounded hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {backfill.isPending && (
                <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white" />
              )}
              Run Backfill
            </button>
          </div>

          {backfill.isSuccess && (
            <div className="mt-3 text-sm text-green-400">
              {backfill.data.snapshots_created} snapshots created from {backfill.data.events_processed} events
            </div>
          )}

          {backfill.isError && (
            <div className="mt-3 text-sm text-red-400">
              Backfill failed: {backfill.error.message}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default BackfillPanel;
