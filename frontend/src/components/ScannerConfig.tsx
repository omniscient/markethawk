import React from 'react';
import { Settings, Info } from 'lucide-react';

interface ScannerConfigProps {
  configs: any[];
  selectedConfig: string;
  onConfigChange: (config: string) => void;
  loading: boolean;
}

const ScannerConfig: React.FC<ScannerConfigProps> = ({
  configs,
  selectedConfig,
  onConfigChange,
  loading
}) => {
  if (loading) {
    return (
      <div className="space-y-4">
        <div className="animate-pulse bg-gray-700 h-10 rounded"></div>
        <div className="animate-pulse bg-gray-700 h-20 rounded"></div>
      </div>
    );
  }

  const currentConfig = configs?.find(c => c.scanner_type === selectedConfig);

  return (
    <div className="space-y-6">
      {/* Scanner Type Selection */}
      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Scanner Type
        </label>
        <select
          value={selectedConfig}
          onChange={(e) => onConfigChange(e.target.value)}
          className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue focus:border-transparent"
        >
          {configs?.map((config) => (
            <option key={config.scanner_type} value={config.scanner_type}>
              {config.name}
            </option>
          ))}
        </select>
      </div>

      {/* Configuration Details */}
      {currentConfig && (
        <div className="space-y-4">
          <div>
            <h4 className="text-lg font-medium text-financial-light mb-2">
              {currentConfig.name}
            </h4>
            <p className="text-gray-400 text-sm">
              {currentConfig.description}
            </p>
          </div>

          {/* Parameters */}
          <div className="bg-gray-800 rounded-lg p-4">
            <h5 className="text-sm font-medium text-gray-300 mb-3 flex items-center">
              <Settings className="h-4 w-4 mr-2" />
              Scanner Parameters
            </h5>
            <div className="grid grid-cols-2 gap-4">
              {Object.entries(currentConfig.parameters || {}).map(([key, value]) => (
                <div key={key}>
                  <label className="block text-xs text-gray-400 mb-1">
                    {key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                  </label>
                  <input
                    type={typeof value === 'number' ? 'number' : 'text'}
                    value={value as any}
                    className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-financial-light"
                    readOnly
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Criteria */}
          <div className="bg-gray-800 rounded-lg p-4">
            <h5 className="text-sm font-medium text-gray-300 mb-3 flex items-center">
              <Info className="h-4 w-4 mr-2" />
              Criteria Logic
            </h5>
            <div className="space-y-2">
              {currentConfig.criteria?.map((criterion: any, index: number) => (
                <div key={index} className="flex items-start space-x-3">
                  <div className="w-2 h-2 bg-financial-blue rounded-full mt-2 flex-shrink-0"></div>
                  <div>
                    <div className="text-sm font-medium text-financial-light">
                      {criterion.name}
                    </div>
                    <div className="text-xs text-gray-400">
                      {criterion.description}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ScannerConfig;