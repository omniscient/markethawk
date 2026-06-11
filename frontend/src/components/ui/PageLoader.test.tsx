import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { PageLoader } from './PageLoader';

describe('PageLoader', () => {
  it('renders without crashing', () => {
    render(<PageLoader />);
  });

  it('renders a spinning element', () => {
    const { container } = render(<PageLoader />);
    const spinner = container.querySelector('.animate-spin');
    expect(spinner).toBeInTheDocument();
  });
});
