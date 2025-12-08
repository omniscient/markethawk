/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Financial data visualization theme
        'financial-dark': '#0f172a',
        'financial-gray': '#1e293b',
        'financial-light': '#f8fafc',
        'financial-blue': '#0ea5e9',
        'financial-green': '#10b981',
        'financial-red': '#ef4444',
        'financial-yellow': '#f59e0b',
        'financial-purple': '#8b5cf6',
        
        // Semantic colors for financial data
        'positive': '#10b981',
        'negative': '#ef4444',
        'neutral': '#6b7280',
        'accent': '#0ea5e9',
        
        // Chart colors
        'chart-primary': '#0ea5e9',
        'chart-secondary': '#8b5cf6',
        'chart-tertiary': '#f59e0b',
      },
      fontFamily: {
        'sans': ['Inter', 'system-ui', 'sans-serif'],
        'mono': ['JetBrains Mono', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-in-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}