
import { Smartphone, ShieldCheck, ShieldAlert } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';

export interface ChannelConfigPanelProps {
  hasPushSubscription: boolean | null;
  onSubscribe: () => void;
  onUnsubscribe: () => void;
  isSubscribing: boolean;
}

export function ChannelConfigPanel({
  hasPushSubscription, onSubscribe, onUnsubscribe, isSubscribing,
}: ChannelConfigPanelProps) {
  return (
    <Card
      title="Browser Push"
      icon={Smartphone}
      className="border-blue-500/20 bg-blue-500/[0.02]"
    >
      <div className="space-y-4">
        <p className="text-sm text-gray-400">
          Receive instant notifications on your desktop even when MarketHawk is closed.
        </p>

        {Notification.permission === 'granted' && hasPushSubscription ? (
          <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/20 flex items-start space-x-3">
            <ShieldCheck className="h-5 w-5 text-green-400 flex-shrink-0 mt-0.5" />
            <div>
              <h4 className="text-sm font-bold text-green-400 uppercase tracking-widest">Active</h4>
              <p className="text-xs text-green-400/70 mt-1">This browser is registered for push alerts.</p>
              <button
                onClick={onUnsubscribe}
                className="text-xs font-bold text-gray-500 hover:text-white underline mt-3 uppercase tracking-tighter"
              >
                Unregister Device
              </button>
            </div>
          </div>
        ) : Notification.permission === 'denied' ? (
          <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 flex items-start space-x-3">
            <ShieldAlert className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <h4 className="text-sm font-bold text-red-400 uppercase tracking-widest">Blocked</h4>
              <p className="text-xs text-red-400/70 mt-1">Permission has been denied. Reset site permissions in your browser to enable.</p>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <Button
              variant="primary"
              fullWidth
              onClick={onSubscribe}
              loading={isSubscribing}
            >
              Enable Push Alerts
            </Button>
            <p className="text-[10px] text-gray-500 text-center uppercase font-bold tracking-widest">
              Zero Cost · Privacy First · No Downloads
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}
