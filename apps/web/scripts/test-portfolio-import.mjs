import assert from 'node:assert/strict'
import test from 'node:test'
import { buildSnapshotPlans, parsePortfolioText, requestWeight, validatePortfolioDrafts } from '../src/lib/portfolio-import.ts'

const plan = holdings => ({ plan_id: 'fixed', label: '', holdings })
test('UTF-8中文表头、BOM、百分比与前导零保留，导入和手工请求一致', () => {
  const csv = '\uFEFF证券代码,名称,权重\r\n600519.SH,贵州茅台,40%\r\n600036.SH,招商银行,35%\r\n000333.SZ,美的集团,25%\r\n'
  const imported = buildSnapshotPlans([plan(parsePortfolioText(csv))])
  const manual = buildSnapshotPlans([plan([{ symbol: '600519.SH', weight: '.4' }, { symbol: '600036.SH', weight: '.35' }, { symbol: '000333.SZ', weight: '.25' }])])
  assert.deepEqual(imported, manual)
  assert.equal(imported[0].holdings[2].symbol, '000333.SZ')
})
test('TSV、单列等权文本、quoted CSV和分号均可导入', () => {
  assert.deepEqual(parsePortfolioText('symbol\tweight\n000001.SZ\t1\n600000.SH\t2'), [{ symbol: '000001.SZ', weight: '1' }, { symbol: '600000.SH', weight: '2' }])
  assert.deepEqual(parsePortfolioText('000001\n600000'), [{ symbol: '000001', weight: '' }, { symbol: '600000', weight: '' }])
  assert.equal(parsePortfolioText('symbol,name,weight\n"000001.SZ","名称,含逗号",1')[0].symbol, '000001.SZ')
  assert.equal(parsePortfolioText('代码;权重\n000001;20')[0].weight, '20')
  assert.equal(parsePortfolioText('股票代码,权重（%）\n000333,25')[0].weight, '25')
  assert.throws(() => parsePortfolioText('股票代码,未知数值列\n000333,25'), /未识别权重列/)
})
test('不对原始重复和零权重行去重或截断，100行可提交、101行拒绝', () => {
  const rows = Array.from({ length: 100 }, (_, i) => ({ symbol: '000001.SZ', weight: i ? '0' : '1' }))
  assert.equal(buildSnapshotPlans([plan(rows)])[0].holdings.length, 100)
  assert.throws(() => buildSnapshotPlans([plan([...rows, rows[0]])]), /100/)
  assert.throws(() => parsePortfolioText(Array(101).fill('000001,1').join('\n')), /100/)
})
test('最多5方案各100行，构造请求保留全部500行和独立权重', () => {
  const drafts = Array.from({ length: 5 }, (_, p) => ({ plan_id: `p${p}`, label: '', holdings: Array.from({ length: 100 }, (_, i) => ({ symbol: `600${String(i).padStart(3, '0')}.SH`, weight: String(p + 1) })) }))
  const output = buildSnapshotPlans(drafts)
  assert.equal(output.length, 5)
  assert.equal(output.reduce((n, p) => n + p.holdings.length, 0), 500)
  assert.equal(output[4].holdings[0].weight, '5')
  assert.throws(() => buildSnapshotPlans([...drafts, { ...drafts[0], plan_id: 'six' }]), /5/)
})
test('拒绝负、非有限、全部零、混填或混单位权重，不静默等权', () => {
  for (const bad of ['-1', 'NaN', 'Infinity', '1e309', '3abc']) assert.throws(() => requestWeight(bad))
  assert.throws(() => parsePortfolioText('symbol,weight\n000001,0\n600000,0'), /大于零/)
  assert.throws(() => parsePortfolioText('symbol,weight\n000001,1\n600000,'), /全部/)
  assert.throws(() => parsePortfolioText('symbol,weight\n000001,40%\n600000,60'), /混用/)
})
test('十进制百分比不通过float舍入，空权重完全省略', () => {
  assert.equal(requestWeight('0.00000000000000000001%'), '0.0000000000000000000001')
  assert.deepEqual(buildSnapshotPlans([plan([{ symbol: '000001', weight: '' }])])[0].holdings, [{ symbol: '000001' }])
})
test('错误CSV、重复表头、空文件、编码错误明确拒绝', () => {
  for (const text of ['', 'symbol,weight\n', '"000001,1', 'symbol,weight,权重\n000001,1,2', 'weight,name\n1,A', '\uFFFD,1']) assert.throws(() => parsePortfolioText(text))
  assert.equal(validatePortfolioDrafts([plan([{ symbol: '  ', weight: '1' }])])[0].path.at(-1), 'symbol')
})
