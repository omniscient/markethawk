import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import Modal from './ui/Modal';
import Button from './ui/Button';
import { createStockUniverse } from '../api/scanner';

interface CreateUniverseModalProps {
    isOpen: boolean;
    onClose: () => void;
}

const CreateUniverseModal: React.FC<CreateUniverseModalProps> = ({ isOpen, onClose }) => {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [criteriaJson, setCriteriaJson] = useState('{\n  "min_market_cap": 1000000000\n}');

    const queryClient = useQueryClient();

    const createMutation = useMutation({
        mutationFn: createStockUniverse,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
            resetForm();
            onClose();
        },
    });

    const resetForm = () => {
        setName('');
        setDescription('');
        setCriteriaJson('{\n  "min_market_cap": 1000000000\n}');
    };

    const handleSubmit = () => {
        try {
            const criteria = JSON.parse(criteriaJson);
            createMutation.mutate({
                name,
                description,
                criteria,
            });
        } catch {
            alert('Invalid JSON in criteria');
        }
    };

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title="Create Stock Universe"
            footer={
                <>
                    <Button variant="ghost" onClick={onClose}>Cancel</Button>
                    <Button
                        variant="primary"
                        loading={createMutation.isPending}
                        onClick={handleSubmit}
                        disabled={!name}
                    >
                        Create Universe
                    </Button>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="block text-sm font-medium text-gray-400 mb-1">Name</label>
                    <input
                        type="text"
                        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-financial-blue"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="e.g., Large Cap Tech"
                    />
                </div>
                <div>
                    <label className="block text-sm font-medium text-gray-400 mb-1">Description</label>
                    <textarea
                        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-financial-blue h-20"
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        placeholder="Optional description..."
                    />
                </div>
                <div>
                    <label className="block text-sm font-medium text-gray-400 mb-1">Criteria (JSON)</label>
                    <textarea
                        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white font-mono text-sm focus:outline-none focus:ring-2 focus:ring-financial-blue h-40"
                        value={criteriaJson}
                        onChange={(e) => setCriteriaJson(e.target.value)}
                    />
                </div>
            </div>
        </Modal>
    );
};

export default CreateUniverseModal;
