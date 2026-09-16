import { lazy, Suspense, ReactNode } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';

import Layout from './components/Layout';
import Login from './pages/Login';
import { PageLoader } from './components/ui/PageLoader';
import { GlobalErrorToast } from './components/ui/GlobalErrorToast';
import { getMe } from './api/auth';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Scanner = lazy(() => import('./pages/Scanner'));
const Universes = lazy(() => import('./pages/Universes'));
const Alerts = lazy(() => import('./pages/Alerts'));
const Settings = lazy(() => import('./pages/Settings'));
const StockDetailPage = lazy(() => import('./pages/StockDetailPage'));
const Journal = lazy(() => import('./pages/Journal'));
const EdgeExplorer = lazy(() => import('./pages/EdgeExplorer'));
const PreMarketMovers = lazy(() => import('./pages/PreMarketMovers'));
const ActiveWatchlist = lazy(() => import('./pages/ActiveWatchlist'));
const AutoTrading = lazy(() => import('./pages/AutoTrading'));
const ScorecardOverview = lazy(() => import('./pages/ScorecardOverview'));
const ScorecardDetail = lazy(() => import('./pages/ScorecardDetail'));
const Replay = lazy(() => import('./pages/Replay'));

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
    // Auth lives at /api/auth/me (unversionedClient), NOT /api/v1/auth/me. Using the
    // shared getMe() helper avoids hitting a 404 that would bounce every login to /login.
    queryFn: getMe,
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
                    <Suspense fallback={<PageLoader />}>
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
                        <Route path="/replay" element={<Replay />} />
                        <Route path="/movers/pre-market" element={<PreMarketMovers />} />
                        <Route path="/watchlist" element={<ActiveWatchlist />} />
                        <Route path="/trading" element={<AutoTrading />} />
                        <Route path="/stock/:ticker" element={<StockDetailPage />} />
                      </Routes>
                    </Suspense>
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
