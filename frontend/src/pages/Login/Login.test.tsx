import { vi, describe, it, expect, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import Login from './index';

const mockLogin = vi.fn().mockResolvedValue(undefined);
const mockRegister = vi.fn().mockResolvedValue({ username: 'test', id: 1 });

vi.mock('../../api/auth', () => ({
  getMe: vi.fn().mockRejectedValue(new Error('unauthorized')),
  getAuthStatus: vi.fn().mockResolvedValue({ bootstrapped: true }),
  login: () => mockLogin(),
  register: () => mockRegister(),
}));

describe('Login page', () => {
  beforeEach(() => {
    mockLogin.mockResolvedValue(undefined);
  });

  it('renders without crashing', () => {
    renderWithQuery(<Login />);
  });

  it('shows the login form after auth check resolves', async () => {
    renderWithQuery(<Login />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    });
  });

  it('shows username and password fields', async () => {
    const { container } = renderWithQuery(<Login />);
    await waitFor(() => screen.getByRole('button', { name: /sign in/i }));
    expect(container.querySelector('input[type="text"]')).toBeInTheDocument();
    expect(container.querySelector('input[type="password"]')).toBeInTheDocument();
  });

  it('calls login with typed credentials on submit', async () => {
    const { container, getByRole } = renderWithQuery(<Login />);
    await waitFor(() => getByRole('button', { name: /sign in/i }));

    fireEvent.change(container.querySelector('input[type="text"]')!, { target: { value: 'admin' } });
    fireEvent.change(container.querySelector('input[type="password"]')!, { target: { value: 'secret' } });
    fireEvent.click(getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(mockLogin).toHaveBeenCalledOnce());
  });

  it('shows an error message when login fails', async () => {
    mockLogin.mockRejectedValue(new Error('401'));
    const { container } = renderWithQuery(<Login />);
    await waitFor(() => screen.getByRole('button', { name: /sign in/i }));

    fireEvent.change(container.querySelector('input[type="text"]')!, { target: { value: 'bad' } });
    fireEvent.change(container.querySelector('input[type="password"]')!, { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid username or password/i)).toBeInTheDocument();
    });
  });
});
