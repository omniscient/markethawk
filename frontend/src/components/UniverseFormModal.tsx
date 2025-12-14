import React, { useState, useEffect } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import Modal from './ui/Modal';
import Button from './ui/Button';
import { createStockUniverse, updateStockUniverse, StockUniverse } from '../api/scanner';

interface UniverseFormModalProps {
    isOpen: boolean;
    onClose: () => void;
    initialData?: StockUniverse | null;
}

const UniverseFormModal: React.FC<UniverseFormModalProps> = ({
    isOpen,
    onClose,
    initialData
}) => {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [criteriaJson, setCriteriaJson] = useState('{\n  "min_market_cap": 1000000000\n}');

    const queryClient = useQueryClient();
    const isEditing = !!initialData;

    useEffect(() => {
        if (initialData) {
            setName(initialData.name);
            setDescription(initialData.description || '');
            setCriteriaJson(JSON.stringify(initialData.criteria, null, 2));
        } else {
            resetForm();
        }
    }, [initialData, isOpen]);

    const createMutation = useMutation({
        mutationFn: createStockUniverse,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
            resetForm();
            onClose();
        },
    });

    const updateMutation = useMutation({
        mutationFn: (data: { id: number; universe: any }) =>
            updateStockUniverse(data.id, data.universe),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
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

            if (isEditing && initialData) {
                updateMutation.mutate({
                    id: initialData.id,
                    universe: {
                        name,
                        description,
                        criteria,
                    }
                });
            } else {
                createMutation.mutate({
                    name,
                    description,
                    criteria,
                });
            }
        } catch (e) {
            alert('Invalid JSON in criteria');
        }
    };

    const isLoading = createMutation.isPending || updateMutation.isPending;

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title={isEditing ? "Edit Stock Universe" : "Create Stock Universe"}
            footer={
                <>
                    <Button variant="ghost" onClick={onClose}>Cancel</Button>
                    <Button
                        variant="primary"
                        loading={isLoading}
                        onClick={handleSubmit}
                        disabled={!name}
                    >
                        {isEditing ? "Update Universe" : "Create Universe"}
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

                <div className="border-t border-gray-700 pt-4">
                    <h4 className="text-sm font-medium text-financial-light mb-3">Screening Criteria</h4>

                    <div className="grid grid-cols-2 gap-4 mb-4">
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Min Market Cap</label>
                            <input
                                type="number"
                                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
                                placeholder="1000000000"
                                onChange={(e) => {
                                    try {
                                        const c = JSON.parse(criteriaJson);
                                        c.min_market_cap = parseFloat(e.target.value);
                                        setCriteriaJson(JSON.stringify(c, null, 2));
                                    } catch (err) { }
                                }}
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Min Volume</label>
                            <input
                                type="number"
                                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
                                placeholder="500000"
                                onChange={(e) => {
                                    try {
                                        const c = JSON.parse(criteriaJson);
                                        c.min_volume = parseFloat(e.target.value);
                                        setCriteriaJson(JSON.stringify(c, null, 2));
                                    } catch (err) { }
                                }}
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Sector</label>
                            <select
                                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
                                onChange={(e) => {
                                    try {
                                        const c = JSON.parse(criteriaJson);
                                        c.sector = e.target.value;
                                        setCriteriaJson(JSON.stringify(c, null, 2));
                                    } catch (err) { }
                                }}
                            >
                                <option value="">Any</option>
                                <option value="Technology">Technology</option>
                                <option value="Healthcare">Healthcare</option>
                                <option value="Finance">Finance</option>
                                <option value="Energy">Energy</option>
                            </select>
                        </div>
                        <div className="flex items-center pt-4">
                            <label className="flex items-center space-x-2 cursor-pointer">
                                <input
                                    type="checkbox"
                                    className="form-checkbox text-financial-blue rounded bg-gray-800 border-gray-700"
                                    onChange={(e) => {
                                        try {
                                            const c = JSON.parse(criteriaJson);
                                            c.price_above_sma50 = e.target.checked;
                                            setCriteriaJson(JSON.stringify(c, null, 2));
                                        } catch (err) { }
                                    }}
                                />
                                <span className="text-sm text-gray-300">Price &gt; SMA 50</span>
                            </label>
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-400 mb-1">Raw Criteria (JSON)</label>
                        <textarea
                            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white font-mono text-sm focus:outline-none focus:ring-2 focus:ring-financial-blue h-32"
                            value={criteriaJson}
                            onChange={(e) => setCriteriaJson(e.target.value)}
                        />
                    </div>
                </div>
            </div>
        </Modal>
    );
};

export default UniverseFormModal;
