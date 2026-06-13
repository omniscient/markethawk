import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  BarChart3,
  ScanLine,
  Database,
  Bell,
  Settings,
  Menu,
  X,
  TrendingUp,
  BookOpen,
  Eye,
  Bot,
  Trophy,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { getSystemStatus, MarketStatus } from '../api/system';
import SystemActivityMonitor from './SystemActivityMonitor';

// ── Status helpers ────────────────────────────────────────────────────────────

const MARKET_LABELS: Record<MarketStatus, string> = {
  open: 'MKT OPEN',
  pre_market: 'PRE-MKT',
  post_market: 'AFTER-HRS',
  closed: 'MKT CLOSED',
};

const MARKET_DOT_COLOR: Record<MarketStatus, string> = {
  open: 'bg-green-400',
  pre_market: 'bg-amber-400',
  post_market: 'bg-amber-400',
  closed: 'bg-gray-500',
};

function formatRelativeTime(isoString: string | null): string {
  if (!isoString) return 'never';
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

interface StatusDotProps {
  color: string;
  label: string;
  pulse?: boolean;
}

const StatusDot: React.FC<StatusDotProps> = ({ color, label, pulse }) => (
  <div className="flex items-center gap-1.5">
    <span className={`relative flex h-2 w-2 ${pulse ? 'shrink-0' : ''}`}>
      {pulse && (
        <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${color} opacity-60`} />
      )}
      <span className={`relative inline-flex rounded-full h-2 w-2 ${color}`} />
    </span>
    <span className="text-xs font-medium text-gray-300">{label}</span>
  </div>
);

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  const { data: status } = useQuery({
    queryKey: ['systemStatus'],
    queryFn: getSystemStatus,
    refetchInterval: 30_000,
    staleTime: 20_000,
  });

  const navigation = [
    { name: 'Dashboard', href: '/', icon: BarChart3 },
    { name: 'Scanner', href: '/scanner', icon: ScanLine },
    { name: 'Pre-market Movers', href: '/movers/pre-market', icon: TrendingUp },
    { name: 'Edge Explorer', href: '/edge-explorer', icon: BarChart3 },
    { name: 'Scorecard', href: '/scorecard', icon: Trophy },
    { name: 'Universes', href: '/universes', icon: Database },
    { name: 'Watchlist', href: '/watchlist', icon: Eye },
    { name: 'Journal', href: '/journal', icon: BookOpen },
    { name: 'Alerts', href: '/alerts', icon: Bell },
    { name: 'Auto Trading', href: '/trading', icon: Bot },
    { name: 'Settings', href: '/settings', icon: Settings },
  ];

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  return (
    <div className="flex h-screen bg-financial-dark">
      {/* Sidebar */}
      <div className={`${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} fixed inset-y-0 left-0 z-50 w-64 2xl:w-72 bg-financial-gray border-r border-gray-700 transform transition-transform duration-300 ease-in-out lg:translate-x-0 lg:static lg:inset-0`}>
        <div className="flex items-center justify-between h-16 px-6 border-b border-gray-700">
          <div className="flex items-center space-x-3">
            <TrendingUp className="h-8 w-8 text-financial-blue" />
            <span className="text-xl font-bold text-financial-light">StockScanner</span>
          </div>
          <button
            onClick={() => setSidebarOpen(false)}
            className="lg:hidden text-gray-400 hover:text-white"
          >
            <X className="h-6 w-6" />
          </button>
        </div>
        
        <nav className="mt-6">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.name}
                to={item.href}
                className={`flex items-center px-6 py-3 text-sm font-medium transition-colors duration-200 ${
                  isActive(item.href)
                    ? 'bg-financial-blue text-white border-r-2 border-financial-blue'
                    : 'text-gray-300 hover:bg-gray-700 hover:text-white'
                }`}
              >
                <Icon className="h-5 w-5 mr-3" />
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-between h-16 bg-financial-gray border-b border-gray-700 px-4 sm:px-6 2xl:px-8">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden text-gray-400 hover:text-white"
          >
            <Menu className="h-6 w-6" />
          </button>
          
          <div className="flex items-center gap-4 ml-auto">
            <SystemActivityMonitor />
            <div className="flex items-center gap-4 px-3 py-1.5 bg-gray-800 rounded-full border border-gray-700">
              <StatusDot
                color={status ? MARKET_DOT_COLOR[status.market_status] : 'bg-gray-600'}
                label={status ? MARKET_LABELS[status.market_status] : '—'}
                pulse={status?.market_status === 'open'}
              />
              <span className="w-px h-3 bg-gray-700" />
              <StatusDot
                color={status?.ibkr_reachable ? 'bg-green-400' : 'bg-red-500'}
                label={status?.ibkr_reachable ? 'IB CONN' : 'IB OFF'}
              />
              <span className="w-px h-3 bg-gray-700" />
              <span className="text-xs text-gray-500">
                {status?.last_scan_at ? (
                  <>
                    <span className="text-gray-400">SCAN</span>{' '}
                    {formatRelativeTime(status.last_scan_at)}
                  </>
                ) : (
                  <span className="text-gray-500">NO SCAN</span>
                )}
              </span>
            </div>
          </div>
        </div>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto overflow-x-hidden bg-financial-dark">
          <div className="app-content-shell">
            {children}
          </div>
        </main>
      </div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black bg-opacity-50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
    </div>
  );
};

export default Layout;
