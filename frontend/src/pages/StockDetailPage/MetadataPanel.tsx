
import { Globe, Newspaper } from 'lucide-react';
import Card from '../../components/ui/Card';
import NewsFeed from '../../components/NewsFeed';
import type { StockDetailConsolidated } from '../../api/stocks';
import type { ScannerEvent } from '../../api/scanner';

export interface MetadataPanelProps {
  symbol: string;
  details: StockDetailConsolidated;
  scannerResults: ScannerEvent[] | undefined;
  events: ScannerEvent[];
}

export function MetadataPanel({ symbol, details, scannerResults, events }: MetadataPanelProps) {
  return (
    <div className="space-y-6">
      <Card title="Stock Specific News" icon={Newspaper}>
        <NewsFeed ticker={symbol} limit={10} />
      </Card>

      <Card title="Trader Plan Checklist" icon={Globe}>
        <div className="space-y-3">
          {[
            { label: 'Scanner Alert Detected', status: events.length > 0 },
            { label: 'Check Extended Hours Volume', status: (details?.pre_market?.pre_market_volume || 0) > 100000 },
            { label: 'Confirm Sector Strength', status: true },
            { label: 'Review Catalyst Summary', status: scannerResults && scannerResults.some((e) => e.metadata?.catalyst_summary) },
          ].map((item, idx) => (
            <div key={idx} className="flex items-center space-x-3 p-3 bg-gray-800/50 rounded-lg">
              <div className={`h-2 w-2 rounded-full ${item.status ? 'bg-positive' : 'bg-gray-600'}`}></div>
              <span className={`text-sm ${item.status ? 'text-financial-light' : 'text-gray-500'}`}>{item.label}</span>
            </div>
          ))}
          <div className="mt-4 p-4 bg-financial-blue/10 border border-financial-blue/20 rounded-lg">
            <p className="text-xs text-blue-300 leading-relaxed">
              <strong>Pro Tip:</strong> Stocks in play often test high/low liquidity before a major move.
              Watch for wick rejections at {symbol}'s PM High (${details?.pre_market?.pre_market_high?.toFixed(2) || 'N/A'}).
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}
