import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import UniverseFormModal from './UniverseFormModal';

const mockCreate = vi.fn().mockResolvedValue({
  id: 1,
  uuid: 'test-uuid',
  name: 'Test',
  description: '',
  criteria: {},
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
});

vi.mock('../api/universe', () => ({
  createStockUniverse: () => mockCreate(),
  updateStockUniverse: vi.fn().mockResolvedValue({}),
}));

vi.mock('../api/scanner', () => ({
  fetchProviders: vi.fn().mockResolvedValue({ available: [] }),
}));

const defaultProps = {
  isOpen: true,
  onClose: vi.fn(),
  initialData: null,
};

describe('UniverseFormModal', () => {
  it('renders without crashing when open', () => {
    renderWithQuery(<UniverseFormModal {...defaultProps} />);
  });

  it('renders nothing when isOpen is false', () => {
    const { container } = renderWithQuery(
      <UniverseFormModal {...defaultProps} isOpen={false} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('shows the "Create Stock Universe" title', () => {
    renderWithQuery(<UniverseFormModal {...defaultProps} />);
    expect(screen.getByText(/create stock universe/i)).toBeInTheDocument();
  });

  it('Create Universe button is disabled when name is empty', () => {
    renderWithQuery(<UniverseFormModal {...defaultProps} />);
    const createBtn = screen.getByRole('button', { name: /create universe/i });
    expect(createBtn).toBeDisabled();
  });

  it('Create Universe button enables after typing a name', () => {
    renderWithQuery(<UniverseFormModal {...defaultProps} />);
    fireEvent.change(screen.getByPlaceholderText(/large cap tech/i), {
      target: { value: 'My Universe' },
    });
    expect(screen.getByRole('button', { name: /create universe/i })).not.toBeDisabled();
  });

  it('calls createStockUniverse when a valid form is submitted', async () => {
    renderWithQuery(<UniverseFormModal {...defaultProps} />);
    fireEvent.change(screen.getByPlaceholderText(/large cap tech/i), {
      target: { value: 'My Universe' },
    });
    fireEvent.click(screen.getByRole('button', { name: /create universe/i }));
    await waitFor(() => expect(mockCreate).toHaveBeenCalledOnce());
  });
});
