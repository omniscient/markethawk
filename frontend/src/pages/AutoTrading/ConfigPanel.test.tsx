import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import { ConfigPanel } from './ConfigPanel';
import type { TradingStrategy } from '../../api/trading';

const baseProps = {
  isOpen: true,
  editingStrategy: null,
  stratForm: {
    name: '',
    description: '',
    is_active: true,
    paper_mode: true,
    requires_approval: false,
    risk_per_trade_pct: 1.0,
    allowed_sessions: [] as string[],
  },
  onStratForm: vi.fn(),
  onSave: vi.fn(),
  onClose: vi.fn(),
  isSaving: false,
};

const minStrategy: TradingStrategy = {
  id: 1,
  name: 'My Strategy',
  description: null,
  is_active: true,
  paper_mode: true,
  requires_approval: false,
  risk_per_trade_pct: 1.0,
  max_position_usd: null,
  max_trades_per_day: 5,
  max_concurrent_positions: 2,
  entry_type: 'market',
  limit_offset_pct: 0,
  stop_pct: 2,
  risk_reward_ratio: 2,
  max_slippage_pct: 0.5,
  allowed_sessions: [],
  direction: 'long_only',
};

describe('ConfigPanel', () => {
  it('renders without crashing', () => {
    renderWithQuery(<ConfigPanel {...baseProps} />);
  });

  it('shows "New Trading Strategy" title for new strategy', () => {
    renderWithQuery(<ConfigPanel {...baseProps} />);
    expect(screen.getByText(/new trading strategy/i)).toBeInTheDocument();
  });

  it('shows strategy name in title when editing', () => {
    renderWithQuery(
      <ConfigPanel
        {...baseProps}
        editingStrategy={minStrategy}
      />
    );
    expect(screen.getByText(/edit strategy — my strategy/i)).toBeInTheDocument();
  });

  it('renders the Strategy Name input field', () => {
    renderWithQuery(<ConfigPanel {...baseProps} />);
    expect(screen.getByPlaceholderText(/2r morning momentum/i)).toBeInTheDocument();
  });

  it('calls onStratForm when the name field changes', () => {
    const onStratForm = vi.fn();
    renderWithQuery(<ConfigPanel {...baseProps} onStratForm={onStratForm} />);
    fireEvent.change(screen.getByPlaceholderText(/2r morning momentum/i), {
      target: { value: 'New Strategy' },
    });
    expect(onStratForm).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'New Strategy' })
    );
  });

  it('calls onSave when Create Strategy button is clicked', () => {
    const onSave = vi.fn();
    renderWithQuery(<ConfigPanel {...baseProps} onSave={onSave} />);
    fireEvent.click(screen.getByRole('button', { name: /create strategy/i }));
    expect(onSave).toHaveBeenCalledOnce();
  });
});
