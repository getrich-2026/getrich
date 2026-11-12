/** 浏览器本地持仓导入。保留原始行、重复项和零权重，交由后端按 PA-02 解析。 */
export interface HoldingDraft { symbol: string; weight: string }
export interface PortfolioDraft { plan_id: string; label: string; holdings: HoldingDraft[] }
export interface DraftIssue { path: (string | number)[]; message: string }

const SYMBOL_HEADERS = new Set(['symbol', 'stock_code', 'stockcode', 'ts_code', 'securitycode', '代码', '股票代码', '证券代码'])
const WEIGHT_HEADERS = new Set(['weight', '权重', '仓位', '比例', '持仓比例', '持仓权重', 'weight(%)', 'weight%', '权重(%)', '权重（%）', '持仓比例(%)', '持仓比例（%）', '比例(%)', '仓位(%)'])
const DECIMAL = /^\+?(?:\d+(?:\.\d*)?|\.\d+)(?:[%％])?$/

/** 百分号转换采用十进制字符串移位；不使用浮点计算或前端重新归一化。 */
export function requestWeight(raw: string): string {
  const text = raw.trim()
  if (!DECIMAL.test(text)) throw new Error('权重须为非负有限数值或百分比。')
  const percent = /[%％]$/.test(text)
  const decimal = text.replace(/[%％]$/, '').replace(/^\+/, '')
  let [whole, fraction = ''] = decimal.split('.')
  whole = whole || '0'
  if (percent) {
    whole = whole.padStart(3, '0')
    fraction = `${whole.slice(-2)}${fraction}`
    whole = whole.slice(0, -2)
  }
  whole = whole.replace(/^0+(?=\d)/, '')
  fraction = fraction.replace(/0+$/, '')
  return `${whole}${fraction ? `.${fraction}` : ''}`
}

export function validatePortfolioDrafts(plans: PortfolioDraft[]): DraftIssue[] {
  const issues: DraftIssue[] = []
  if (plans.length < 1 || plans.length > 5) issues.push({ path: ['plans'], message: '一次提交 1～5 个方案。' })
  plans.forEach((plan, p) => {
    if (plan.holdings.length < 1 || plan.holdings.length > 100) {
      issues.push({ path: ['plans', p, 'holdings'], message: '每个方案须有 1～100 行，重复和零权重行也计数。' })
    }
    let positive = false
    const filled = plan.holdings.filter(h => h.weight.trim() !== '')
    if (filled.length > 0 && filled.length !== plan.holdings.length) {
      issues.push({ path: ['plans', p, 'holdings'], message: '同一方案的权重须全部填写或全部留空。' })
    }
    const percentCount = filled.filter(h => /[%％]$/.test(h.weight.trim())).length
    if (percentCount > 0 && percentCount !== filled.length) {
      issues.push({ path: ['plans', p, 'holdings'], message: '请统一使用相对数值或带百分号的权重，不要混用。' })
    }
    plan.holdings.forEach((holding, i) => {
      const symbol = holding.symbol.trim()
      if (!symbol || symbol.length > 64) issues.push({ path: ['plans', p, 'holdings', i, 'symbol'], message: '填写 1～64 字符的股票代码。' })
      if (!holding.weight.trim()) return
      try {
        const value = requestWeight(holding.weight)
        if (BigInt(value.replace('.', '')) > 0n) positive = true
      } catch {
        issues.push({ path: ['plans', p, 'holdings', i, 'weight'], message: '权重须为非负有限数值，不支持负数、NaN 或 Infinity。' })
      }
    })
    if (filled.length && !positive) issues.push({ path: ['plans', p, 'holdings'], message: '至少一行权重须大于零。' })
  })
  return issues
}

/** 文件导入与手工输入共用此请求构造，始终提交全部方案和全部原始行。 */
export function buildSnapshotPlans(plans: PortfolioDraft[]) {
  const issues = validatePortfolioDrafts(plans)
  if (issues.length) throw new Error(issues[0].message)
  return plans.map(plan => ({
    plan_id: plan.plan_id,
    ...(plan.label.trim() ? { label: plan.label.trim() } : {}),
    holdings: plan.holdings.map(holding => ({
      symbol: holding.symbol.trim(),
      ...(holding.weight.trim() ? { weight: requestWeight(holding.weight) } : {}),
    })),
  }))
}

