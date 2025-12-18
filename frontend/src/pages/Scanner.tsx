import React, { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
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
import { runScanner, fetchScannerConfigs, fetchStockUniverses, StockUniverse } from '../api/scanner';

const Scanner: React.FC = () => {
  const [isScanning, setIsScanning] = useState(false);
  const [selectedConfig, setSelectedConfig] = useState<string>('pre_market_volume');
  const [selectedUniverse, setSelectedUniverse] = useState<number | null>(null);
  const [scanResults, setScanResults] = useState<any>(null);

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

  // Run scanner mutation
  const scannerMutation = useMutation({
    mutationFn: runScanner,
    onSuccess: (data) => {
      setScanResults(data);
      setIsScanning(false);
    },
    onError: (error) => {
      console.error('Scanner error:', error);
      setIsScanning(false);
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
                <span className="text-financial-light">2 min ago</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Next Run</span>
                <span className="text-financial-light">13 min</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Stocks in Universe</span>
                <span className="text-financial-light">503</span>
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
          <ScannerResults results={scanResults} />
        </div>
      )}

      {/* Historical Results */}
      <Card title="Recent Scan History" icon={Clock as any}>
        <div className="space-y-4">
          {[
            { date: '2024-12-07 09:15', events: 12, status: 'completed', duration: '2.3s' },
            { date: '2024-12-07 09:00', events: 8, status: 'completed', duration: '1.8s' },
            { date: '2024-12-06 16:30', events: 15, status: 'completed', duration: '3.1s' },
            { date: '2024-12-06 16:15', events: 0, status: 'completed', duration: '1.5s' },
          ].map((scan, index) => (
            <div key={index} className="flex items-center justify-between p-4 bg-gray-800 rounded-lg">
              <div>
                <div className="text-financial-light font-medium">{scan.date}</div>
                <div className="text-gray-400 text-sm">{scan.events} events detected</div>
              </div>
              <div className="flex items-center space-x-3">
                <span className="text-gray-400 text-sm">{scan.duration}</span>
                <span className={`px-2 py-1 rounded text-xs font-medium ${scan.status === 'completed'
                  ? 'bg-green-500/20 text-green-400'
                  : 'bg-yellow-500/20 text-yellow-400'
                  }`}>
                  {scan.status}
                </span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};

export default Scanner;