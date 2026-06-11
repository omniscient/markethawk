import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import { AccountPanel } from './AccountPanel';

const baseAccount = {
  connected: true,
  net_liquidation: 50000,
  available_funds: 30000,
  buying_power: 60000,
  open_broker_orders: [],
  error: null,
};

const baseProps = {
  account: baseAccount,
  fetchingAccount: false,
  onRefreshAccount: vi.fn(),
  stats: null,
  config: { AUTO_TRADING_ENABLED: false, PAPER_ACCOUNT_SIZE: 100000 },
  onUpdateConfig: vi.fn(),
};

describe('AccountPanel — not-connected state', () => {
  it('shows not connected message when account.connected is false', () => {
    const props = { ...baseProps, account: { ...baseAccount, connected: false } };
    renderWithQuery(<AccountPanel {...props} />);
    expect(screen.getByText(/IBKR not connected/i)).toBeInTheDocument();
  });

  it('shows error message when account has an error', () => {
    const props = {
      ...baseProps,
      account: { ...baseAccount, connected: false, error: 'Gateway timeout' },
    };
    renderWithQuery(<AccountPanel {...props} />);
    expect(screen.getByText(/Gateway timeout/i)).toBeInTheDocument();
  });

  it('shows not connected when account is null', () => {
    const props = { ...baseProps, account: null };
    renderWithQuery(<AccountPanel {...props} />);
    expect(screen.getByText(/IBKR not connected/i)).toBeInTheDocument();
  });
});

describe('AccountPanel — connected state', () => {
  it('renders without crashing when connected', () => {
    renderWithQuery(<AccountPanel {...baseProps} />);
  });

  it('shows Net Liquidation label', () => {
    renderWithQuery(<AccountPanel {...baseProps} />);
    expect(screen.getByText(/Net Liquidation/i)).toBeInTheDocument();
  });

  it('shows Available Funds label', () => {
    renderWithQuery(<AccountPanel {...baseProps} />);
    expect(screen.getByText(/Available Funds/i)).toBeInTheDocument();
  });

  it('shows Buying Power label', () => {
    renderWithQuery(<AccountPanel {...baseProps} />);
    expect(screen.getByText(/Buying Power/i)).toBeInTheDocument();
  });

  it('formats net_liquidation as USD', () => {
    renderWithQuery(<AccountPanel {...baseProps} />);
    expect(screen.getByText(/\$50,000\.00/)).toBeInTheDocument();
  });

  it('formats available_funds as USD', () => {
    renderWithQuery(<AccountPanel {...baseProps} />);
    expect(screen.getByText(/\$30,000\.00/)).toBeInTheDocument();
  });
});

describe('AccountPanel — 30-Day Breakdown', () => {
  it('does not render 30-Day Breakdown when stats is null', () => {
    renderWithQuery(<AccountPanel {...baseProps} stats={null} />);
    expect(screen.queryByText(/30-Day Breakdown/i)).not.toBeInTheDocument();
  });

  it('does not render 30-Day Breakdown when total_orders is 0', () => {
    const stats = { total_orders: 0, closed_count: 0, by_status: {}, win_rate: null, total_pnl: 0, avg_pnl_per_trade: 0 };
    renderWithQuery(<AccountPanel {...baseProps} stats={stats} />);
    expect(screen.queryByText(/30-Day Breakdown/i)).not.toBeInTheDocument();
  });

  it('shows 30-Day Breakdown when stats has total_orders > 0', () => {
    const stats = {
      total_orders: 5,
      closed_count: 3,
      by_status: { closed: 3, open: 2 },
      win_rate: 66,
      total_pnl: 150.5,
      avg_pnl_per_trade: 30.1,
    };
    renderWithQuery(<AccountPanel {...baseProps} stats={stats} />);
    expect(screen.getByText(/30-Day Breakdown/i)).toBeInTheDocument();
  });
});

describe('AccountPanel — System Config', () => {
  it('shows System Config card', () => {
    renderWithQuery(<AccountPanel {...baseProps} />);
    expect(screen.getByText(/System Config/i)).toBeInTheDocument();
  });

  it('shows Live Trading Enabled label', () => {
    renderWithQuery(<AccountPanel {...baseProps} />);
    expect(screen.getByText(/Live Trading Enabled/i)).toBeInTheDocument();
  });

  it('calls onUpdateConfig when toggle is clicked', () => {
    const onUpdateConfig = vi.fn();
    const props = { ...baseProps, onUpdateConfig };
    renderWithQuery(<AccountPanel {...props} />);
    const toggleBtn = screen.getByRole('button', { name: '' });
    fireEvent.click(toggleBtn);
    expect(onUpdateConfig).toHaveBeenCalledWith({ AUTO_TRADING_ENABLED: true });
  });
});

describe('AccountPanel — Refresh button', () => {
  it('shows Refresh button', () => {
    renderWithQuery(<AccountPanel {...baseProps} />);
    expect(screen.getByRole('button', { name: /Refresh/i })).toBeInTheDocument();
  });

  it('calls onRefreshAccount when Refresh is clicked', () => {
    const onRefreshAccount = vi.fn();
    renderWithQuery(<AccountPanel {...baseProps} onRefreshAccount={onRefreshAccount} />);
    fireEvent.click(screen.getByRole('button', { name: /Refresh/i }));
    expect(onRefreshAccount).toHaveBeenCalledOnce();
  });
});
