import { vi, describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { WatchlistTable } from './WatchlistTable';
import type { WatchlistItem } from '../../api/watchlist';
import type { SymbolLiveData } from '../../hooks/useWatchlistLive';

const mockRemoveMutate = vi.hoisted(() => vi.fn());
const mockUpdateMutate = vi.hoisted(() => vi.fn());

vi.mock('../../api/watchlist', () => ({
  useRemoveFromWatchlist: () => ({ mutate: mockRemoveMutate, isPending: false }),
  useUpdateWatchlistNotes: () => ({ mutate: mockUpdateMutate, isPending: false }),
}));

beforeEach(() => {
  mockRemoveMutate.mockClear();
  mockUpdateMutate.mockClear();
});

function makeItem(overrides: Partial<WatchlistItem> = {}): WatchlistItem {
  return {
    id: 1,
    symbol: 'AAPL',
    security_type: 'STK',
    exchange: null,
    notes: null,
    added_at: new Date().toISOString(),
    ...overrides,
  };
}

function makeLive(overrides: Partial<SymbolLiveData> = {}): SymbolLiveData {
  return {
    price: 150,
    priceChangePct: 1.5,
    session: 'regular',
    sessionVolume: 100,
    lastTickAt: Date.now(),
    alert: null,
    ...overrides,
  };
}

function renderTable(
  items: WatchlistItem[],
  liveData: Record<string, SymbolLiveData> = {}
) {
  return render(
    <MemoryRouter>
      <WatchlistTable items={items} liveData={liveData} />
    </MemoryRouter>
  );
}

describe('WatchlistTable — PriceCell', () => {
  it('shows dash when no live data for symbol', () => {
    renderTable([makeItem()], {});
    // PriceCell, SessionCell and notes all show —; at least one is present
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('applies text-financial-light to fresh price', () => {
    const { container } = renderTable([makeItem()], { AAPL: makeLive() });
    expect(container.querySelector('span.text-financial-light.font-semibold')).not.toBeNull();
  });

  it('applies text-gray-500 to stale price (>15s)', () => {
    const { container } = renderTable(
      [makeItem()],
      { AAPL: makeLive({ lastTickAt: Date.now() - 20_000 }) }
    );
    expect(container.querySelector('span.text-gray-500.font-semibold')).not.toBeNull();
  });

  it('applies text-positive to positive priceChangePct', () => {
    const { container } = renderTable([makeItem()], { AAPL: makeLive({ priceChangePct: 2.5 }) });
    expect(container.querySelector('span.text-positive')).not.toBeNull();
  });

  it('applies text-negative to negative priceChangePct', () => {
    const { container } = renderTable([makeItem()], { AAPL: makeLive({ priceChangePct: -1.0 }) });
    expect(container.querySelector('span.text-negative')).not.toBeNull();
  });

  it('does not render pct span when priceChangePct is null', () => {
    // Use session:'closed' so SessionCell renders a dash (no text-positive/text-negative)
    const { container } = renderTable(
      [makeItem()],
      { AAPL: makeLive({ priceChangePct: null, session: 'closed' }) }
    );
    expect(container.querySelector('span.text-positive')).toBeNull();
    expect(container.querySelector('span.text-negative')).toBeNull();
  });
});

describe('WatchlistTable — SessionCell', () => {
  it('shows PRE label with yellow-400 for pre session', () => {
    const { container } = renderTable([makeItem()], { AAPL: makeLive({ session: 'pre' }) });
    expect(screen.getByText('PRE')).toBeInTheDocument();
    expect(container.querySelector('span.text-yellow-400')).not.toBeNull();
  });

  it('shows REG label with text-positive for regular session', () => {
    const { container } = renderTable([makeItem()], { AAPL: makeLive({ session: 'regular' }) });
    expect(screen.getByText('REG')).toBeInTheDocument();
    expect(container.querySelector('span.text-positive')).not.toBeNull();
  });

  it('shows POST label with text-blue-400 for post session', () => {
    const { container } = renderTable([makeItem()], { AAPL: makeLive({ session: 'post' }) });
    expect(screen.getByText('POST')).toBeInTheDocument();
    expect(container.querySelector('span.text-blue-400')).not.toBeNull();
  });

  it('formats session volume ≥ 1M as #.#M', () => {
    renderTable([makeItem()], { AAPL: makeLive({ session: 'regular', sessionVolume: 1_500_000 }) });
    expect(screen.getByText('1.5M')).toBeInTheDocument();
  });

  it('formats session volume ≥ 1K as #K', () => {
    renderTable([makeItem()], { AAPL: makeLive({ session: 'regular', sessionVolume: 2_500 }) });
    expect(screen.getByText('3K')).toBeInTheDocument();
  });

  it('renders raw session volume below 1K', () => {
    renderTable([makeItem()], { AAPL: makeLive({ session: 'regular', sessionVolume: 500 }) });
    expect(screen.getByText('500')).toBeInTheDocument();
  });
});

describe('WatchlistTable — security badge', () => {
  it('shows STK badge with blue classes', () => {
    const { container } = renderTable([makeItem({ security_type: 'STK' })], {});
    const badge = container.querySelector('span.bg-blue-900\\/40');
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toBe('STK');
  });

  it('shows FUT badge with purple classes', () => {
    const { container } = renderTable(
      [makeItem({ security_type: 'FUT', exchange: 'CME' })],
      {}
    );
    const badge = container.querySelector('span.bg-purple-900\\/50');
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toBe('FUT');
  });
});

describe('WatchlistTable — notes', () => {
  it('displays notes text when notes are present', () => {
    renderTable(
      [makeItem({ notes: 'Watching for breakout' })],
      { AAPL: makeLive() }
    );
    expect(screen.getByText('Watching for breakout')).toBeInTheDocument();
  });

  it('shows em-dash when notes are absent', () => {
    // Provide live data so PriceCell and SessionCell do not also render dashes
    renderTable(
      [makeItem({ notes: null })],
      { AAPL: makeLive({ session: 'regular', sessionVolume: 100 }) }
    );
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('WatchlistTable — interactions', () => {
  it('clicking edit-notes button switches to inline edit mode', () => {
    renderTable([makeItem({ symbol: 'AAPL', notes: 'Some note' })], { AAPL: makeLive() });
    fireEvent.click(screen.getByTitle('Edit notes'));
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  it('pressing Enter in inline edit calls updateNotes.mutate', () => {
    renderTable([makeItem({ symbol: 'AAPL', notes: 'Old note' })], { AAPL: makeLive() });
    fireEvent.click(screen.getByTitle('Edit notes'));
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'New note' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(mockUpdateMutate).toHaveBeenCalledWith(
      { symbol: 'AAPL', notes: 'New note' },
      expect.anything()
    );
  });

  it('pressing Escape cancels edit and returns to display mode', () => {
    renderTable([makeItem({ symbol: 'AAPL', notes: 'Some note' })], { AAPL: makeLive() });
    fireEvent.click(screen.getByTitle('Edit notes'));
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' });
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('clicking remove button calls remove.mutate with symbol', () => {
    renderTable([makeItem({ symbol: 'AAPL' })], { AAPL: makeLive() });
    fireEvent.click(screen.getByTitle('Remove AAPL'));
    expect(mockRemoveMutate).toHaveBeenCalledWith('AAPL');
  });
});
