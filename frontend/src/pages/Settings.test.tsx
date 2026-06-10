import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import Settings from './Settings';

vi.mock('../api/scanner', () => ({
  syncFundamentals: vi.fn().mockResolvedValue({}),
  syncMetrics: vi.fn().mockResolvedValue({}),
  syncTickerDetails: vi.fn().mockResolvedValue({}),
  stopSync: vi.fn().mockResolvedValue({}),
  fetchStorageStats: vi.fn().mockResolvedValue({ total_rows: 1000, db_size_mb: 50 }),
}));

vi.mock('../api/system', () => ({
  getSystemConfig: vi.fn().mockResolvedValue({ polygon_crawl_delay: '15.0' }),
  updateSystemConfig: vi.fn().mockResolvedValue({ polygon_crawl_delay: '10.0' }),
}));

vi.mock('../components/NewsSettings', () => ({ default: () => <div>NewsSettings</div> }));

describe('Settings page', () => {
  it('renders without crashing', () => {
    renderWithQuery(<Settings />);
  });

  it('shows Market Data Sync section by default', () => {
    renderWithQuery(<Settings />);
    expect(screen.getByText(/Market Data Sync/i)).toBeInTheDocument();
  });

  it('shows News tab button', () => {
    renderWithQuery(<Settings />);
    expect(screen.getByRole('button', { name: /News/i })).toBeInTheDocument();
  });

  it('shows News tab content when News tab is clicked', () => {
    renderWithQuery(<Settings />);
    fireEvent.click(screen.getByRole('button', { name: /News/i }));
    expect(screen.getByText('NewsSettings')).toBeInTheDocument();
  });

  it('shows Global API Speed selector in Data tab', () => {
    renderWithQuery(<Settings />);
    expect(screen.getByText(/Global API Speed/i)).toBeInTheDocument();
  });
});
