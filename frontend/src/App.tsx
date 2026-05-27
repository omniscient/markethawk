import React, { ReactNode } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';

import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Scanner from './pages/Scanner';
import Universes from './pages/Universes';
import Alerts from './pages/Alerts';
import Settings from './pages/Settings';
import StockDetailPage from './pages/StockDetailPage';
import Journal from './pages/Journal';
import EdgeExplorer from './pages/EdgeExplorer';
import PreMarketMovers from './pages/PreMarketMovers';
import ActiveWatchlist from './pages/ActiveWatchlist';
import AutoTrading from './pages/AutoTrading';
import ScorecardOverview from './pages/ScorecardOverview';
import ScorecardDetail from './pages/ScorecardDetail';
import Login from './pages/Login';
import { GlobalErrorToast } from './components/ui/GlobalErrorToast';
import { apiClient } from './api/client';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      retry: 1,
    },
  },
});

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isLoading, isError } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => apiClient.get('/auth/me').then((r) => r.data),
    retry: false,
  });
  if (isLoading) return <div className="min-h-screen bg-financial-dark" />;
  if (isError) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <div className="min-h-screen bg-financial-dark text-financial-light relative">
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/scanner" element={<Scanner />} />
                      <Route path="/universes" element={<Universes />} />
                      <Route path="/alerts" element={<Alerts />} />
                      <Route path="/settings" element={<Settings />} />
                      <Route path="/journal" element={<Journal />} />
                      <Route path="/edge-explorer" element={<EdgeExplorer />} />
                      <Route path="/scorecard" element={<ScorecardOverview />} />
                      <Route path="/scorecard/:scannerType" element={<ScorecardDetail />} />
                      <Route path="/movers/pre-market" element={<PreMarketMovers />} />
                      <Route path="/watchlist" element={<ActiveWatchlist />} />
                      <Route path="/trading" element={<AutoTrading />} />
                      <Route path="/stock/:ticker" element={<StockDetailPage />} />
                    </Routes>
                  </Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
          <GlobalErrorToast />
        </div>
      </Router>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}

export default App;
