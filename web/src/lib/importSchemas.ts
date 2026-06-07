import { z } from 'zod'

export const strategyImportSchema = z.object({
  strategy_code: z.string().min(3).max(64),
  name: z.string().min(1).max(128),
  strategy_type: z.string().min(1).max(32),
  summary: z.string().max(500).optional(),
  description: z.string().optional(),
  detail_html: z.string().optional(),
  category_id: z.string().max(64).optional(),
  asset_class: z.string().min(1).max(32),
  market: z.string().min(1).max(32),
  risk_level: z.enum(['low', 'medium', 'high']),
  run_status: z.string().min(1).max(32),
  pub_status: z.string().min(1).max(32),
  author_id: z.string().min(1),
  cover_image: z.string().max(512).optional(),
  subscription_monthly: z.string().min(1),
  subscription_yearly: z.string().min(1),
  backtest_start: z.string().optional(),
  backtest_end: z.string().optional(),
})

export type StrategyImportFormValues = z.infer<typeof strategyImportSchema>
