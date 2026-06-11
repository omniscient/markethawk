import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import BackfillPanel from './BackfillPanel';

const mockMutate = vi.hoisted(() => vi.fn());

vi.mock('../../hooks/useScorecard', () => ({
  useBackfillMutation: () => ({
    mutate: mockMutate,
    isPending: false,
    isSuccess: false,
    isError: false,
    data: null,
    error: null,
  }),
}));

describe('BackfillPanel — collapsed state', () => {
  it('renders without crashing', () => {
    renderWithQuery(<BackfillPanel scannerType="pre_market_volume_spike" />);
  });

  it('shows "Backfill Outcomes" toggle button', () => {
    renderWithQuery(<BackfillPanel scannerType="pre_market_volume_spike" />);
    expect(screen.getByRole('button', { name: /Backfill Outcomes/i })).toBeInTheDocument();
  });

  it('does not show Run Backfill button when collapsed', () => {
    renderWithQuery(<BackfillPanel scannerType="pre_market_volume_spike" />);
    expect(screen.queryByRole('button', { name: /Run Backfill/i })).not.toBeInTheDocument();
  });
});

describe('BackfillPanel — expanded state', () => {
  it('shows Run Backfill button after clicking the toggle', () => {
    renderWithQuery(<BackfillPanel scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Backfill Outcomes/i }));
    expect(screen.getByRole('button', { name: /Run Backfill/i })).toBeInTheDocument();
  });

  it('shows Start Date and End Date labels after expanding', () => {
    renderWithQuery(<BackfillPanel scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Backfill Outcomes/i }));
    expect(screen.getByText(/Start Date/i)).toBeInTheDocument();
    expect(screen.getByText(/End Date/i)).toBeInTheDocument();
  });

  it('collapses again when toggle is clicked a second time', () => {
    renderWithQuery(<BackfillPanel scannerType="pre_market_volume_spike" />);
    const toggle = screen.getByRole('button', { name: /Backfill Outcomes/i });
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    expect(screen.queryByRole('button', { name: /Run Backfill/i })).not.toBeInTheDocument();
  });
});

describe('BackfillPanel — backfill action', () => {
  it('calls mutate when Run Backfill is clicked', () => {
    mockMutate.mockClear();
    renderWithQuery(<BackfillPanel scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Backfill Outcomes/i }));
    fireEvent.click(screen.getByRole('button', { name: /Run Backfill/i }));
    expect(mockMutate).toHaveBeenCalledOnce();
    expect(mockMutate).toHaveBeenCalledWith(
      expect.objectContaining({ scanner_type: 'pre_market_volume_spike' }),
    );
  });
});
