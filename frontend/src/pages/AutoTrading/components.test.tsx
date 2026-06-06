import { describe, it, expect } from 'vitest';
import {
  STATUS_CONFIG,
  SESSION_OPTIONS,
  DIRECTION_OPTIONS,
  DEFAULT_STRATEGY,
} from './components';

describe('AutoTrading/components — exported constants', () => {
  it('STATUS_CONFIG has entries for all expected statuses', () => {
    const statuses = ['pending_approval', 'pending', 'submitted', 'open', 'closed', 'cancelled', 'rejected', 'error'];
    statuses.forEach(s => {
      expect(STATUS_CONFIG[s]).toBeDefined();
      expect(STATUS_CONFIG[s].label).toBeTruthy();
      expect(STATUS_CONFIG[s].icon).toBeTruthy();
    });
  });

  it('SESSION_OPTIONS contains pre, regular, post sessions', () => {
    const ids = SESSION_OPTIONS.map(o => o.id);
    expect(ids).toContain('pre');
    expect(ids).toContain('regular');
    expect(ids).toContain('post');
  });

  it('DIRECTION_OPTIONS contains long_only, short_only, both', () => {
    const ids = DIRECTION_OPTIONS.map(o => o.id);
    expect(ids).toContain('long_only');
    expect(ids).toContain('short_only');
    expect(ids).toContain('both');
  });

  it('DEFAULT_STRATEGY is_active defaults to true', () => {
    expect(DEFAULT_STRATEGY.is_active).toBe(true);
  });

  it('DEFAULT_STRATEGY paper_mode defaults to true', () => {
    expect(DEFAULT_STRATEGY.paper_mode).toBe(true);
  });
});
