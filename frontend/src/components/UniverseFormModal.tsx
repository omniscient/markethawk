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
                            <label className="block text-xs text-gray-400 mb-1">Max Market Cap</label>
                            <input
                                type="number"
                                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
                                placeholder="Unlimited"
                                onChange={(e) => {
                                    try {
                                        const c = JSON.parse(criteriaJson);
                                        c.max_market_cap = parseFloat(e.target.value);
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
                        {/* Sector Multi-select */}
                        <div className="col-span-2">
                            <label className="block text-xs text-gray-400 mb-2">Sectors</label>
                            <div className="flex flex-wrap gap-2">
                                {['Technology', 'Healthcare', 'Finance', 'Energy', 'Consumer Cyclical', 'Consumer Defensive', 'Industrials', 'Utilities', 'Real Estate', 'Basic Materials', 'Communication Services'].map((sector) => {
                                    const currentSectors = (() => {
                                        try { return JSON.parse(criteriaJson).sector || []; } catch { return []; }
                                    })();
                                    const isSelected = Array.isArray(currentSectors) ? currentSectors.includes(sector) : currentSectors === sector;

                                    return (
                                        <button
                                            key={sector}
                                            type="button"
                                            onClick={() => {
                                                try {
                                                    const c = JSON.parse(criteriaJson);
                                                    let s = c.sector || [];
                                                    if (!Array.isArray(s)) s = [s]; // normalize

                                                    if (s.includes(sector)) {
                                                        s = s.filter((item: string) => item !== sector);
                                                    } else {
                                                        s.push(sector);
                                                    }
                                                    c.sector = s;
                                                    setCriteriaJson(JSON.stringify(c, null, 2));
                                                } catch (err) { }
                                            }}
                                            className={`px-2 py-1 text-xs rounded border ${isSelected
                                                ? 'bg-financial-blue text-white border-financial-blue'
                                                : 'bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-500'
                                                }`}
                                        >
                                            {sector}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        {/* Exchange Multi-select */}
                        <div className="col-span-2 mt-2">
                            <label className="block text-xs text-gray-400 mb-2">Exchanges</label>
                            <div className="flex gap-2">
                                {[
                                    { id: 'XNYS', label: 'NYSE' },
                                    { id: 'XNAS', label: 'NASDAQ' },
                                    { id: 'XASE', label: 'AMEX' }
                                ].map((ex) => {
                                    const currentExchanges = (() => {
                                        try { return JSON.parse(criteriaJson).primary_exchange || []; } catch { return []; }
                                    })();
                                    const isSelected = Array.isArray(currentExchanges) ? currentExchanges.includes(ex.id) : currentExchanges === ex.id;

                                    return (
                                        <button
                                            key={ex.id}
                                            type="button"
                                            onClick={() => {
                                                try {
                                                    const c = JSON.parse(criteriaJson);
                                                    let e = c.primary_exchange || [];
                                                    if (!Array.isArray(e)) e = [e];

                                                    if (e.includes(ex.id)) {
                                                        e = e.filter((item: string) => item !== ex.id);
                                                    } else {
                                                        e.push(ex.id);
                                                    }
                                                    c.primary_exchange = e;
                                                    setCriteriaJson(JSON.stringify(c, null, 2));
                                                } catch (err) { }
                                            }}
                                            className={`px-3 py-1 text-xs rounded border ${isSelected
                                                ? 'bg-financial-blue text-white border-financial-blue'
                                                : 'bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-500'
                                                }`}
                                        >
                                            {ex.label}
                                        </button>
                                    )
                                })}
                            </div>
                        </div>

                        {/* Employee Range */}
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Min Employees</label>
                            <input
                                type="number"
                                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
                                placeholder="0"
                                onChange={(e) => {
                                    try {
                                        const c = JSON.parse(criteriaJson);
                                        c.min_employees = parseFloat(e.target.value);
                                        setCriteriaJson(JSON.stringify(c, null, 2));
                                    } catch (err) { }
                                }}
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Max Employees</label>
                            <input
                                type="number"
                                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
                                placeholder="Unlimited"
                                onChange={(e) => {
                                    try {
                                        const c = JSON.parse(criteriaJson);
                                        c.max_employees = parseFloat(e.target.value);
                                        setCriteriaJson(JSON.stringify(c, null, 2));
                                    } catch (err) { }
                                }}
                            />
                        </div>

                        {/* Shares Range */}
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Min Shares Out</label>
                            <input
                                type="number"
                                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
                                placeholder="0"
                                onChange={(e) => {
                                    try {
                                        const c = JSON.parse(criteriaJson);
                                        c.min_share_class_shares = parseFloat(e.target.value);
                                        setCriteriaJson(JSON.stringify(c, null, 2));
                                    } catch (err) { }
                                }}
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Max Shares Out</label>
                            <input
                                type="number"
                                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
                                placeholder="Unlimited"
                                onChange={(e) => {
                                    try {
                                        const c = JSON.parse(criteriaJson);
                                        c.max_share_class_shares = parseFloat(e.target.value);
                                        setCriteriaJson(JSON.stringify(c, null, 2));
                                    } catch (err) { }
                                }}
                            />
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
