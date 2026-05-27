import React from 'react';
import { Bot, Plus, Loader2 } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import { StrategyRow } from './components';
import type { TradingStrategy } from '../../api/trading';

export interface StrategyPanelProps {
  strategies: TradingStrategy[];
  loadingStrategies: boolean;
  onOpenCreate: () => void;
  onEditStrategy: (s: TradingStrategy) => void;
  onDeleteStrategy: (id: number) => void;
  onToggleStrategy: (id: number, isActive: boolean) => void;
}

export function StrategyPanel({
  strategies, loadingStrategies,
  onOpenCreate, onEditStrategy, onDeleteStrategy, onToggleStrategy,
}: StrategyPanelProps) {
  return (
    <Card title="Trading Strategies" icon={Bot} subtitle="Define risk/reward parameters for automated order execution.">
      {loadingStrategies ? (
        <div className="flex items-center justify-center py-16 text-gray-500">
          <Loader2 className="h-6 w-6 animate-spin mr-2" /> Loading strategies...
        </div>
      ) : !strategies?.length ? (
        <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
          <Bot className="h-12 w-12 text-gray-700" />
          <p className="text-gray-400 font-medium">No strategies yet</p>
          <p className="text-gray-600 text-sm max-w-xs">
            Create a strategy and link it to an alert rule to start auto-trading.
          </p>
          <Button variant="primary" icon={Plus} onClick={onOpenCreate} className="mt-2">
            Create First Strategy
          </Button>
        </div>
      ) : (
        <div className="divide-y divide-gray-800">
          {strategies.map(s => (
            <StrategyRow
              key={s.id}
              strategy={s}
              onEdit={() => onEditStrategy(s)}
              onDelete={() => onDeleteStrategy(s.id)}
              onToggle={() => onToggleStrategy(s.id, s.is_active)}
            />
          ))}
        </div>
      )}
    </Card>
  );
}
