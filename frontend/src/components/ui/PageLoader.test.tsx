import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PageLoader } from './PageLoader';

describe('PageLoader', () => {
  it('renders an accessible loading status element', () => {
    render(<PageLoader />);
    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument();
  });
});
