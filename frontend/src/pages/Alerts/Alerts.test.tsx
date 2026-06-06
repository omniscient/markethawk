import { vi, describe, it, expect, beforeAll } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import Alerts from './index';

// ChannelConfigPanel reads Notification.permission at render time; jsdom doesn't define it
beforeAll(() => {
  Object.defineProperty(globalThis, 'Notification', {
    value: { permission: 'default' },
    writable: true,
    configurable: true,
  });
});

vi.mock('../../api/alerts', () => ({
  useAlertRules: () => ({ data: [], isLoading: false }),
  useAlertStats: () => ({ data: undefined }),
  useAlertLogs: () => ({ data: [] }),
  useCreateAlertRule: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateAlertRule: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useDeleteAlertRule: () => ({ mutate: vi.fn() }),
  useTestAlertRule: () => ({ mutate: vi.fn() }),
  usePushSubscription: () => ({
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
    isSubscribing: false,
  }),
}));

vi.mock('../../api/trading', () => ({
  useStrategies: () => ({ data: [] }),
}));

describe('Alerts page', () => {
  it('renders without crashing', () => {
    renderWithQuery(<Alerts />);
  });

  it('shows the Alert Center heading', () => {
    renderWithQuery(<Alerts />);
    expect(screen.getByRole('heading', { name: /alert center/i })).toBeInTheDocument();
  });

  it('shows the New Alert Rule button', () => {
    renderWithQuery(<Alerts />);
    expect(screen.getByRole('button', { name: /new alert rule/i })).toBeInTheDocument();
  });
});
