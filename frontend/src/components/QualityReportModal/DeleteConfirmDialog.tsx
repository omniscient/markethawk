import React from 'react';
import { AlertTriangle, Loader2, Trash2 } from 'lucide-react';
import Button from '../ui/Button';
import type { QualityTickerResult } from '../../api/universe';

interface DeleteConfirmDialogProps {
  pendingDelete: QualityTickerResult;
  deleteError: string | null;
  isPending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const DeleteConfirmDialog: React.FC<DeleteConfirmDialogProps> = ({
  pendingDelete,
  deleteError,
  isPending,
  onConfirm,
  onCancel,
}) => (
  <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-black/60 backdrop-blur-sm">
    <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl p-6 max-w-sm w-full mx-4">
      <div className="flex items-start gap-3 mb-4">
        <AlertTriangle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-financial-light font-semibold">Remove ticker from universe?</p>
          <p className="text-sm text-gray-400 mt-1">
            This will permanently delete{' '}
            <span className="font-mono text-financial-light">{pendingDelete.ticker}</span>'s
            aggregate data (all timespans) and remove it from this universe.
            This cannot be undone.
          </p>
        </div>
      </div>
      {deleteError && (
        <p className="text-xs text-red-400 mb-3">{deleteError}</p>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={isPending}>
          Cancel
        </Button>
        <Button
          variant="ghost"
          className="text-red-400 hover:text-red-300 border border-red-500/30 hover:border-red-400/50"
          icon={isPending ? Loader2 : Trash2}
          onClick={onConfirm}
          disabled={isPending}
        >
          {isPending ? 'Deleting…' : 'Delete'}
        </Button>
      </div>
    </div>
  </div>
);

export default DeleteConfirmDialog;
