import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import { ScannerHistoryPanel } from './ScannerHistoryPanel';

vi.mock('../../components/RecentEvents', () => ({ default: () => null }));
vi.mock('../../components/ForceScanDialog', () => ({ default: () => null }));

const idleScanTask = { status: 'idle', done: 0, total: 0, error: null };

const baseProps = {
  symbol: 'TSLA',
  events: [],
  clearConfirmOpen: false,
  onClearConfirmOpen: vi.fn(),
  onClearHistory: vi.fn(),
  clearHistoryPending: false,
  scanDialogOpen: false,
  onScanDialogOpen: vi.fn(),
  scanTask: idleScanTask,
  scanDoneMsg: null,
  onScanSubmit: vi.fn(),
  scanSubmitting: false,
  onHighlightDate: vi.fn(),
};

describe('ScannerHistoryPanel — rendering', () => {
  it('renders without crashing', () => {
    renderWithQuery(<ScannerHistoryPanel {...baseProps} />);
  });

  it('shows the Scanner Event History heading', () => {
    renderWithQuery(<ScannerHistoryPanel {...baseProps} />);
    expect(screen.getByText(/Scanner Event History/i)).toBeInTheDocument();
  });

  it('shows Run Scanner button', () => {
    renderWithQuery(<ScannerHistoryPanel {...baseProps} />);
    expect(screen.getByRole('button', { name: /Run Scanner/i })).toBeInTheDocument();
  });

  it('shows Clear History button', () => {
    renderWithQuery(<ScannerHistoryPanel {...baseProps} />);
    expect(screen.getByRole('button', { name: /Clear History/i })).toBeInTheDocument();
  });
});

describe('ScannerHistoryPanel — Run Scanner disable states', () => {
  it('Run Scanner button is enabled when idle', () => {
    renderWithQuery(<ScannerHistoryPanel {...baseProps} />);
    expect(screen.getByRole('button', { name: /Run Scanner/i })).not.toBeDisabled();
  });

  it('Run Scanner button is disabled when status is connecting', () => {
    const props = { ...baseProps, scanTask: { ...idleScanTask, status: 'connecting' } };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    expect(screen.getByRole('button', { name: /Run Scanner/i })).toBeDisabled();
  });

  it('Run Scanner button is disabled when status is running', () => {
    const props = { ...baseProps, scanTask: { ...idleScanTask, status: 'running' } };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    expect(screen.getByRole('button', { name: /Run Scanner/i })).toBeDisabled();
  });
});

describe('ScannerHistoryPanel — status messages', () => {
  it('shows "Queued" message when status is connecting', () => {
    const props = { ...baseProps, scanTask: { ...idleScanTask, status: 'connecting' } };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    expect(screen.getByText(/Queued/i)).toBeInTheDocument();
  });

  it('shows "Preparing" when running with total === 0', () => {
    const props = { ...baseProps, scanTask: { status: 'running', done: 0, total: 0, error: null } };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    expect(screen.getByText(/Preparing/i)).toBeInTheDocument();
  });

  it('shows progress "done / total" when running with total > 0', () => {
    const props = { ...baseProps, scanTask: { status: 'running', done: 3, total: 10, error: null } };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    expect(screen.getByText(/3 \/ 10 days/i)).toBeInTheDocument();
  });

  it('shows scanDoneMsg when provided', () => {
    const props = { ...baseProps, scanDoneMsg: 'Scan complete! 5 events found.' };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    expect(screen.getByText(/Scan complete! 5 events found\./i)).toBeInTheDocument();
  });

  it('shows "Scan failed" when status is failed', () => {
    const props = { ...baseProps, scanTask: { status: 'failed', done: 0, total: 0, error: 'timeout' } };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    expect(screen.getByText(/Scan failed/i)).toBeInTheDocument();
  });
});

describe('ScannerHistoryPanel — clear confirm dialog', () => {
  it('does not show confirm dialog by default', () => {
    renderWithQuery(<ScannerHistoryPanel {...baseProps} />);
    expect(screen.queryByText(/cannot be undone/i)).not.toBeInTheDocument();
  });

  it('shows confirm dialog when clearConfirmOpen is true', () => {
    const props = { ...baseProps, clearConfirmOpen: true };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    expect(screen.getByText(/cannot be undone/i)).toBeInTheDocument();
  });

  it('shows symbol in confirm dialog', () => {
    const props = { ...baseProps, clearConfirmOpen: true };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    expect(screen.getByText(/TSLA/)).toBeInTheDocument();
  });

  it('calls onClearHistory when "Yes, Clear" is clicked', () => {
    const onClearHistory = vi.fn();
    const props = { ...baseProps, clearConfirmOpen: true, onClearHistory };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /Yes, Clear/i }));
    expect(onClearHistory).toHaveBeenCalledOnce();
  });

  it('calls onClearConfirmOpen(false) when "No, Cancel" is clicked', () => {
    const onClearConfirmOpen = vi.fn();
    const props = { ...baseProps, clearConfirmOpen: true, onClearConfirmOpen };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /No, Cancel/i }));
    expect(onClearConfirmOpen).toHaveBeenCalledWith(false);
  });
});

describe('ScannerHistoryPanel — button callbacks', () => {
  it('calls onScanDialogOpen(true) when Run Scanner is clicked', () => {
    const onScanDialogOpen = vi.fn();
    const props = { ...baseProps, onScanDialogOpen };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /Run Scanner/i }));
    expect(onScanDialogOpen).toHaveBeenCalledWith(true);
  });

  it('calls onClearConfirmOpen(true) when Clear History is clicked', () => {
    const onClearConfirmOpen = vi.fn();
    const props = { ...baseProps, onClearConfirmOpen };
    renderWithQuery(<ScannerHistoryPanel {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /Clear History/i }));
    expect(onClearConfirmOpen).toHaveBeenCalledWith(true);
  });
});
