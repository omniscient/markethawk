import { vi, describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import AutoTrading from './index';

vi.mock('../../api/trading', () => ({
  useStrategies: () => ({ data: [], isLoading: false }),
  useCreateStrategy: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useUpdateStrategy: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useDeleteStrategy: () => ({ mutate: vi.fn(), isPending: false }),
  useAutoTradeOrders: () => ({ data: [], isLoading: false }),
  useApproveOrder: () => ({ mutate: vi.fn(), isPending: false }),
  useRejectOrder: () => ({ mutate: vi.fn(), isPending: false }),
  useCancelOrder: () => ({ mutate: vi.fn(), isPending: false }),
  useTradingStats: () => ({ data: undefined }),
  useTradingConfig: () => ({ data: undefined }),
  useUpdateTradingConfig: () => ({ mutate: vi.fn() }),
  useAccountSummary: () => ({ data: undefined, refetch: vi.fn(), isFetching: false }),
}));

describe('AutoTrading page', () => {
  it('renders without crashing', () => {
    renderWithQuery(<AutoTrading />);
  });

  it('shows the Auto Trading heading', () => {
    renderWithQuery(<AutoTrading />);
    expect(screen.getByRole('heading', { name: /auto trading/i })).toBeInTheDocument();
  });

  it('shows the New Strategy button', () => {
    renderWithQuery(<AutoTrading />);
    expect(screen.getByRole('button', { name: /new strategy/i })).toBeInTheDocument();
  });
});
