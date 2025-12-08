import React from 'react';
import Modal from './ui/Modal';
import Button from './ui/Button';
import { StockUniverse } from '../api/scanner';

interface UniverseDetailsModalProps {
    isOpen: boolean;
    onClose: () => void;
    universe: StockUniverse | null;
}

const UniverseDetailsModal: React.FC<UniverseDetailsModalProps> = ({
    isOpen,
    onClose,
    universe
}) => {
    if (!universe) return null;

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title={universe.name}
            footer={
                <Button variant="secondary" onClick={onClose}>Close</Button>
            }
        >
            <div className="space-y-6">
                <div>
                    <h4 className="text-sm font-medium text-gray-400 mb-1">Description</h4>
                    <p className="text-financial-light">
                        {universe.description || 'No description provided.'}
                    </p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <h4 className="text-sm font-medium text-gray-400 mb-1">Created At</h4>
                        <p className="text-financial-light">
                            {new Date(universe.created_at).toLocaleString()}
                        </p>
                    </div>
                    <div>
                        <h4 className="text-sm font-medium text-gray-400 mb-1">Status</h4>
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${universe.is_active
                                ? 'bg-green-100 text-green-800'
                                : 'bg-red-100 text-red-800'
                            }`}>
                            {universe.is_active ? 'Active' : 'Inactive'}
                        </span>
                    </div>
                </div>

                <div>
                    <h4 className="text-sm font-medium text-gray-400 mb-2">Criteria</h4>
                    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
                        <pre className="text-xs text-green-400 font-mono overflow-auto max-h-60">
                            {JSON.stringify(universe.criteria, null, 2)}
                        </pre>
                    </div>
                </div>
            </div>
        </Modal>
    );
};

export default UniverseDetailsModal;
