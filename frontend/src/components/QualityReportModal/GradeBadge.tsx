import React from 'react';

export const GRADE_STYLES: Record<string, string> = {
  A: 'bg-green-500/20 text-green-400 border-green-500/30',
  B: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  C: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  D: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  F: 'bg-red-500/20 text-red-400 border-red-500/30',
};

export const GRADE_LABEL: Record<string, string> = {
  A: 'Production-ready',
  B: 'Minor gaps, usable',
  C: 'Significant gaps — use with caution',
  D: 'Major holes — scanner results unreliable',
  F: 'Severely incomplete',
};

interface GradeBadgeProps {
  grade: string;
  size?: 'sm' | 'md' | 'lg';
}

const GradeBadge: React.FC<GradeBadgeProps> = ({ grade, size = 'md' }) => {
  const style = GRADE_STYLES[grade] ?? 'bg-gray-500/20 text-gray-400 border-gray-500/30';
  const sz = size === 'lg' ? 'text-3xl px-4 py-1 font-bold' : size === 'md' ? 'text-sm px-2.5 py-0.5 font-semibold' : 'text-xs px-1.5 py-0.5 font-medium';
  return (
    <span className={`inline-flex items-center justify-center rounded border ${style} ${sz} font-mono`}>
      {grade}
    </span>
  );
};

export default GradeBadge;
