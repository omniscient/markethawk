import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import { ScanConfigPanel } from './ScanConfigPanel';

const baseProps = {
  configs: [{ scanner_type: 'pre_market_volume_spike', display_name: 'Pre-Market Spike', description: '' }],
  loadingConfigs: false,
  universes: [{ id: 1, uuid: 'u1', name: 'All Stocks', description: '', criteria: {}, is_active: true, created_at: '' }],
  loadingUniverses: false,
  selectedConfig: 'pre_market_volume_spike',
  onSelectConfig: vi.fn(),
  selectedUniverse: 1,
  onSelectUniverse: vi.fn(),
  scanStartDate: '',
  onScanStartDate: vi.fn(),
  scanEndDate: '',
  onScanEndDate: vi.fn(),
  isScanning: false,
  onRunScan: vi.fn(),
  onCancelScan: vi.fn(),
  statusBlock: undefined,
  scanHistory: [],
  loadingHistory: false,
  scanError: null,
  onDismissError: vi.fn(),
  scannerMutationPending: false,
};

describe('ScanConfigPanel', () => {
  it('renders without crashing', () => {
    renderWithQuery(<ScanConfigPanel {...baseProps} />);
  });

  it('shows the Run Scanner button when not scanning', () => {
    renderWithQuery(<ScanConfigPanel {...baseProps} />);
    expect(screen.getByRole('button', { name: /run scanner/i })).toBeInTheDocument();
  });

  it('Run Scanner button is enabled when a config and universe are selected', () => {
    renderWithQuery(<ScanConfigPanel {...baseProps} />);
    expect(screen.getByRole('button', { name: /run scanner/i })).not.toBeDisabled();
  });

  it('shows Cancel button when isScanning is true', () => {
    renderWithQuery(<ScanConfigPanel {...baseProps} isScanning={true} />);
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('calls onRunScan when Run Scanner is clicked', () => {
    const onRunScan = vi.fn();
    renderWithQuery(<ScanConfigPanel {...baseProps} onRunScan={onRunScan} />);
    fireEvent.click(screen.getByRole('button', { name: /run scanner/i }));
    expect(onRunScan).toHaveBeenCalledOnce();
  });

  it('shows scanError when provided', () => {
    renderWithQuery(<ScanConfigPanel {...baseProps} scanError="Scan failed: network error" />);
    expect(screen.getByText(/scan failed: network error/i)).toBeInTheDocument();
  });
});
