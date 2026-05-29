import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export const apiClient = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Separate client for unversioned endpoints (auth, health). Auth stays at /api/auth
// regardless of API version so tokens work across all versions.
export const unversionedClient = axios.create({
  baseURL: '/api',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status;
    const isNetworkError = !error.response;

    if (status === 401 && !error.config._retried && !error.config.url?.includes('/auth/')) {
      error.config._retried = true;
      try {
        await unversionedClient.post('/auth/refresh');
        return apiClient(error.config);
      } catch {
        window.location.href = '/login';
      }
    }

    if (status >= 500 || isNetworkError || status === undefined) {
      const data = error.response?.data;
      const isJson = error.response?.headers?.['content-type']?.includes('application/json');

      window.dispatchEvent(
        new CustomEvent('server-error', {
          detail: {
            message:
              isJson && data?.message
                ? data.message
                : isNetworkError
                  ? 'Network error or server timeout. Please check your connection or dashboard status.'
                  : 'An unexpected server error occurred.',
            error_id: isJson && data?.error_id ? data.error_id : null,
            detail: isJson && data?.detail ? data.detail : null,
            stack_trace: isJson && data?.stack_trace ? data.stack_trace : null,
          },
        }),
      );
    }

    return Promise.reject(error);
  },
);
