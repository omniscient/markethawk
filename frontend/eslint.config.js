import js from '@eslint/js'
import globals from 'globals'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import tsParser from '@typescript-eslint/parser'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

export default [
  { ignores: ['dist/**', 'node_modules/**'] },

  // Service worker (runs in browser SW context, not in main-thread JS)
  {
    files: ['public/**/*.js'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.serviceworker,
      },
    },
  },

  // Base JS rules
  js.configs.recommended,

  // TS recommended — flat/recommended is an array in @typescript-eslint v8; spread each entry
  ...tsPlugin.configs['flat/recommended'],

  // Custom overrides (applied after TS recommended so they win)
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
      globals: { ...globals.browser },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',

      // React hooks
      ...reactHooks.configs['recommended-latest'].rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

      // Enforce const for variables that are never reassigned
      'prefer-const': 'error',

      // TypeScript handles unused-vars better than the base rule
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },

  // Regression guard: ban raw /api/ strings outside the api/ layer.
  // All WS and HTTP URLs must go through wsUrl() or apiClient so a single
  // env-var change propagates everywhere.
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/api/**'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "Literal[value=/^\\/api\\//]",
          message:
            "Raw /api/ string detected outside src/api/**. Use wsUrl() or apiClient instead.",
        },
        {
          selector: "TemplateLiteral > TemplateElement[value.raw=/^\\/api\\//]",
          message:
            "Raw /api/ in template literal outside src/api/**. Use wsUrl() or apiClient instead.",
        },
      ],
    },
  },
]
