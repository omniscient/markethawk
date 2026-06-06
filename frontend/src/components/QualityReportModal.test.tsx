import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import QualityReportModal from './QualityReportModal';
import type { StockUniverse } from '../api/scanner';

const mockFetchReport = vi.fn().mockResolvedValue({
  universe_id: 1,
  status: 'complete' as const,
  overall_grade: 'A',
  overall_score: 97.5,
  ticker_count: 5,
  started_at: '2026-01-01T00:00:00Z',
  generated_at: '2026-01-01T00:00:00Z',
  error_message: null,
  report_data: {
    overall_score: 97.5,
    overall_grade: 'A',
    generated_at: '2026-01-01T00:00:00Z',
    ticker_count: 5,
    analyzed_count: 5,
    timespans_analyzed: ['day'],
    grade_distribution: { A: 5 },
    tickers: [],
  },
  normalization_status: null,
  normalization_data: null,
});

vi.mock('../api/scanner', () => ({
  fetchQualityReport: () => mockFetchReport(),
  triggerQualityAnalysis: vi.fn().mockResolvedValue({}),
  triggerNormalization: vi.fn().mockResolvedValue({}),
  deleteTickerAggregates: vi.fn().mockResolvedValue({}),
}));

const mockUniverse: StockUniverse = {
  id: 1,
  uuid: 'test-universe-uuid',
  name: 'Test Universe',
  description: 'Test',
  criteria: {},
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
};

describe('QualityReportModal', () => {
  it('renders nothing when isOpen is false', () => {
    const { container } = renderWithQuery(
      <QualityReportModal isOpen={false} onClose={vi.fn()} universe={mockUniverse} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders the modal title when open', () => {
    renderWithQuery(
      <QualityReportModal isOpen={true} onClose={vi.fn()} universe={mockUniverse} />
    );
    expect(screen.getByText(/data quality/i)).toBeInTheDocument();
  });

  it('renders the grade badge after data loads', async () => {
    renderWithQuery(
      <QualityReportModal isOpen={true} onClose={vi.fn()} universe={mockUniverse} />
    );
    await waitFor(() => {
      expect(screen.getAllByText('A').length).toBeGreaterThan(0);
    });
  });

  it('calls onClose when the close button is clicked', () => {
    const onClose = vi.fn();
    renderWithQuery(
      <QualityReportModal isOpen={true} onClose={onClose} universe={mockUniverse} />
    );
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
