import { vi, describe, it, expect, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import EdgeExplorer from './EdgeExplorer';

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  fetchScannerConfigs: vi.fn(),
  getSignalQualityDistribution: vi.fn(),
  fetchCorrelations: vi.fn(),
  triggerAnalysis: vi.fn(),
  fetchExplanationTraits: vi.fn(),
  fetchExplanationArchetypes: vi.fn(),
  fetchEdgeDecay: vi.fn(),
}));

vi.mock('../api/client', () => ({
  apiClient: { get: mocks.apiGet },
}));

vi.mock('../api/scanner', () => ({
  fetchScannerConfigs: (...args: unknown[]) => mocks.fetchScannerConfigs(...args),
  getSignalQualityDistribution: (...args: unknown[]) => mocks.getSignalQualityDistribution(...args),
}));

vi.mock('../api/analysis', () => ({
  fetchCorrelations: (...args: unknown[]) => mocks.fetchCorrelations(...args),
  triggerAnalysis: (...args: unknown[]) => mocks.triggerAnalysis(...args),
}));

vi.mock('../api/outcomes', () => ({
  fetchExplanationTraits: (...args: unknown[]) => mocks.fetchExplanationTraits(...args),
  fetchExplanationArchetypes: (...args: unknown[]) => mocks.fetchExplanationArchetypes(...args),
  fetchEdgeDecay: (...args: unknown[]) => mocks.fetchEdgeDecay(...args),
}));

vi.mock('recharts', () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const noop = () => null;
  return {
    ResponsiveContainer: passthrough,
    ScatterChart: passthrough,
    Scatter: passthrough,
    AreaChart: passthrough,
    Area: noop,
    ComposedChart: passthrough,
    Bar: noop,
    Line: noop,
    XAxis: noop,
    YAxis: noop,
    CartesianGrid: noop,
    Tooltip: noop,
    ZAxis: noop,
    Cell: noop,
    Legend: noop,
  };
});

const scannerConfig = {
  scanner_type: 'pre_market_volume_spike',
  name: 'Pre Market Volume Spike',
};

const traitResponse = {
  event_count: 12,
  filters: {
    scanner_type: 'pre_market_volume_spike',
    start_date: null,
    end_date: null,
    severity: null,
    min_sample_size: 5,
  },
  traits: [
    {
      trait_type: 'criterion_passed',
      trait_key: 'premarket.volume_spike',
      trait_label: 'Volume Spike',
      sample_size: 8,
      event_ids: [1, 2],
      win_rate_pct: 75,
      follow_through_rate_pct: 70,
      avg_mfe_pct: 5.5,
      avg_mae_pct: 1.1,
      win_rate_ci_95_pct: { lower: 40, upper: 90 },
      warnings: [],
    },
    {
      trait_type: 'warning',
      trait_key: 'missing_float',
      trait_label: 'Missing Float',
      sample_size: 1,
      event_ids: [3],
      win_rate_pct: 0,
      follow_through_rate_pct: 0,
      avg_mfe_pct: 0.7,
      avg_mae_pct: 3.2,
      win_rate_ci_95_pct: { lower: 0, upper: 80 },
      warnings: [{ code: 'weak_sample_size', message: 'Only 1 events matched this trait.' }],
    },
    {
      trait_type: 'confidence_input',
      trait_key: 'signal_quality_score:high',
      trait_label: 'signal_quality_score = high',
      sample_size: 6,
      event_ids: [4, 5],
      win_rate_pct: 66.67,
      follow_through_rate_pct: 60,
      avg_mfe_pct: 4.2,
      avg_mae_pct: 1.5,
      win_rate_ci_95_pct: { lower: 25, upper: 90 },
      warnings: [],
    },
  ],
};

const archetypeResponse = {
  analysis_run_id: 10,
  scanner_type: 'pre_market_volume_spike',
  event_count: 12,
  filters: traitResponse.filters,
  warnings: [],
  archetypes: [
    {
      cluster_id: 100,
      cluster_index: 0,
      label: 'Volume Spike / Positive Outcomes',
      sample_size: 8,
      event_ids: [1, 2],
      centroid: {},
      return_profile: { sample_size: 8, win_rate_pct: 75, avg_mfe_pct: 5.5 },
      warnings: [],
    },
    {
      cluster_id: 101,
      cluster_index: 1,
      label: 'Missing Float / Weak Outcomes',
      sample_size: 1,
      event_ids: [3],
      centroid: {},
      return_profile: { sample_size: 1, win_rate_pct: 0, avg_mfe_pct: 0.7 },
      warnings: [{ code: 'weak_archetype_sample', message: 'Only 1 events matched this archetype.' }],
    },
  ],
};

