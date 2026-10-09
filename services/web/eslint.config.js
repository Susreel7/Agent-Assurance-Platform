// ESLint flat config.
//
// `tsc --noEmit` already runs in strict mode, so this file deliberately does not
// duplicate type checking. It exists for the two classes of defect the compiler cannot
// see: React hook misuse (conditional hooks, missing dependencies producing stale
// closures) and accidental `any` leaking through the API client boundary.
//
// Rules are errors rather than warnings because `npm run lint` runs with
// --max-warnings 0; a warning here would fail the build anyway, and calling it a
// warning would only make the output harder to read.

import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    // Build output and generated API types. `schema.d.ts` comes from
    // openapi-typescript and is not ours to lint.
    ignores: ['dist', 'src/api/schema.d.ts'],
  },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,

      // Vite's HMR boundary: a module exporting both a component and a helper cannot
      // be hot-replaced, which degrades to a full reload during development.
      'react-refresh/only-export-components': ['error', { allowConstantExport: true }],

      // An unused variable prefixed with an underscore is a deliberate placeholder —
      // most often an ignored callback argument.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],

      // `any` silently disables checking at exactly the boundary where the data is
      // least trusted. Escaping it should require saying so in a comment.
      '@typescript-eslint/no-explicit-any': 'error',
    },
  },
);
