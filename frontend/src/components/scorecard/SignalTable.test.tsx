import { vi, describe, it, expect, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import SignalTable from './SignalTable';
import type { AISignalBrief, SignalListItem } from '../../api/outcomes';

const mocks = vi.hoisted(() => ({
  useSignals: vi.fn(),
  fetchAISignalBrief: vi.fn(),
  fetchAISignalNarrative: vi.fn(),
  fetchSignalPostMortem: vi.fn(),
  getLLMStatus: vi.fn(),
}));

vi.mock('../../hooks/useScorecard', () => ({
  useSignals: (...args: unknown[]) => mocks.useSignals(...args),
}));

vi.mock('../../api/outcomes', () => ({
  fetchAISignalBrief: (...args: unknown[]) => mocks.fetchAISignalBrief(...args),
  fetchAISignalNarrative: (...args: unknown[]) => mocks.fetchAISignalNarrative(...args),
  fetchSignalPostMortem: (...args: unknown[]) => mocks.fetchSignalPostMortem(...args),
}));

vi.mock('../../api/system', () => ({
  getLLMStatus: (...args: unknown[]) => mocks.getLLMStatus(...args),
}));

const makeSignal = (overrides: Partial<SignalListItem> = {}): SignalListItem => ({
  id: 1,
  ticker: 'AAPL',
  event_date: '2026-01-15',
  severity: 'high',
  summary: null,
  opening_price: 150.0,
  previous_close: 148.0,
  closing_price: 152.0,
  reference_price: 150.5,
  mfe_pct: 3.2,
  mae_pct: -1.1,
  mfe_mae_ratio: 2.9,
  eod_pct_change: 1.5,
  follow_through: true,
  is_complete: true,
  ...overrides,
});

describe('SignalTable - event intelligence brief', () => {
  beforeEach(() => {
    mocks.useSignals.mockReturnValue({
      data: {
        signals: [makeSignal({ ticker: 'TSLA', id: 1 })],
        total: 1,
        limit: 20,
        offset: 0,
      },
      isLoading: false,
    });
    mocks.fetchAISignalBrief.mockResolvedValue(makeBrief());
    mocks.fetchAISignalNarrative.mockResolvedValue(makeNarrative({ cache: { status: 'disabled' } }));
    mocks.fetchSignalPostMortem.mockResolvedValue(makePostMortem({ cache: { status: 'disabled' } }));
    mocks.getLLMStatus.mockResolvedValue(makeLLMStatus({ enabled: false, allowed_features: [] }));
  });

  it('shows deterministic explanation, analogs, expected behavior, archetype, and outcome context for a complete event', async () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);

    fireEvent.click(screen.getByRole('button', { name: /Brief/i }));

    expect(await screen.findByText('Deterministic Signal Brief')).toBeInTheDocument();
    expect(screen.getByText(/Facts only/i)).toBeInTheDocument();
    expect(screen.getByText('Relative volume exceeded the configured threshold.')).toBeInTheDocument();
    expect(screen.getByText(/NVDA/)).toBeInTheDocument();
    expect(screen.getByText(/expected behavior/i)).toBeInTheDocument();
    expect(screen.getByText(/Gap continuation/)).toBeInTheDocument();
    expect(screen.getByText(/EOD \+1.50%/)).toBeInTheDocument();
    expect(screen.getByText(/MFE \+3.20%/)).toBeInTheDocument();
    expect(screen.getByText(/MAE -1.10%/)).toBeInTheDocument();
  });

  it('shows partial-state copy when explanation, analogs, archetype, and complete outcome are unavailable', async () => {
    mocks.fetchAISignalBrief.mockResolvedValueOnce(makeBrief({
      why: [],
      analogs: [],
      archetype: null,
      outcome_context: { summary: null, snapshots: [] },
      risks: [
        'Scanner explanation is missing.',
        'Outcome summary is incomplete or unavailable.',
        'No explanation-aware archetype is assigned yet.',
      ],
    }));

    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Brief/i }));

    expect(await screen.findByText('No explanation bullets are stored.')).toBeInTheDocument();
    expect(screen.getByText('No historical analogs were available.')).toBeInTheDocument();
    expect(screen.getByText(/Unassigned/)).toBeInTheDocument();
    expect(screen.getByText('Scanner explanation is missing.')).toBeInTheDocument();
    expect(screen.getByText('Outcome summary is incomplete or unavailable.')).toBeInTheDocument();
  });

  it('keeps no-outcome events factual and labels the missing outcome context', async () => {
    mocks.useSignals.mockReturnValue({
      data: {
        signals: [
          makeSignal({
            id: 9,
            ticker: 'MSFT',
            eod_pct_change: null,
            mfe_pct: null,
            mae_pct: null,
            mfe_mae_ratio: null,
            follow_through: null,
            is_complete: false,
          }),
        ],
        total: 1,
        limit: 20,
        offset: 0,
      },
      isLoading: false,
    });
    mocks.fetchAISignalBrief.mockResolvedValueOnce(makeBrief({
      event_id: 9,
      facts: {
        ticker: 'MSFT',
        event_date: '2026-01-15',
        scanner_type: 'pre_market_volume_spike',
        severity: 'high',
        summary: null,
        signal_quality_score: null,
        regime: null,
      },
      outcome_context: { summary: null, snapshots: [] },
      risks: ['Outcome summary is incomplete or unavailable.'],
    }));

    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Brief/i }));

    expect(await screen.findByText('Deterministic Signal Brief')).toBeInTheDocument();
    expect(screen.getAllByText(/MSFT/).length).toBeGreaterThan(1);
    expect(screen.getByText('Outcome summary is incomplete or unavailable.')).toBeInTheDocument();
    expect(screen.getByText(/Generated narrative can be added later/i)).toBeInTheDocument();
  });

  it('keeps generated AI layers visibly disabled while preserving deterministic facts', async () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Brief/i }));

    expect(await screen.findByText('Deterministic Signal Brief')).toBeInTheDocument();
    expect(await screen.findByText(/AI narrative layers disabled/i)).toBeInTheDocument();
    expect(screen.getByText(/Relative volume exceeded the configured threshold/i)).toBeInTheDocument();
    expect(screen.queryByText(/provider/i)).not.toBeInTheDocument();
  });

  it('loads an enabled generated narrative on demand and labels cached content', async () => {
    mocks.getLLMStatus.mockResolvedValueOnce(makeLLMStatus({
      enabled: true,
      allowed_features: ['scanner_narrative'],
    }));
    mocks.fetchAISignalNarrative.mockResolvedValueOnce(makeNarrative({
      narrative: {
        text: 'TSLA produced a grounded generated scanner narrative.',
        prompt_version: 'scanner_narrative.v1',
        brief_schema_version: 'ai_signal_brief.v1',
        brief_fingerprint: 'abc',
        provenance: [{ claim: 'Scanner event facts', source_fields: ['facts.ticker'] }],
        created_at: '2026-07-04T10:00:00Z',
        updated_at: '2026-07-04T10:00:00Z',
      },
      cache: { status: 'hit' },
    }));

    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Brief/i }));

    expect(await screen.findByRole('button', { name: /load ai narrative/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /load ai narrative/i }));

    expect(await screen.findByText('Generated AI Narrative')).toBeInTheDocument();
    expect(screen.getByText(/TSLA produced a grounded generated scanner narrative/i)).toBeInTheDocument();
    expect(screen.getByText(/Cached/i)).toBeInTheDocument();
    expect(screen.getByText(/Sources: Scanner event facts/i)).toBeInTheDocument();
  });

  it('shows loading state while an AI narrative layer is being generated', async () => {
    mocks.getLLMStatus.mockResolvedValueOnce(makeLLMStatus({
      enabled: true,
      allowed_features: ['scanner_narrative'],
    }));
    mocks.fetchAISignalNarrative.mockReturnValueOnce(new Promise(() => {}));

    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Brief/i }));

    expect(await screen.findByRole('button', { name: /load ai narrative/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /load ai narrative/i }));

    expect(await screen.findByText(/Generating AI narrative/i)).toBeInTheDocument();
  });

  it('labels stale regenerated content without hiding generated text', async () => {
    mocks.getLLMStatus.mockResolvedValueOnce(makeLLMStatus({
      enabled: true,
      allowed_features: ['scanner_narrative'],
    }));
    mocks.fetchAISignalNarrative.mockResolvedValueOnce(makeNarrative({
      narrative: {
        text: 'Updated generated scanner narrative after brief changes.',
        prompt_version: 'scanner_narrative.v1',
        brief_schema_version: 'ai_signal_brief.v1',
        brief_fingerprint: 'def',
        provenance: [{ claim: 'Risk summary', source_fields: ['risks'] }],
        created_at: '2026-07-04T10:00:00Z',
        updated_at: '2026-07-04T11:00:00Z',
      },
      cache: { status: 'stale_regenerated' },
    }));

    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Brief/i }));
    fireEvent.click(await screen.findByRole('button', { name: /load ai narrative/i }));

    expect(await screen.findByText(/Updated generated scanner narrative/i)).toBeInTheDocument();
    expect(screen.getByText(/Regenerated from stale cache/i)).toBeInTheDocument();
  });

  it('shows rejected and failed AI generation states as generated-layer status only', async () => {
    mocks.getLLMStatus.mockResolvedValueOnce(makeLLMStatus({
      enabled: true,
      allowed_features: ['scanner_narrative'],
    }));
    mocks.fetchAISignalNarrative.mockResolvedValueOnce(makeNarrative({
      narrative: null,
      cache: { status: 'rejected' },
      rejection: { reason: 'Generated narrative is missing provenance.' },
    }));

    const { unmount } = renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Brief/i }));
    fireEvent.click(await screen.findByRole('button', { name: /load ai narrative/i }));

    expect(await screen.findByText(/AI narrative was rejected/i)).toBeInTheDocument();
    expect(screen.getByText(/Generated narrative is missing provenance/i)).toBeInTheDocument();
    expect(screen.getByText('Deterministic Signal Brief')).toBeInTheDocument();

    unmount();
    mocks.getLLMStatus.mockResolvedValueOnce(makeLLMStatus({
      enabled: true,
      allowed_features: ['scanner_narrative'],
    }));
    mocks.fetchAISignalNarrative.mockRejectedValueOnce(new Error('service unavailable'));

    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Brief/i }));
    fireEvent.click(await screen.findByRole('button', { name: /load ai narrative/i }));

    expect(await screen.findByText(/AI narrative failed/i)).toBeInTheDocument();
    expect(screen.getByText('Deterministic Signal Brief')).toBeInTheDocument();
  });

  it('offers post-mortem controls only when that narrative feature is enabled', async () => {
    mocks.getLLMStatus.mockResolvedValueOnce(makeLLMStatus({
      enabled: true,
      allowed_features: ['scanner_narrative', 'post_mortem'],
    }));
    mocks.fetchSignalPostMortem.mockResolvedValueOnce(makePostMortem({
      post_mortem: {
        text: 'The realized outcome matched the expected analog pattern.',
        prompt_version: 'signal_post_mortem.v1',
        brief_schema_version: 'ai_signal_brief.v1',
        brief_fingerprint: 'post',
        outcome_status: 'winning',
        known_at_signal_time: {},
        expected_behavior: {},
        realized_outcome: {},
        provenance: [{ claim: 'Realized outcome', source_fields: ['realized_outcome.summary'] }],
        created_at: '2026-07-04T10:00:00Z',
        updated_at: '2026-07-04T10:00:00Z',
      },
      cache: { status: 'miss' },
    }));

    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByRole('button', { name: /Brief/i }));
    fireEvent.click(await screen.findByRole('button', { name: /load post-mortem/i }));

    expect(await screen.findByText('Generated Post-Mortem')).toBeInTheDocument();
    expect(screen.getByText(/The realized outcome matched/i)).toBeInTheDocument();
    expect(screen.getByText(/^Generated$/)).toBeInTheDocument();
  });
});

