
import {
  Bell, ToggleLeft, ToggleRight, Mail, Smartphone, Webhook,
  MessageSquare, Clock, ShieldCheck, Edit2, Trash2, Send, Bot, Loader2,
} from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import type { AlertRule } from '../../api/alerts';

export interface AlertRulesPanelProps {
  rules: AlertRule[];
  isLoadingRules: boolean;
  onOpenCreate: () => void;
  onOpenEdit: (rule: AlertRule) => void;
  onToggle: (rule: AlertRule) => void;
  onDelete: (id: number) => void;
  onTest: (id: number) => void;
}

const getSeverityColor = (sev: string) => {
  switch (sev) {
    case 'high':   return 'text-red-400 bg-red-400/10 border-red-400/20';
    case 'medium': return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20';
    case 'low':    return 'text-blue-400 bg-blue-400/10 border-blue-400/20';
    default:       return 'text-gray-400 bg-gray-400/10 border-gray-400/20';
  }
};

export function AlertRulesPanel({
  rules, isLoadingRules, onOpenCreate, onOpenEdit, onToggle, onDelete, onTest,
}: AlertRulesPanelProps) {
  return (
    <Card title="Alert Rules" icon={ShieldCheck} subtitle="Strategic rules determining when to notify you.">
      {isLoadingRules ? (
        <div className="py-12 flex justify-center">
          <Loader2 className="h-8 w-8 text-blue-500 animate-spin" />
        </div>
      ) : rules?.length === 0 ? (
        <div className="py-12 text-center">
          <div className="mb-4 inline-flex p-4 bg-gray-800 rounded-full">
            <Bell className="h-8 w-8 text-gray-600" />
          </div>
          <h3 className="text-lg font-medium text-white">No rules configured</h3>
          <p className="text-gray-500 mt-1">Create your first rule to start getting notified.</p>
          <Button variant="secondary" className="mt-4" onClick={onOpenCreate}>
            Set up your first rule
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          {rules?.map((rule) => (
            <div
              key={rule.id}
              className="p-5 bg-gray-800/50 border border-gray-700/50 rounded-xl hover:border-gray-600 transition-all group"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start space-x-4">
                  <button onClick={() => onToggle(rule)} className="mt-1 transition-colors outline-none">
                    {rule.is_active
                      ? <ToggleRight className="h-8 w-8 text-blue-500" />
                      : <ToggleLeft className="h-8 w-8 text-gray-600" />}
                  </button>
                  <div>
                    <h3 className={`text-lg font-bold transition-colors ${rule.is_active ? 'text-white' : 'text-gray-500'}`}>
                      {rule.name}
                    </h3>
                    <div className="flex flex-wrap items-center gap-2 mt-2">
                      {rule.scanner_types.length === 0 ? (
                        <span className="text-xs px-2 py-0.5 rounded border border-blue-500/30 bg-blue-500/10 text-blue-300 font-medium">
                          ALL SCANNERS
                        </span>
                      ) : (
                        rule.scanner_types.map(t => (
                          <span key={t} className="text-xs px-2 py-0.5 rounded border border-gray-600 bg-gray-700 text-gray-300 font-medium uppercase tracking-wider">
                            {t.replace(/_/g, ' ')}
                          </span>
                        ))
                      )}
                      <span className={`text-xs px-2 py-0.5 rounded border font-bold uppercase ${getSeverityColor(rule.severity_filter)}`}>
                        {rule.severity_filter}
                      </span>
                    </div>
                    <div className="flex items-center space-x-4 mt-3">
                      <div className="flex items-center -space-x-1">
                        {rule.channels.includes('browser_push') && <Smartphone className="h-4 w-4 text-blue-400 bg-gray-800 border border-gray-700 p-0.5 rounded-full z-30" />}
                        {rule.channels.includes('email') && <Mail className="h-4 w-4 text-purple-400 bg-gray-800 border border-gray-700 p-0.5 rounded-full z-20" />}
                        {rule.channels.includes('google_chat') && <MessageSquare className="h-4 w-4 text-green-400 bg-gray-800 border border-gray-700 p-0.5 rounded-full z-10" />}
                        {rule.channels.includes('webhook') && <Webhook className="h-4 w-4 text-amber-400 bg-gray-800 border border-gray-700 p-0.5 rounded-full z-0" />}
                      </div>
                      <span className="text-xs text-gray-500 font-medium flex items-center">
                        <Clock className="h-3 w-3 mr-1" />
                        {rule.cooldown_minutes}m cooldown
                      </span>
                      {rule.auto_trade && (
                        <span className="text-xs font-bold uppercase px-2 py-0.5 rounded border text-financial-blue bg-financial-blue/10 border-financial-blue/20 flex items-center gap-1">
                          <Bot className="h-3 w-3" /> Auto-Trade
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center space-x-1 opacity-10 group-hover:opacity-100 transition-opacity">
                  <Button
                    variant="ghost" size="sm" icon={Send} title="Send Test"
                    onClick={() => {
                      if (window.confirm(`Send a test notification for "${rule.name}"?`)) {
                        onTest(rule.id);
                      }
                    }}
                  />
                  <Button variant="ghost" size="sm" icon={Edit2} onClick={() => onOpenEdit(rule)} />
                  <Button
                    variant="ghost" size="sm" icon={Trash2}
                    onClick={() => onDelete(rule.id)}
                    className="text-red-500 hover:text-red-400 hover:bg-red-500/10"
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
