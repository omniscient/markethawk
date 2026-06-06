import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';
import type { RenderOptions } from '@testing-library/react';
import React from 'react';

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

export function renderWithQuery(
  ui: React.ReactElement,
  options?: RenderOptions & { initialEntries?: string[] }
) {
  const qc = makeQueryClient();
  const { initialEntries = ['/'], ...rest } = options ?? {};
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>,
    rest
  );
}
