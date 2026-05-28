import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getAuthStatus, getMe, login, register } from '../../api/auth';

type Mode = 'loading' | 'login' | 'register' | 'redirecting';

export default function Login() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>('loading');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then(() => { if (!cancelled) navigate('/', { replace: true }); })
      .catch(() =>
        getAuthStatus().then((s) => {
          if (!cancelled) setMode(s.bootstrapped ? 'login' : 'register');
        })
      );
    return () => { cancelled = true; };
  }, [navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (mode === 'register' && password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    setSubmitting(true);
    try {
      if (mode === 'register') {
        await register(username, password);
        await login(username, password);
      } else {
        await login(username, password);
      }
      navigate('/', { replace: true });
    } catch {
      setError(mode === 'register' ? 'Registration failed' : 'Invalid username or password');
    } finally {
      setSubmitting(false);
    }
  }

  if (mode === 'loading' || mode === 'redirecting') {
    return (
      <div className="min-h-screen bg-financial-dark flex items-center justify-center">
        <div className="text-financial-light">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-financial-dark flex items-center justify-center">
      <div className="w-full max-w-sm bg-financial-surface border border-financial-border rounded-lg p-8 shadow-xl">
        <h1 className="text-2xl font-bold text-financial-light mb-2">MarketHawk</h1>
        <p className="text-financial-muted text-sm mb-6">
          {mode === 'register' ? 'Create your account to get started' : 'Sign in to continue'}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-financial-light mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              className="w-full bg-financial-dark border border-financial-border rounded px-3 py-2 text-financial-light focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm text-financial-light mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full bg-financial-dark border border-financial-border rounded px-3 py-2 text-financial-light focus:outline-none focus:border-blue-500"
            />
          </div>
          {mode === 'register' && (
            <div>
              <label className="block text-sm text-financial-light mb-1">Confirm Password</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                className="w-full bg-financial-dark border border-financial-border rounded px-3 py-2 text-financial-light focus:outline-none focus:border-blue-500"
              />
            </div>
          )}
          {error && <p className="text-red-400 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded py-2 font-medium transition-colors"
          >
            {submitting ? 'Please wait...' : mode === 'register' ? 'Create Account' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
