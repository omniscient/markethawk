import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import HeroMetrics from './HeroMetrics';
import type { Scorecard } from '../../api/outcomes';

const baseScorecard: Scorecard = {
  scanner_type: 'pre_market_volume_spike',
  period: '90d',
  total_signals: 120,
  complete_signals: 95,
  win_rate_pct: 62.5,
  avg_mfe_pct: 3.4,
  avg_mae_pct: 1.8,
  mfe_mae_ratio: 1.9,
  avg_r_multiple: 1.2,
  expectancy: 2.3,
  profit_factor: 2.1,
  follow_through_rate_pct: 71.0,
  edge_decay: [],
  interval_breakdown: {},
};

describe('HeroMetrics', () => {
  it('renders without crashing', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
  });

  it('shows Win Rate label', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    expect(screen.getByText(/Win Rate/i)).toBeInTheDocument();
  });

  it('shows formatted win rate percentage', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    expect(screen.getByText('62.5%')).toBeInTheDocument();
  });

  it('shows em-dash for null win_rate_pct', () => {
    const sc = { ...baseScorecard, win_rate_pct: null };
    const { container } = render(<HeroMetrics scorecard={sc} />);
    const winRateCard = container.firstChild as HTMLElement;
    expect(winRateCard.textContent).toContain('—');
  });

  it('applies green color when win_rate_pct >= 50', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    const winRateValue = screen.getByText('62.5%');
    expect(winRateValue.className).toContain('text-green-400');
  });

  it('applies red color when win_rate_pct < 50', () => {
    const sc = { ...baseScorecard, win_rate_pct: 45.0 };
    render(<HeroMetrics scorecard={sc} />);
    const winRateValue = screen.getByText('45.0%');
    expect(winRateValue.className).toContain('text-red-400');
  });

  it('shows MFE:MAE label', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    expect(screen.getAllByText(/MFE.*MAE/i).length).toBeGreaterThan(0);
  });

  it('shows MFE:MAE ratio formatted as "X.X : 1"', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    expect(screen.getByText('1.9 : 1')).toBeInTheDocument();
  });

  it('shows em-dash for null mfe_mae_ratio', () => {
    const sc = { ...baseScorecard, mfe_mae_ratio: null };
    render(<HeroMetrics scorecard={sc} />);
    const ratioCard = screen.getByText('MFE : MAE').closest('div')?.parentElement;
    expect(ratioCard?.textContent).toContain('—');
  });

  it('shows Expectancy label', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    expect(screen.getByText(/Expectancy/i)).toBeInTheDocument();
  });

  it('shows expectancy with + sign for positive value', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    expect(screen.getByText('+2.3%')).toBeInTheDocument();
  });

  it('shows total_signals and complete_signals counts', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    expect(screen.getByText(/95 \/ 120 signals/i)).toBeInTheDocument();
  });

  it('shows Profit Factor label', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    expect(screen.getByText(/Profit Factor/i)).toBeInTheDocument();
  });

  it('shows Avg R-Multiple label', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    expect(screen.getByText(/Avg R-Multiple/i)).toBeInTheDocument();
  });

  it('shows Follow-Through label', () => {
    render(<HeroMetrics scorecard={baseScorecard} />);
    expect(screen.getByText(/Follow-Through/i)).toBeInTheDocument();
  });
});
