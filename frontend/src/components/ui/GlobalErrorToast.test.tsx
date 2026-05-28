import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { GlobalErrorToast } from './GlobalErrorToast';

function dispatchServerError(detail: object) {
  window.dispatchEvent(new CustomEvent('server-error', { detail }));
}

describe('GlobalErrorToast', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders nothing by default', () => {
    const { container } = render(<GlobalErrorToast />);
    expect(container.firstChild).toBeNull();
  });

  it('shows the toast when a server-error event fires', () => {
    render(<GlobalErrorToast />);

    act(() => {
      dispatchServerError({ message: 'Internal server error', error_id: null });
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Internal server error')).toBeInTheDocument();
  });

  it('shows Seq link when error_id is present', () => {
    render(<GlobalErrorToast />);

    act(() => {
      dispatchServerError({ message: 'DB failed', error_id: 'err-123' });
    });

    const link = screen.getByText('Trace in Seq').closest('a');
    expect(link).toHaveAttribute('href', expect.stringContaining('err-123'));
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('does not show Seq link when error_id is null', () => {
    render(<GlobalErrorToast />);

    act(() => {
      dispatchServerError({ message: 'No ID', error_id: null });
    });

    expect(screen.queryByText('Trace in Seq')).toBeNull();
  });

  it('dismisses when the X button is clicked', () => {
    render(<GlobalErrorToast />);

    act(() => {
      dispatchServerError({ message: 'Oops', error_id: null });
    });

    const dismiss = screen.getByLabelText('Dismiss error notification');
    fireEvent.click(dismiss);

    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('auto-dismisses after 20 seconds', () => {
    render(<GlobalErrorToast />);

    act(() => {
      dispatchServerError({ message: 'Will disappear', error_id: null });
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(20_000); });

    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('expands developer details when stack_trace is present', () => {
    render(<GlobalErrorToast />);

    act(() => {
      dispatchServerError({ message: 'Crash', error_id: null, stack_trace: 'line 1\nline 2' });
    });

    const toggleBtn = screen.getByText('Developer details');
    fireEvent.click(toggleBtn);

    expect(screen.getByText(/line 1/)).toBeInTheDocument();
  });

  it('collapses developer details on second click', () => {
    render(<GlobalErrorToast />);

    act(() => {
      dispatchServerError({ message: 'Crash', error_id: null, stack_trace: 'trace here' });
    });

    const toggleBtn = screen.getByText('Developer details');
    fireEvent.click(toggleBtn);
    expect(screen.getByText(/trace here/)).toBeInTheDocument();

    fireEvent.click(toggleBtn);
    expect(screen.queryByText(/trace here/)).toBeNull();
  });

  it('resets expanded state when a new error arrives', () => {
    render(<GlobalErrorToast />);

    act(() => {
      dispatchServerError({ message: 'First', error_id: null, stack_trace: 'trace 1' });
    });
    fireEvent.click(screen.getByText('Developer details'));
    expect(screen.getByText(/trace 1/)).toBeInTheDocument();

    act(() => {
      dispatchServerError({ message: 'Second', error_id: null, stack_trace: 'trace 2' });
    });

    // expanded should have reset → detail panel not visible
    expect(screen.queryByText(/trace 2/)).toBeNull();
    expect(screen.getByText('Second')).toBeInTheDocument();
  });
});
