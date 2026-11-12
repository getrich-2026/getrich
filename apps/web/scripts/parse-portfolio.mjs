// 与网页共用解析及完整请求构造，供受控端到端验收使用。
import { readFileSync } from 'node:fs'
import { buildSnapshotPlans, parsePortfolioText } from '../src/lib/portfolio-import.ts'
if (!process.argv[2]) throw new Error('Usage: node scripts/parse-portfolio.mjs file.csv')
const holdings = parsePortfolioText(readFileSync(process.argv[2], 'utf8'))
process.stdout.write(JSON.stringify({ plans: buildSnapshotPlans([{ plan_id: 'fixed', label: '', holdings }]) }))
