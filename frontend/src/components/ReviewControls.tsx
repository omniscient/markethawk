import React, { useState } from 'react';
import { ThumbsUp, ThumbsDown, HelpCircle, Check, X, Wrench } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { submitReview, SignalReview, RejectionReason } from '../api/scanner';

interface ReviewControlsProps {
  eventUuid: string;
  latestReview: SignalReview | null | undefined;
}

const REJECTION_REASONS: { value: RejectionReason; label: string }[] = [
  { value: 'too_late', label: 'Too Late' },
  { value: 'noise', label: 'Noise' },
  { value: 'stale_data', label: 'Stale Data' },
  { value: 'split_artifact', label: 'Split Artifact' },
];

const ReviewControls: React.FC<ReviewControlsProps> = ({ eventUuid, latestReview }) => {
  const queryClient = useQueryClient();
  const [showRejectPopover, setShowRejectPopover] = useState(false);
  const [rejectReason, setRejectReason] = useState<RejectionReason>('noise');
  const [rejectNotes, setRejectNotes] = useState('');
  const [editing, setEditing] = useState(false);

  const mutation = useMutation({
    mutationFn: (payload: { verdict: string; reject_reason?: string | null; notes?: string | null }) =>
      submitReview(eventUuid, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scannerResults'] });
      queryClient.invalidateQueries({ queryKey: ['reviewStats'] });
      setShowRejectPopover(false);
      setEditing(false);
    },
  });

  const handleConfirm = (e: React.MouseEvent) => {
    e.stopPropagation();
    mutation.mutate({ verdict: 'confirmed' });
  };

  const handleUncertain = (e: React.MouseEvent) => {
    e.stopPropagation();
    mutation.mutate({ verdict: 'uncertain' });
  };

  const handleRejectClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setShowRejectPopover(true);
  };

  const handleRejectSubmit = (e: React.MouseEvent) => {
    e.stopPropagation();
    mutation.mutate({
      verdict: 'rejected',
      reject_reason: rejectReason,
      notes: rejectNotes || null,
    });
  };

  const showButtons = !latestReview || editing;

  if (!showButtons && latestReview) {
    const badgeConfig: Record<string, { icon: React.ElementType; color: string; title: string }> = {
      confirmed: { icon: Check, color: 'text-green-400 bg-green-500/20 border-green-500/30', title: 'Confirmed' },
      rejected: { icon: X, color: 'text-red-400 bg-red-500/20 border-red-500/30', title: `Rejected: ${latestReview.reject_reason}` },
      uncertain: { icon: HelpCircle, color: 'text-gray-400 bg-gray-500/20 border-gray-500/30', title: 'Uncertain' },
      enhanced: { icon: Wrench, color: 'text-blue-400 bg-blue-500/20 border-blue-500/30', title: 'Enhanced' },
    };
    const cfg = badgeConfig[latestReview.verdict] || badgeConfig.uncertain;
    const Icon = cfg.icon;

    return (
      <button
        onClick={(e) => { e.stopPropagation(); setEditing(true); }}
        className={`inline-flex items-center px-1.5 py-0.5 rounded border text-xs ${cfg.color} hover:opacity-80 transition-opacity`}
        title={cfg.title}
      >
        <Icon className="h-3 w-3" />
      </button>
    );
  }

  return (
    <div className="relative flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
      <button
        onClick={handleConfirm}
        disabled={mutation.isPending}
        className="p-1 rounded hover:bg-green-500/20 text-gray-500 hover:text-green-400 transition-colors"
        title="Confirm"
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </button>
      <button
        onClick={handleRejectClick}
        disabled={mutation.isPending}
        className="p-1 rounded hover:bg-red-500/20 text-gray-500 hover:text-red-400 transition-colors"
        title="Reject"
      >
        <ThumbsDown className="h-3.5 w-3.5" />
      </button>
      <button
        onClick={handleUncertain}
        disabled={mutation.isPending}
        className="p-1 rounded hover:bg-gray-500/20 text-gray-500 hover:text-gray-300 transition-colors"
        title="Uncertain"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>

      {showRejectPopover && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-gray-800 border border-gray-700 rounded-lg shadow-xl p-3 w-56">
          <label className="block text-[10px] font-bold text-gray-500 uppercase mb-1">Reason</label>
          <select
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value as RejectionReason)}
            className="w-full px-2 py-1 bg-gray-900 border border-gray-700 rounded text-sm text-financial-light mb-2"
            onClick={(e) => e.stopPropagation()}
          >
            {REJECTION_REASONS.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
          <label className="block text-[10px] font-bold text-gray-500 uppercase mb-1">Notes</label>
          <textarea
            value={rejectNotes}
            onChange={(e) => setRejectNotes(e.target.value)}
            className="w-full px-2 py-1 bg-gray-900 border border-gray-700 rounded text-sm text-financial-light mb-2 resize-none"
            rows={2}
            placeholder="Optional notes..."
            onClick={(e) => e.stopPropagation()}
          />
          <div className="flex gap-2">
            <button
              onClick={handleRejectSubmit}
              disabled={mutation.isPending}
              className="flex-1 px-2 py-1 bg-red-600 text-white text-xs font-bold rounded hover:bg-red-500"
            >
              Reject
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setShowRejectPopover(false); }}
              className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded hover:bg-gray-600"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ReviewControls;
