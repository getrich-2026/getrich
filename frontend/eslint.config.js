import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { createRequire } from 'node:module'
import { defineConfig, globalIgnores } from 'eslint/config'

const require = createRequire(import.meta.url)
const getrichPlugin = require('./src/lib/eslint-plugin-no-unsanitized-danger.cjs')

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    plugins: {
      getrich: getrichPlugin,
    },
    rules: {
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      "getrich/no-unsanitized-danger": "error",
    },
    languageOptions: {
      globals: globals.browser,
    },
  },
])
