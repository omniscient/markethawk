import { vi, describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import Scanner from './index';

vi.mock('../../api/scanner', () => ({
  fetchScannerConfigs: vi.fn().mockResolvedValue([]),
  fetchStockUniverses: vi.fn().mockResolvedValue([]),
  fetchScannerHistory: vi.fn().mockResolvedValue([]),
  fetchScanStatusBlock: vi.fn().mockResolvedValue(null),
  fetchScannerResults: vi.fn().mockResolvedValue([]),
  fetchScanStatus: vi.fn().mockResolvedValue({ status: 'completed' }),
  handleApiError: vi.fn().mockReturnValue('error'),
  runScanner: vi.fn().mockResolvedValue({ scan_id: '1', task_id: 't1', scanner_type: 'pre_market_volume_spike' }),
  submitReview: vi.fn().mockResolvedValue({}),
}));

vi.mock('../../hooks/useScannerWs', () => ({
  useScannerWs: () => ({ attachWebSocket: vi.fn() }),
}));

describe('Scanner page', () => {
  it('renders without crashing', () => {
    renderWithQuery(<Scanner />);
  });

  it('mounts the ScanConfigPanel with a Run Scanner button', () => {
    renderWithQuery(<Scanner />);
    expect(screen.getByRole('button', { name: /run scanner/i })).toBeInTheDocument();
  });
});
