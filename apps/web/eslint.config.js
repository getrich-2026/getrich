import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

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
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
  {
    // src/components/ui/ 是 shadcn/ui CLI 生成并托管的，AGENTS.md §5 明确要求不手改。
    // 这两条规则只会在这些文件里触发，且都要改动上游源码才能消除：
    // - only-export-components：组件文件同时导出 buttonVariants 这类 cva 常量，
    //   按规则应拆到单独文件，一拆 CLI 下次重新生成就覆盖回去。
    // - react-hooks/purity：sidebar.tsx 的骨架屏用 Math.random() 随机宽度，
    //   纯装饰用途，且已包在 useMemo(..., []) 里，每个实例只算一次。
    // 自己写的组件不在此列，仍受完整规则约束。
    files: ['src/components/ui/**/*.{ts,tsx}'],
    rules: {
      'react-refresh/only-export-components': 'off',
      'react-hooks/purity': 'off',
    },
  },
])
