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
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { getSystemInfo } from '../api/system';
import SystemActivityMonitor from './SystemActivityMonitor';

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  const { data: systemInfo } = useQuery({
    queryKey: ['systemInfo'],
    queryFn: getSystemInfo
  });

  const navigation = [
    { name: 'Dashboard', href: '/', icon: BarChart3 },
    { name: 'Scanner', href: '/scanner', icon: ScanLine },
    { name: 'Pre-market Movers', href: '/movers/pre-market', icon: TrendingUp },
    { name: 'Edge Explorer', href: '/edge-explorer', icon: BarChart3 },
    { name: 'Universes', href: '/universes', icon: Database },
    { name: 'Watchlist', href: '/watchlist', icon: Eye },
    { name: 'Journal', href: '/journal', icon: BookOpen },
    { name: 'Alerts', href: '/alerts', icon: Bell },
    { name: 'Settings', href: '/settings', icon: Settings },
  ];

  const isActive = (path: string) => {
    return location.pathname === path;
  };

  return (
    <div className="flex h-screen bg-financial-dark">
      {/* Sidebar */}
      <div className={`${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} fixed inset-y-0 left-0 z-50 w-64 bg-financial-gray border-r border-gray-700 transform transition-transform duration-300 ease-in-out lg:translate-x-0 lg:static lg:inset-0`}>
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
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <div className="flex items-center justify-between h-16 bg-financial-gray border-b border-gray-700 px-6">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden text-gray-400 hover:text-white"
          >
            <Menu className="h-6 w-6" />
          </button>
          
          <div className="flex items-center space-x-6 ml-auto">
            <SystemActivityMonitor />
            <div className="flex items-center text-xs space-x-2 px-2 py-1 bg-gray-800 rounded-full border border-gray-700">
              <span className="text-gray-500 uppercase font-bold tracking-tighter">Plan:</span>
              <span className={`font-bold ${systemInfo?.data_mode === 'live' ? 'text-positive' : 'text-warning'}`}>
                {systemInfo?.data_mode === 'live' ? 'LIVE-RT' : 'STARTER-15M'}
              </span>
            </div>
            <div className="text-sm text-gray-400">
              Market Status: <span className="text-positive">Open</span>
            </div>
            <div className="text-sm text-gray-400">
              Last Scan: <span className="text-financial-light">2 min ago</span>
            </div>
          </div>
        </div>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto bg-financial-dark">
          <div className="p-6">
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