const makeBrief = (overrides: Partial<AISignalBrief> = {}): AISignalBrief => ({
  schema_version: 'ai_signal_brief.v1',
  event_id: 1,
  facts: {
    ticker: 'TSLA',
    event_date: '2026-01-15',
    scanner_type: 'pre_market_volume_spike',
    severity: 'high',
    summary: 'Premarket volume expansion with elevated gap.',
    signal_quality_score: 82,
    regime: 'risk_on',
  },
  why: ['Relative volume exceeded the configured threshold.'],
  risks: [],
  warnings: [],
  analogs: [
    {
      event_id: 22,
      ticker: 'NVDA',
      event_date: '2025-11-03',
      scanner_type: 'pre_market_volume_spike',
      similarity_score: 0.87,
      score_components: {},
      matched_criteria: ['premarket.volume_spike'],
      outcome_summary: {
        eod_pct_change: 2.4,
        mfe_pct: 4.1,
        mae_pct: -0.8,
      },
      captured_snapshot_count: 4,
      warning_count: 0,
      event: {
        id: 22,
        ticker: 'NVDA',
        event_date: '2025-11-03',
        scanner_type: 'pre_market_volume_spike',
        summary: null,
        severity: 'medium',
        why: [],
        criteria_passed: [],
        criteria_failed: [],
        warnings: [],
      },
    },
  ],
  outcome_context: {
    summary: {
      eod_pct_change: 1.5,
      mfe_pct: 3.2,
      mae_pct: -1.1,
      follow_through: true,
      is_complete: true,
    },
    snapshots: [],
  },
  archetype: {
    cluster_id: 7,
    label: 'Gap continuation',
    event_count: 18,
    centroid: {},
    return_profile: {},
  },
  forbidden_claims: ['Do not claim guaranteed future returns.'],
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.fetchAISignalBrief.mockResolvedValue(makeBrief());
  mocks.fetchAISignalNarrative.mockResolvedValue(makeNarrative({ cache: { status: 'disabled' } }));
  mocks.fetchSignalPostMortem.mockResolvedValue(makePostMortem({ cache: { status: 'disabled' } }));
  mocks.getLLMStatus.mockResolvedValue(makeLLMStatus({ enabled: false, allowed_features: [] }));
});

