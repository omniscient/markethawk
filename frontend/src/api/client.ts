/**
 * Centralized API Client
 *
 * All HTTP calls to the backend must go through this module.
 * It provides:
 *  - A single, configurable Axios instance (baseURL driven by env var)
 *  - Global response interceptor that catches 5xx errors and fires a
 *    window 'server-error' event so the GlobalErrorToast can surface them
 *
 * Usage:
 *   import { apiClient } from '@/api/client';
 *   const data = await apiClient.get('/scanner/results');
 *
 * To swap the error-tracking backend: update the toast URL generation
 * in GlobalErrorToast.tsx – the API contract (error_id) stays the same.
 */
import axios from 'axios';

// Base is "/api" which the Vite dev proxy (vite.config.ts → /api → backend:8000) handles at runtime.
// In production builds, VITE_API_BASE_URL should point at the full origin if needed.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';

export const apiClient = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ----- Global Error Interceptor ------------------------------------------ //
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // 5xx errors or network errors with no response
    const status = error.response?.status;
    const isNetworkError = !error.response;

    if (status >= 500 || isNetworkError || status === undefined) {
      const data = error.response?.data;
      const isJson = error.response?.headers?.['content-type']?.includes('application/json');

      // Fire global event that GlobalErrorToast listens to
      window.dispatchEvent(
        new CustomEvent('server-error', {
          detail: {
            message:
              (isJson && data?.message) ? data.message : 
              isNetworkError ? 'Network error or server timeout. Please check your connection or dashboard status.' :
              'An unexpected server error occurred.',
            error_id: (isJson && data?.error_id) ? data.error_id : null,
            // In dev mode the backend also returns stack_trace + detail
            detail: (isJson && data?.detail) ? data.detail : null,
            stack_trace: (isJson && data?.stack_trace) ? data.stack_trace : null,
          },
        }),
      );
    }
    return Promise.reject(error);
  },
);