const edgeDecay = [
  { period: '2026-W27', win_rate: 75, avg_mfe: 5.5, avg_mae: 1.1, sample_size: 8 },
];

beforeEach(() => {
  vi.clearAllMocks();
  mocks.fetchScannerConfigs.mockResolvedValue([scannerConfig]);
  mocks.getSignalQualityDistribution.mockResolvedValue({ deciles: [], signal_ranker_version: 'test' });
  mocks.fetchCorrelations.mockResolvedValue(null);
  mocks.triggerAnalysis.mockResolvedValue({ task_id: 'task-1' });
  mocks.fetchExplanationTraits.mockResolvedValue(traitResponse);
  mocks.fetchExplanationArchetypes.mockResolvedValue(archetypeResponse);
  mocks.fetchEdgeDecay.mockResolvedValue(edgeDecay);
  mocks.apiGet.mockImplementation((url: string) => {
    if (url.startsWith('/scanner/edge-stats')) {
      return Promise.resolve({
        data: [{ label: 'Jul 2026', event_count: 2, avg_gap_pct: 4, avg_fade_pct: -1, avg_day_range_pct: 6, avg_rel_vol: 3 }],
      });
    }
    if (url.startsWith('/scanner/edge-distribution')) {
      return Promise.resolve({ data: { events: [] } });
    }
    return Promise.resolve({ data: [] });
  });
});

describe('EdgeExplorer explanation intelligence', () => {
  it('prompts for a strategy before loading explanation filters', async () => {
    renderWithQuery(<EdgeExplorer />);

    expect(await screen.findByText(/Select a strategy to research edge/i)).toBeInTheDocument();
    expect(mocks.fetchExplanationTraits).not.toHaveBeenCalled();
    expect(mocks.fetchExplanationArchetypes).not.toHaveBeenCalled();
  });

  it('renders trait, warning, confidence, archetype, and edge decay analysis', async () => {
    renderWithQuery(<EdgeExplorer />);

    await screen.findByRole('option', { name: /Pre Market Volume Spike/i });
    fireEvent.change(screen.getByLabelText(/Strategy filter/i), {
      target: { value: 'pre_market_volume_spike' },
    });

    expect(await screen.findByText(/^Volume Spike$/i)).toBeInTheDocument();
    expect(screen.getByText(/^Missing Float$/i)).toBeInTheDocument();
    expect(screen.getByText(/^signal_quality_score = high$/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Volume Spike \/ Positive Outcomes/i).length).toBeGreaterThan(1);
    expect(screen.getByText(/Only 1 events matched this trait/i)).toBeInTheDocument();
    expect(screen.getByText(/Only 1 events matched this archetype/i)).toBeInTheDocument();
    expect(screen.getByText(/Scanner Edge Decay/i)).toBeInTheDocument();
    expect(mocks.fetchEdgeDecay).toHaveBeenCalledWith('pre_market_volume_spike', { period: 'monthly' });
  });

  it('filters visible performance rows by selected trait and archetype', async () => {
    renderWithQuery(<EdgeExplorer />);

    await screen.findByRole('option', { name: /Pre Market Volume Spike/i });
    fireEvent.change(screen.getByLabelText(/Strategy filter/i), {
      target: { value: 'pre_market_volume_spike' },
    });
    await screen.findByText(/^Volume Spike$/i);

    fireEvent.change(screen.getByLabelText(/Explanation trait filter/i), {
      target: { value: 'warning:missing_float' },
    });
    fireEvent.change(screen.getByLabelText(/Signal archetype filter/i), {
      target: { value: '101' },
    });

    expect(screen.getByText(/^Missing Float$/i)).toBeInTheDocument();
    expect(screen.queryByText(/^Volume Spike$/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/Missing Float \/ Weak Outcomes/i).length).toBeGreaterThan(1);
    expect(screen.getAllByText(/Volume Spike \/ Positive Outcomes/i)).toHaveLength(1);
  });
});