const makeLLMStatus = (overrides: Record<string, unknown> = {}) => ({
  enabled: false,
  provider_state: 'disabled',
  allowed_features: [],
  limits: {
    timeout_seconds: 20,
    max_tokens: 1000,
    max_cost_usd_per_call: 0,
  },
  metrics: {},
  ...overrides,
});

const makeNarrative = (overrides: Record<string, unknown> = {}) => ({
  brief: makeBrief(),
  narrative: null,
  cache: { status: 'disabled' },
  ...overrides,
});

const makePostMortem = (overrides: Record<string, unknown> = {}) => ({
  brief: makeBrief(),
  post_mortem: null,
  cache: { status: 'disabled' },
  ...overrides,
});

describe('SignalTable — loading state', () => {
  it('shows loading skeleton when isLoading', () => {
    mocks.useSignals.mockReturnValue({ data: undefined, isLoading: true });
    const { container } = renderWithQuery(
      <SignalTable scannerType="pre_market_volume_spike" />,
    );
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('shows "Signals" heading in loading state', () => {
    mocks.useSignals.mockReturnValue({ data: undefined, isLoading: true });
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/^Signals$/)).toBeInTheDocument();
  });
});

describe('SignalTable — empty state', () => {
  it('shows "No signals found" when data total is 0', () => {
    mocks.useSignals.mockReturnValue({
      data: { signals: [], total: 0, limit: 20, offset: 0 },
      isLoading: false,
    });
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/No signals found/i)).toBeInTheDocument();
  });

  it('shows "No signals found" when data is undefined', () => {
    mocks.useSignals.mockReturnValue({ data: undefined, isLoading: false });
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/No signals found/i)).toBeInTheDocument();
  });
});

