import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import { AlertRuleModal } from './AlertRuleModal';
import type { AlertRule } from '../../api/alerts';

const baseFormState: Partial<AlertRule> = {
  name: '',
  is_active: true,
  scanner_types: [],
  severity_filter: 'any',
  cooldown_minutes: 60,
  channels: ['browser_push'],
  channel_config: { email: '', google_chat_webhook: '', webhook_url: '' },
  auto_trade: false,
  trading_strategy_id: null,
};

const baseProps = {
  isOpen: true,
  editingRule: null,
  formState: baseFormState,
  onFormState: vi.fn(),
  onSave: vi.fn(),
  onClose: vi.fn(),
  isSaving: false,
  strategies: [],
};

describe('AlertRuleModal', () => {
  it('renders without crashing', () => {
    renderWithQuery(<AlertRuleModal {...baseProps} />);
  });

  it('shows "Create New Alert Rule" title for new rule', () => {
    renderWithQuery(<AlertRuleModal {...baseProps} />);
    expect(screen.getByText(/create new alert rule/i)).toBeInTheDocument();
  });

  it('shows "Edit Alert Rule" title when editing an existing rule', () => {
    renderWithQuery(
      <AlertRuleModal
        {...baseProps}
        editingRule={{ id: 42, name: 'Existing Rule' } as AlertRule}
      />
    );
    expect(screen.getByText(/edit alert rule/i)).toBeInTheDocument();
  });

  it('shows scanner type toggle buttons', () => {
    renderWithQuery(<AlertRuleModal {...baseProps} />);
    expect(screen.getByText(/pre-market volume spike/i)).toBeInTheDocument();
  });

  it('calls onSave when Create Rule button is clicked', () => {
    const onSave = vi.fn();
    renderWithQuery(<AlertRuleModal {...baseProps} onSave={onSave} />);
    fireEvent.click(screen.getByRole('button', { name: /create rule/i }));
    expect(onSave).toHaveBeenCalledOnce();
  });

  it('calls onClose when Cancel is clicked', () => {
    const onClose = vi.fn();
    renderWithQuery(<AlertRuleModal {...baseProps} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
