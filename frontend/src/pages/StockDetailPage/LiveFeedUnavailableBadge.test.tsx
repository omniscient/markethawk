import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LiveFeedUnavailableBadge } from './LiveFeedUnavailableBadge';

describe('LiveFeedUnavailableBadge', () => {
  it('tells the user the chart shows last known data', () => {
    render(<LiveFeedUnavailableBadge />);
    expect(screen.getByRole('status')).toHaveTextContent('Live feed unavailable — showing last known data');
  });
});
