import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import { OrdersPanel } from './OrdersPanel';
import type { AutoTradeOrder } from '../../api/trading';

const baseProps = {
  orders: [],
  loadingOrders: false,
  orderFilter: '',
  onOrderFilter: vi.fn(),
  strategies: [],
  onApprove: vi.fn(),
  onReject: vi.fn(),
  onCancel: vi.fn(),
};

const makeOrder = (overrides: Partial<AutoTradeOrder> = {}): AutoTradeOrder => ({
  id: 1,
  alert_rule_id: null,
  scanner_event_id: null,
  trading_strategy_id: null,
  symbol: 'AAPL',
  side: 'long',
  event_date: '2026-01-01',
  status: 'open',
  rejection_reason: null,
  trigger_price: 150.0,
  entry_price_target: 150.5,
  calculated_stop: 148.0,
  calculated_target: 155.0,
  quantity: 10,
  risk_amount_usd: 150.0,
  is_paper: true,
  broker_order_id: null,
  broker_stop_id: null,
  broker_target_id: null,
  fill_price: 150.25,
  filled_at: null,
  exit_price: null,
  exited_at: null,
  exit_reason: null,
  trade_id: null,
  ...overrides,
});

describe('OrdersPanel — filter buttons', () => {
  it('renders without crashing', () => {
    renderWithQuery(<OrdersPanel {...baseProps} />);
  });

  it('shows the All filter button', () => {
    renderWithQuery(<OrdersPanel {...baseProps} />);
    expect(screen.getByRole('button', { name: /^All$/i })).toBeInTheDocument();
  });

  it('shows the pending_approval filter button', () => {
    renderWithQuery(<OrdersPanel {...baseProps} />);
    expect(screen.getByRole('button', { name: /pending_approval/i })).toBeInTheDocument();
  });

  it('shows the closed filter button', () => {
    renderWithQuery(<OrdersPanel {...baseProps} />);
    expect(screen.getByRole('button', { name: /^closed$/i })).toBeInTheDocument();
  });

  it('calls onOrderFilter with empty string when All is clicked', () => {
    const onOrderFilter = vi.fn();
    renderWithQuery(<OrdersPanel {...baseProps} onOrderFilter={onOrderFilter} />);
    fireEvent.click(screen.getByRole('button', { name: /^All$/i }));
    expect(onOrderFilter).toHaveBeenCalledWith('');
  });

  it('calls onOrderFilter with correct value when a status filter is clicked', () => {
    const onOrderFilter = vi.fn();
    renderWithQuery(<OrdersPanel {...baseProps} onOrderFilter={onOrderFilter} />);
    fireEvent.click(screen.getByRole('button', { name: /^closed$/i }));
    expect(onOrderFilter).toHaveBeenCalledWith('closed');
  });

  it('active filter button has financial-blue styling', () => {
    const props = { ...baseProps, orderFilter: 'closed' };
    renderWithQuery(<OrdersPanel {...props} />);
    const closedBtn = screen.getByRole('button', { name: /^closed$/i });
    expect(closedBtn.className).toContain('bg-financial-blue');
  });

  it('inactive filter buttons do not have financial-blue background', () => {
    const props = { ...baseProps, orderFilter: 'closed' };
    renderWithQuery(<OrdersPanel {...props} />);
    const allBtn = screen.getByRole('button', { name: /^All$/i });
    expect(allBtn.className).not.toContain('bg-financial-blue');
  });
});

describe('OrdersPanel — order list states', () => {
  it('shows loading spinner when loadingOrders is true', () => {
    renderWithQuery(<OrdersPanel {...baseProps} loadingOrders={true} />);
    expect(screen.getByText(/Loading orders/i)).toBeInTheDocument();
  });

  it('shows "No orders found" when orders is empty and not loading', () => {
    renderWithQuery(<OrdersPanel {...baseProps} />);
    expect(screen.getByText(/No orders found/i)).toBeInTheDocument();
  });

  it('shows order symbol when orders are provided', () => {
    const props = { ...baseProps, orders: [makeOrder({ symbol: 'TSLA' })] };
    renderWithQuery(<OrdersPanel {...props} />);
    expect(screen.getByText('TSLA')).toBeInTheDocument();
  });
});
