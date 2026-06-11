
import {
  Activity, RefreshCw, CheckCircle, AlertCircle,
  Smartphone, Mail, MessageSquare, Webhook,
} from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import type { AlertLog } from '../../api/alerts';

export interface AlertActivityCardProps {
  logs: AlertLog[];
}

export function AlertActivityCard({ logs }: AlertActivityCardProps) {
  return (
    <Card title="Latest Activity" icon={Activity}>
      {logs?.length === 0 ? (
        <div className="text-center py-6">
          <p className="text-sm text-gray-500 italic">No activity yet.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {logs?.slice(0, 5).map(log => (
            <div key={log.id} className="flex items-center justify-between text-xs p-2 rounded hover:bg-gray-800 transition-colors">
              <div className="flex items-center space-x-2">
                <span className={`font-bold ${log.status === 'sent' ? 'text-green-500' : 'text-red-500'}`}>
                  {log.status === 'sent' ? '✓' : '✗'}
                </span>
                <span className="text-white font-medium">{log.ticker}</span>
                <span className="text-gray-500">→</span>
                <span className="text-gray-400 truncate w-24 uppercase font-bold tracking-tighter">{log.channel.replace('_', ' ')}</span>
              </div>
              <span className="text-[10px] text-gray-600 font-mono">
                {new Date(log.delivered_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          ))}
          <div className="pt-2">
            <Button variant="ghost" size="sm" fullWidth className="text-[10px] uppercase font-bold text-gray-500 tracking-widest">
              View Full System Log
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

export interface AlertLogsPanelProps {
  logs: AlertLog[];
}

export function AlertLogsPanel({ logs }: AlertLogsPanelProps) {
  return (
    <>
      <Card title="Delivery Journal" icon={RefreshCw} subtitle="Complete audit trail of notification attempts.">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-gray-700">
                {['Time', 'Ticker', 'Trigger', 'Channel', 'Status', 'Result'].map(h => (
                  <th key={h} className="pb-3 text-sm font-bold text-gray-500 uppercase tracking-widest px-4">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {logs?.map(log => (
                <tr key={log.id} className="group hover:bg-gray-800/50 transition-colors">
                  <td className="py-4 px-4 text-sm text-gray-400 tabular-nums">
                    {new Date(log.delivered_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </td>
                  <td className="py-4 px-4">
                    <span className="text-white font-bold bg-gray-700 px-2 py-1 rounded text-xs">{log.ticker || 'SYS'}</span>
                  </td>
                  <td className="py-4 px-4 text-sm text-gray-300">
                    {log.scanner_type?.replace(/_/g, ' ').toUpperCase() || 'MANUAL TEST'}
                  </td>
                  <td className="py-4 px-4">
                    <span className="text-xs font-medium text-gray-400 uppercase tracking-widest border border-gray-700 px-2 py-0.5 rounded-full inline-flex items-center">
                      {log.channel === 'browser_push' && <Smartphone className="h-3 w-3 mr-1" />}
                      {log.channel === 'email' && <Mail className="h-3 w-3 mr-1" />}
                      {log.channel === 'google_chat' && <MessageSquare className="h-3 w-3 mr-1" />}
                      {log.channel === 'webhook' && <Webhook className="h-3 w-3 mr-1" />}
                      {log.channel}
                    </span>
                  </td>
                  <td className="py-4 px-4">
                    <span className={`text-xs font-bold uppercase tracking-widest inline-flex items-center ${log.status === 'sent' ? 'text-green-500' : 'text-red-500'}`}>
                      {log.status === 'sent'
                        ? <><CheckCircle className="h-3 w-3 mr-1" /> Delivered</>
                        : <><AlertCircle className="h-3 w-3 mr-1" /> Failed</>}
                    </span>
                  </td>
                  <td className="py-4 px-4 text-xs text-gray-500 italic max-w-xs truncate">
                    {log.error_message || 'Successfully dispatched'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
