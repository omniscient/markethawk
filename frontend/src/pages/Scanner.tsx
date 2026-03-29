import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { formatDistanceToNow, format } from 'date-fns';
import {
  Play,
  Pause,
  Settings,
  Download,
  Eye,
  Clock,
  Zap
} from 'lucide-react';

// Components
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import ScannerConfig from '../components/ScannerConfig';
import ScannerResults from '../components/ScannerResults';

// API functions
import { runScanner, fetchScannerConfigs, fetchStockUniverses, fetchScannerResults, fetchScannerHistory, StockUniverse } from '../api/scanner';

const Scanner: React.FC = () => {
  const [isScanning, setIsScanning] = useState(false);
  const [selectedConfig, setSelectedConfig] = useState<string>('pre_market_volume_spike');
  const [selectedUniverse, setSelectedUniverse] = useState<number | null>(null);
  const [scanResults, setScanResults] = useState<any>(null);
  const [sortBy, setSortBy] = useState<string>('created_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  // Fetch scanner configurations
  const { data: configs, isLoading: loadingConfigs } = useQuery({
    queryKey: ['scannerConfigs'],
    queryFn: fetchScannerConfigs,
  });

  // Fetch stock universes
  const { data: universes, isLoading: loadingUniverses } = useQuery({
    queryKey: ['stockUniverses'],
    queryFn: fetchStockUniverses,
  });

  // Fetch scanner history
  const { data: scanHistory, isLoading: loadingHistory } = useQuery({
    queryKey: ['scannerHistory'],
    queryFn: () => fetchScannerHistory(10),
  });

  const queryClient = useQueryClient();

  // Auto-load existing results
  const { data: existingResults } = useQuery({
    queryKey: ['scannerResults', selectedUniverse, selectedConfig, sortBy, sortOrder],
    queryFn: () => fetchScannerResults({
      universe_id: selectedUniverse,
      event_type: selectedConfig === 'pre_market_volume_spike' ? 'pre_market_volume_spike' : 'liquidity_hunt',
      sort_by: sortBy,
      sort_order: sortOrder,
      limit: 100
    }),
    enabled: !!selectedUniverse && !!selectedConfig,
  });

  // Update scanResults when existingResults changes (if no manual scan run recently)
  React.useEffect(() => {
    if (existingResults && !isScanning) {
      setScanResults({
        scan_id: 'historical',
        status: 'completed',
        stocks_scanned: 0, // Unknown for historical
        events_detected: existingResults.length,
        execution_time_ms: 0,
        events: existingResults
      });
    }
  }, [existingResults, isScanning]);

  // Run scanner mutation
  const scannerMutation = useMutation({
    mutationFn: runScanner,
    onSuccess: (data) => {
      setScanResults(data);
      setIsScanning(false);
      // Refresh history and configs (which has last_run)
      queryClient.invalidateQueries({ queryKey: ['scannerHistory'] });
      queryClient.invalidateQueries({ queryKey: ['scannerConfigs'] });
    },
    onError: (error) => {
      console.error('Scanner error:', error);
      setIsScanning(false);
      queryClient.invalidateQueries({ queryKey: ['scannerHistory'] });
    }
  });

  const handleRunScanner = async () => {
    // Basic validation
    if (!selectedUniverse && !selectedConfig) {
      alert("Please select a universe and scan type");
      return;
    }

    setIsScanning(true);
    try {
      scannerMutation.mutate({
        scanner_type: selectedConfig,
        universe_id: selectedUniverse || undefined,
        tickers: [], // Backend handles universe lookup
        dry_run: false
      });
    } catch (e) {
      console.error('Error triggering mutation:', e);
      setIsScanning(false);
    }
  };

  const handleStopScanner = () => {
    setIsScanning(false);
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-financial-light">Scanner</h1>
          <p className="text-gray-400 mt-1">Configure and run stock scanning algorithms</p>
        </div>
        <div className="flex items-center space-x-3">
          {isScanning ? (
            <Button
              variant="danger"
              onClick={handleStopScanner}
              icon={Pause as any}
              loading={scannerMutation.isPending}
            >
              Stop Scan
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={handleRunScanner}
              icon={Play as any}
              loading={scannerMutation.isPending}
              disabled={loadingConfigs}
            >
              Run Scanner
            </Button>
          )}
        </div>
      </div>

      {/* Scanner Status */}
      {isScanning && (
        <Card className="bg-blue-900/20 border-blue-500/30">
          <div className="flex items-center space-x-3">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-financial-blue"></div>
            <div>
              <h3 className="text-financial-light font-semibold">Scanner Running</h3>
              <p className="text-gray-400 text-sm">Analyzing stocks for volume spike patterns...</p>
            </div>
          </div>
        </Card>
      )}

      {/* Configuration */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card title="Scanner Configuration" icon={Settings as any}>
            <ScannerConfig
              configs={configs || []}
              universes={universes || []}
              selectedConfig={selectedConfig}
              selectedUniverse={selectedUniverse}
              onConfigChange={setSelectedConfig}
              onUniverseChange={setSelectedUniverse}
              loading={loadingConfigs || loadingUniverses}
            />
          </Card>
        </div>

        {/* Quick Stats */}
        <div className="space-y-4">
          <Card title="Scan Status" icon={Eye as any}>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Status</span>
                <span className={`px-2 py-1 rounded text-xs font-medium ${isScanning
                  ? 'bg-blue-500/20 text-blue-400'
                  : 'bg-green-500/20 text-green-400'
                  }`}>
                  {isScanning ? 'Running' : 'Ready'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Last Run</span>
                <span className="text-financial-light">
                  {(() => {
                    const currentConf = configs?.find(c => c.scanner_type === (selectedConfig === 'pre_market_volume_spike' ? 'pre_market_volume_spike' : 'liquidity_hunt'));
                    return currentConf?.last_run 
                      ? formatDistanceToNow(new Date(currentConf.last_run), { addSuffix: true })
                      : 'Never';
                  })()}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Next Run</span>
                <span className="text-financial-light">
                  {(() => {
                    const currentConf = configs?.find(c => c.scanner_type === (selectedConfig === 'pre_market_volume_spike' ? 'pre_market_volume_spike' : 'liquidity_hunt'));
                    return currentConf?.next_run 
                      ? formatDistanceToNow(new Date(currentConf.next_run), { addSuffix: true })
                      : 'Not scheduled';
                  })()}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Stocks in Universe</span>
                <span className="text-financial-light">
                  {universes?.find(u => u.id === selectedUniverse)?.ticker_count || universes?.find(u => u.id === selectedUniverse)?.aggregate_count || 0}
                </span>
              </div>
            </div>
          </Card>

          <Card title="Quick Actions" icon={Zap as any}>
            <div className="space-y-2">
              <Button
                variant="secondary"
                size="sm"
                fullWidth
                icon={Clock as any}
              >
                Schedule Scan
              </Button>
              <Button
                variant="secondary"
                size="sm"
                fullWidth
                icon={Download as any}
              >
                Export Results
              </Button>
            </div>
          </Card>
        </div>
      </div>

      {/* Results */}
      {scanResults && (
        <div className="animate-slide-up">
          <ScannerResults 
            results={scanResults} 
            sortBy={sortBy}
            sortOrder={sortOrder}
            onSort={(column) => {
              if (column === sortBy) {
                setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
              } else {
                setSortBy(column);
                setSortOrder('desc');
              }
            }}
          />
        </div>
      )}

      {/* Historical Results */}
      <Card title="Recent Scan History" icon={Clock as any}>
        <div className="space-y-4">
          {loadingHistory ? (
            <div className="text-center py-4 text-gray-400">Loading history...</div>
          ) : scanHistory && scanHistory.length > 0 ? (
            scanHistory.map((scan, index) => (
              <div key={index} className="flex items-center justify-between p-4 bg-gray-800 rounded-lg">
                <div className="flex-1">
                  <div className="flex items-center space-x-2">
                    <div className="text-financial-light font-medium">
                      {scan.created_at ? format(new Date(scan.created_at), 'yyyy-MM-dd HH:mm:ss') : 'Unknown Date'}
                    </div>
                    <span className="text-xs text-gray-500 uppercase">({scan.scanner_type.replace(/_/g, ' ')})</span>
                  </div>
                  <div className="flex items-center space-x-3 mt-1">
                    <div className="text-gray-400 text-sm">{scan.stocks_scanned} stocks analyzed</div>
                    <div className="text-financial-blue text-sm font-semibold">{scan.events_detected} events found</div>
                  </div>
                  {scan.status === 'failed' && scan.error_message && (
                    <div className="text-red-400 text-xs mt-1 italic">Error: {scan.error_message}</div>
                  )}
                </div>
                <div className="flex items-center space-x-3">
                  <span className="text-gray-400 text-sm">{(scan.execution_time_ms / 1000).toFixed(1)}s</span>
                  <span className={`px-2 py-1 rounded text-xs font-medium ${scan.status === 'completed'
                    ? 'bg-green-500/20 text-green-400'
                    : scan.status === 'running'
                      ? 'bg-blue-500/20 text-blue-400'
                      : 'bg-red-500/20 text-red-400'
                    }`}>
                    {scan.status}
                  </span>
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-8 text-gray-500">No scan history found</div>
          )}
        </div>
      </Card>
    </div>
  );
};

export default Scanner;