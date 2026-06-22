import { ShieldCheck, ShieldAlert, ShieldX, ShieldOff } from 'lucide-react';
import type { QualityGateVerdict } from '../api/scanner';

export const VERDICT_CONFIG: Record<
  QualityGateVerdict,
  { bg: string; border: string; text: string; icon: React.FC<{ className?: string }> }
> = {
  trusted: { bg: 'bg-green-500/10', border: 'border-green-500/30', text: 'text-green-400', icon: ShieldCheck },
  warning: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', icon: ShieldAlert },
  blocked: { bg: 'bg-red-500/10',   border: 'border-red-500/30',   text: 'text-red-400',   icon: ShieldX },
  skipped: { bg: 'bg-gray-500/10',  border: 'border-gray-500/30',  text: 'text-gray-400',  icon: ShieldOff },
};