function delimiterFor(text: string): string {
  const first = text.split(/\r?\n/).find(line => line.trim()) || ''
  let quoted = false
  const counts = new Map([ [',', 0], ['\t', 0], [';', 0] ])
  for (let i = 0; i < first.length; i++) {
    if (first[i] === '"') {
      if (quoted && first[i + 1] === '"') i++
      else quoted = !quoted
    } else if (!quoted && counts.has(first[i])) counts.set(first[i], (counts.get(first[i]) || 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0]
}

function delimitedRows(text: string, delimiter: string): string[][] {
  const rows: string[][] = []
  let row: string[] = [], field = '', quoted = false, closed = false
  const endField = () => { row.push(field.trim()); field = ''; closed = false }
  const endRow = () => { endField(); if (row.some(value => value !== '')) rows.push(row); row = [] }
  for (let i = 0; i < text.length; i++) {
    const character = text[i]
    if (quoted) {
      if (character === '"') {
        if (text[i + 1] === '"') { field += '"'; i++ }
        else { quoted = false; closed = true }
      } else field += character
    } else if (character === delimiter) endField()
    else if (character === '\n' || character === '\r') {
      if (character === '\r' && text[i + 1] === '\n') i++
      endRow()
    } else if (character === '"' && !field.trim() && !closed) { field = ''; quoted = true }
    else if (closed && character.trim()) throw new Error('引号结束后出现非法字符，请检查 CSV 格式。')
    else if (character === '"') throw new Error('CSV 引号位置不正确。')
    else if (!closed) field += character
  }
  if (quoted) throw new Error('CSV 引号未闭合。')
  endRow()
  return rows
}

/** 支持 UTF-8 CSV、TSV 或单列文本；中文表头可选，股票代码始终保留为字符串。 */
export function parsePortfolioText(input: string): HoldingDraft[] {
  if (input.includes('\uFFFD')) throw new Error('文件编码无法识别，请另存为 UTF-8 CSV 或 TSV。')
  const text = input.replace(/^\uFEFF/, '')
  const rows = delimitedRows(text, delimiterFor(text))
  if (!rows.length) throw new Error('文件中没有持仓。')
  const header = rows[0].map(value => value.trim().toLowerCase().replace(/\s/g, ''))
  if (header.filter(value => SYMBOL_HEADERS.has(value)).length > 1 || header.filter(value => WEIGHT_HEADERS.has(value)).length > 1) throw new Error('代码或权重表头重复，请保留唯一列。')
  const symbolColumn = header.findIndex(value => SYMBOL_HEADERS.has(value))
  const weightColumn = header.findIndex(value => WEIGHT_HEADERS.has(value))
  if (symbolColumn < 0 && weightColumn >= 0) throw new Error('表头缺少股票代码列。')
  const hasHeader = symbolColumn >= 0
  if (hasHeader && weightColumn < 0 && header.some((value, index) => index !== symbolColumn && !['name', '名称', '股票名称', '证券名称'].includes(value))) throw new Error('未识别权重列，请使用“股票代码、权重”表头；不能把未知数值列静默当作等权。')
  const body = hasHeader ? rows.slice(1) : rows
  if (!body.length || body.length > 100) throw new Error('每个方案须有 1～100 行，重复和零权重行也计数。')
  const holdings = body.map((row, i) => {
    if (!hasHeader && row.length > 2) throw new Error(`第 ${i + 1} 行超过两列，请使用代码、权重表头。`)
    const symbol = row[hasHeader ? symbolColumn : 0] || ''
    const weight = hasHeader ? (weightColumn >= 0 ? row[weightColumn] || '' : '') : row[1] || ''
    return { symbol, weight }
  })
  const issues = validatePortfolioDrafts([{ plan_id: 'import', label: '', holdings }])
  if (issues.length) throw new Error(issues[0].message)
  return holdings
}
