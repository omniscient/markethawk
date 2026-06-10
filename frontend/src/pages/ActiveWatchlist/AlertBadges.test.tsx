import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AlertBadge } from './AlertBadges';
import type { LiveAlert } from '../../hooks/useWatchlistLive';

const recentTimestamp = new Date(Date.now() - 60000).toISOString(); // 1 minute ago

const makeAlert = (overrides: Partial<LiveAlert> = {}): LiveAlert => ({
  type: 'alert',
  symbol: 'AAPL',
  scanner_type: 'live_volume_spike',
  summary: 'Volume spike detected',
  severity: 'high',
  indicators: {},
  timestamp: recentTimestamp,
  ...overrides,
});

describe('AlertBadge', () => {
  it('renders null when alert is null', () => {
    const { container } = render(<AlertBadge alert={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders null when alert is older than 1 hour', () => {
    const oldAlert = makeAlert({
      timestamp: new Date(Date.now() - 3_700_000).toISOString(),
    });
    const { container } = render(<AlertBadge alert={oldAlert} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows "VOL" badge for live_volume_spike scanner type', () => {
    render(<AlertBadge alert={makeAlert({ scanner_type: 'live_volume_spike' })} />);
    expect(screen.getByText('VOL')).toBeInTheDocument();
  });

  it('shows "MOVE" badge for other scanner types', () => {
    render(<AlertBadge alert={makeAlert({ scanner_type: 'pre_market_volume_spike' })} />);
    expect(screen.getByText('MOVE')).toBeInTheDocument();
  });

  it('applies red color classes for high severity', () => {
    const { container } = render(<AlertBadge alert={makeAlert({ severity: 'high' })} />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain('text-red-300');
  });

  it('applies yellow color classes for medium severity', () => {
    const { container } = render(
      <AlertBadge alert={makeAlert({ severity: 'medium' })} />,
    );
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain('text-yellow-300');
  });

  it('applies gray color classes for low severity', () => {
    const { container } = render(
      <AlertBadge alert={makeAlert({ severity: 'low' })} />,
    );
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain('text-gray-400');
  });
});
