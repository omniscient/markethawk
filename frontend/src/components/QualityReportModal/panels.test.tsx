import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import GradeBadge, { GRADE_STYLES } from './GradeBadge';
import ScoreBar from './ScoreBar';
import NormalizationProgressPanel from './NormalizationProgressPanel';
import CoverageBreakdown from './CoverageBreakdown';
import TickerRow from './TickerRow';
import DeleteConfirmDialog from './DeleteConfirmDialog';
import QualityOverviewCard from './QualityOverviewCard';
import QualityFiltersBar from './QualityFiltersBar';
import type { QualityTickerResult, CoverageDetail, NormalizationProgress, QualityReport } from '../../api/universe';

vi.mock('../../api/universe', () => ({
  fetchQualityReport: vi.fn().mockResolvedValue(null),
  triggerQualityAnalysis: vi.fn().mockResolvedValue({}),
  triggerNormalization: vi.fn().mockResolvedValue({}),
  deleteTickerAggregates: vi.fn().mockResolvedValue({}),
}));

vi.mock('../Ticker', () => ({
  default: ({ ticker }: { ticker: string }) => <span data-testid="ticker">{ticker}</span>,
}));

const mockTicker: QualityTickerResult = {
  ticker: 'AAPL',
  asset_class: 'us_equity',
  timespan: 'minute',
  multiplier: 1,
  grade: 'A',
  score: 97.5,
  actual_bars: 50000,
  expected_bars: 50000,
  coverage_pct: 100,
  integrity_pct: 99.9,
  continuity_score: 99.8,
  gap_count: 0,
  bad_bar_count: 0,
  duplicate_count: 0,
  first_bar: '2026-01-01T04:00:00Z',
  last_bar: '2026-06-01T20:00:00Z',
  gaps: [],
  coverage_detail: null,
};

const mockCoverageDetail: CoverageDetail = {
  p90_bars_per_day: 390,
  full_day_count: 100,
  stub_day_count: 2,
  partial_day_count: 0,
  holiday_day_count: 3,
  partial_days: [],
};

const mockNormProgress: NormalizationProgress = {
  status: 'running',
  total_combos: 10,
  processed_combos: ['AAPL_minute', 'MSFT_minute'],
  fixes_applied: { deduped: 5, gaps_filled: 12, backfilled: 3 },
  errors: [],
};

const mockReportData: NonNullable<QualityReport['report_data']> = {
  overall_score: 92.5,
  overall_grade: 'A',
  generated_at: '2026-01-01T00:00:00Z',
  ticker_count: 10,
  analyzed_count: 10,
  timespans_analyzed: ['minute', 'day'],
  grade_distribution: { A: 7, B: 2, C: 1 },
  tickers: [mockTicker],
};

// ── GradeBadge ───────────────────────────────────────────────────────────────

describe('GradeBadge', () => {
  it('renders the grade letter', () => {
    renderWithQuery(<GradeBadge grade="A" />);
    expect(screen.getByText('A')).toBeInTheDocument();
  });

  it('applies the correct style for each grade', () => {
    const { container } = renderWithQuery(<GradeBadge grade="F" size="lg" />);
    const badge = container.querySelector('span');
    expect(badge?.className).toContain('text-red-400');
  });

  it('uses fallback style for unknown grade', () => {
    const { container } = renderWithQuery(<GradeBadge grade="Z" />);
    const badge = container.querySelector('span');
    expect(badge?.className).toContain('text-gray-400');
  });

  it('exports GRADE_STYLES with all expected grades', () => {
    expect(Object.keys(GRADE_STYLES)).toEqual(expect.arrayContaining(['A', 'B', 'C', 'D', 'F']));
  });
});

// ── ScoreBar ─────────────────────────────────────────────────────────────────

