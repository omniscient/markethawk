import { vi, describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import Layout from './Layout';

vi.mock('../api/system', () => ({
  getSystemStatus: vi.fn().mockResolvedValue(null),
}));

vi.mock('./SystemActivityMonitor', () => ({ default: () => null }));

describe('Layout', () => {
  it('renders without crashing', () => {
    renderWithQuery(<Layout>child</Layout>);
  });

  it('mounts children inside the layout', () => {
    renderWithQuery(<Layout><span>hello world</span></Layout>);
    expect(screen.getByText('hello world')).toBeInTheDocument();
  });

  it('renders top-level nav links', () => {
    renderWithQuery(<Layout>content</Layout>);
    expect(screen.getByRole('link', { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /scanner/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /alerts/i })).toBeInTheDocument();
  });

  it('applies active styles to the current route link', () => {
    renderWithQuery(<Layout>content</Layout>, { initialEntries: ['/scanner'] });
    const scannerLink = screen.getByRole('link', { name: /^scanner$/i });
    expect(scannerLink.className).toMatch(/bg-financial-blue/);
  });
});