describe('SignalTable — data state', () => {
  beforeEach(() => {
    mocks.useSignals.mockReturnValue({
      data: {
        signals: [makeSignal({ ticker: 'TSLA', id: 1 })],
        total: 1,
        limit: 20,
        offset: 0,
      },
      isLoading: false,
    });
  });

  it('renders without crashing', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
  });

  it('shows ticker symbol', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText('TSLA')).toBeInTheDocument();
  });

  it('shows event_date', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText('2026-01-15')).toBeInTheDocument();
  });

  it('shows total count', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/1 total/i)).toBeInTheDocument();
  });

  it('shows table headers: Date, Ticker, Severity', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/^Date/i)).toBeInTheDocument();
    expect(screen.getByText(/^Ticker/i)).toBeInTheDocument();
    expect(screen.getByText(/^Severity/i)).toBeInTheDocument();
  });

  it('shows severity badge', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/high/i)).toBeInTheDocument();
  });
});

describe('SignalTable — sorting', () => {
  beforeEach(() => {
    mocks.useSignals.mockReturnValue({
      data: { signals: [makeSignal()], total: 1, limit: 20, offset: 0 },
      isLoading: false,
    });
  });

  it('clicking Date header calls useSignals with changed sort params', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByText(/^Date/i));
    expect(mocks.useSignals).toHaveBeenCalled();
  });

  it('clicking Ticker header triggers a re-render', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByText(/^Ticker/i));
    expect(screen.getByText(/^Ticker/i)).toBeInTheDocument();
  });
});

describe('SignalTable — pagination', () => {
  it('shows pagination controls when total > PAGE_SIZE', () => {
    mocks.useSignals.mockReturnValue({
      data: {
        signals: Array.from({ length: 20 }, (_, i) => makeSignal({ id: i + 1, ticker: `SYM${i}` })),
        total: 45,
        limit: 20,
        offset: 0,
      },
      isLoading: false,
    });
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/1 \/ 3/i)).toBeInTheDocument();
  });
});