describe('ScoreBar', () => {
  it('renders the percentage text', () => {
    renderWithQuery(<ScoreBar value={87.5} />);
    expect(screen.getByText('87.5%')).toBeInTheDocument();
  });

  it('sets bar width via inline style', () => {
    const { container } = renderWithQuery(<ScoreBar value={75} />);
    const bar = container.querySelector('[style]');
    expect(bar?.getAttribute('style')).toContain('75%');
  });

  it('uses green color for high scores', () => {
    const { container } = renderWithQuery(<ScoreBar value={97} />);
    const bar = container.querySelector('[class*="bg-green-500"]');
    expect(bar).toBeInTheDocument();
  });

  it('uses red color for low scores', () => {
    const { container } = renderWithQuery(<ScoreBar value={30} />);
    const bar = container.querySelector('[class*="bg-red-500"]');
    expect(bar).toBeInTheDocument();
  });
});

// ── NormalizationProgressPanel ───────────────────────────────────────────────

describe('NormalizationProgressPanel', () => {
  it('renders nothing when status is null', () => {
    const { container } = renderWithQuery(
      <NormalizationProgressPanel status={null} data={null} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders running state with progress info', () => {
    renderWithQuery(
      <NormalizationProgressPanel status="running" data={mockNormProgress} />
    );
    expect(screen.getByText(/Normalizing.*2\/10 combos/)).toBeInTheDocument();
  });

  it('renders complete state', () => {
    const completeData: NormalizationProgress = { ...mockNormProgress, status: 'complete' };
    renderWithQuery(<NormalizationProgressPanel status="complete" data={completeData} />);
    expect(screen.getByText('Normalization complete')).toBeInTheDocument();
  });

  it('renders fix summary when fixes are applied', () => {
    renderWithQuery(<NormalizationProgressPanel status="complete" data={mockNormProgress} />);
    expect(screen.getByText(/12.*bars gap-filled/)).toBeInTheDocument();
  });
});

// ── CoverageBreakdown ─────────────────────────────────────────────────────────

describe('CoverageBreakdown', () => {
  it('renders coverage percentage', () => {
    renderWithQuery(<CoverageBreakdown detail={mockCoverageDetail} coveragePct={98.5} />);
    expect(screen.getByText(/Coverage breakdown.*98\.5%/)).toBeInTheDocument();
  });

  it('renders full day count', () => {
    renderWithQuery(<CoverageBreakdown detail={mockCoverageDetail} coveragePct={98.5} />);
    expect(screen.getByText(/100 full days/)).toBeInTheDocument();
  });

  it('shows all-clear message when no unexplained partials', () => {
    renderWithQuery(<CoverageBreakdown detail={mockCoverageDetail} coveragePct={98.5} />);
    expect(screen.getByText(/All shortened sessions are accounted for/)).toBeInTheDocument();
  });

  it('shows partial days list when present', () => {
    const detailWithPartials: CoverageDetail = {
      ...mockCoverageDetail,
      partial_day_count: 1,
      partial_days: [{ date: '2026-03-15', actual_bars: 200, expected_bars: 390, shortfall: 190 }],
    };
    renderWithQuery(<CoverageBreakdown detail={detailWithPartials} coveragePct={96.0} />);
    expect(screen.getByText('2026-03-15')).toBeInTheDocument();
  });
});

// ── TickerRow ─────────────────────────────────────────────────────────────────

describe('TickerRow', () => {
  it('renders the ticker symbol', () => {
    renderWithQuery(
      <table><tbody><TickerRow result={mockTicker} onDelete={vi.fn()} /></tbody></table>
    );
    expect(screen.getByTestId('ticker')).toHaveTextContent('AAPL');
  });

  it('calls onDelete when trash button is clicked', () => {
    const onDelete = vi.fn();
    renderWithQuery(
      <table><tbody><TickerRow result={mockTicker} onDelete={onDelete} /></tbody></table>
    );
    fireEvent.click(screen.getByTitle('Remove ticker from universe'));
    expect(onDelete).toHaveBeenCalledWith(mockTicker);
  });

  it('shows grade badge', () => {
    renderWithQuery(
      <table><tbody><TickerRow result={mockTicker} onDelete={vi.fn()} /></tbody></table>
    );
    expect(screen.getByText('A')).toBeInTheDocument();
  });
});

// ── DeleteConfirmDialog ───────────────────────────────────────────────────────

describe('DeleteConfirmDialog', () => {
  it('renders the ticker name', () => {
    renderWithQuery(
      <DeleteConfirmDialog
        pendingDelete={mockTicker}
        deleteError={null}
        isPending={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByText('AAPL')).toBeInTheDocument();
  });

  it('calls onCancel when Cancel is clicked', () => {
    const onCancel = vi.fn();
    renderWithQuery(
      <DeleteConfirmDialog
        pendingDelete={mockTicker}
        deleteError={null}
        isPending={false}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it('calls onConfirm when Delete is clicked', () => {
    const onConfirm = vi.fn();
    renderWithQuery(
      <DeleteConfirmDialog
        pendingDelete={mockTicker}
        deleteError={null}
        isPending={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /delete/i }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it('shows error message when deleteError is set', () => {
    renderWithQuery(
      <DeleteConfirmDialog
        pendingDelete={mockTicker}
        deleteError="Something went wrong"
        isPending={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });
});

// ── QualityOverviewCard ───────────────────────────────────────────────────────

describe('QualityOverviewCard', () => {
  it('renders the overall score', () => {
    renderWithQuery(
      <QualityOverviewCard rd={mockReportData} gradeFilter="all" onGradeFilterChange={vi.fn()} />
    );
    expect(screen.getByText('92.5')).toBeInTheDocument();
  });

  it('renders ticker count', () => {
    renderWithQuery(
      <QualityOverviewCard rd={mockReportData} gradeFilter="all" onGradeFilterChange={vi.fn()} />
    );
    expect(screen.getAllByText('10').length).toBeGreaterThanOrEqual(1);
  });

  it('renders grade distribution buttons', () => {
    renderWithQuery(
      <QualityOverviewCard rd={mockReportData} gradeFilter="all" onGradeFilterChange={vi.fn()} />
    );
    const gradeButtons = screen.getAllByRole('button');
    expect(gradeButtons.length).toBeGreaterThanOrEqual(3);
  });

  it('calls onGradeFilterChange when a grade button is clicked', () => {
    const onChange = vi.fn();
    renderWithQuery(
      <QualityOverviewCard rd={mockReportData} gradeFilter="all" onGradeFilterChange={onChange} />
    );
    const aButton = screen.getAllByRole('button').find(b => b.textContent?.includes('7'));
    if (aButton) fireEvent.click(aButton);
    expect(onChange).toHaveBeenCalled();
  });
});

// ── QualityFiltersBar ─────────────────────────────────────────────────────────

describe('QualityFiltersBar', () => {
  it('renders All timespan button', () => {
    renderWithQuery(
      <QualityFiltersBar
        timespanFilter="all"
        onTimespanChange={vi.fn()}
        minScore={0}
        onMinScoreChange={vi.fn()}
        availableTimespans={['minute', 'day']}
        totalCount={10}
        activeCount={7}
      />
    );
    expect(screen.getByText('All')).toBeInTheDocument();
  });

  it('renders available timespan options', () => {
    renderWithQuery(
      <QualityFiltersBar
        timespanFilter="all"
        onTimespanChange={vi.fn()}
        minScore={0}
        onMinScoreChange={vi.fn()}
        availableTimespans={['minute', 'day']}
        totalCount={10}
        activeCount={7}
      />
    );
    expect(screen.getByText('minute')).toBeInTheDocument();
    expect(screen.getByText('day')).toBeInTheDocument();
  });

  it('displays active/total count', () => {
    renderWithQuery(
      <QualityFiltersBar
        timespanFilter="all"
        onTimespanChange={vi.fn()}
        minScore={0}
        onMinScoreChange={vi.fn()}
        availableTimespans={['minute']}
        totalCount={10}
        activeCount={7}
      />
    );
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText(/of 10/)).toBeInTheDocument();
  });

  it('calls onTimespanChange when a timespan is selected', () => {
    const onChange = vi.fn();
    renderWithQuery(
      <QualityFiltersBar
        timespanFilter="all"
        onTimespanChange={onChange}
        minScore={0}
        onMinScoreChange={vi.fn()}
        availableTimespans={['minute']}
        totalCount={10}
        activeCount={10}
      />
    );
    fireEvent.click(screen.getByText('minute'));
    expect(onChange).toHaveBeenCalledWith('minute');
  });
});
