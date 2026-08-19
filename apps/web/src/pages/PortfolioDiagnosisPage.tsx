import { useState, useMemo, useRef, useEffect } from 'react'
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts'

/* ─── Types ──────────────────────────────────────────────────────────────── */
interface StockInfo {
  ind: string; themes: string[]; tech: number; fund: number
  sig: 'buy' | 'sell' | 'hold' | 'watch'; sigTxt: string
}
interface PortfolioItem { name: string; amount: number }
interface ChatMessage   { role: 'ai' | 'user'; content: string }
type AnalysisResult = ReturnType<typeof runAnalysis>

/* ─── DB ─────────────────────────────────────────────────────────────────── */
const DB: Record<string, StockInfo> = {
  '宁德时代': { ind:'电力设备',  themes:['新能源','锂电池','储能'], tech:58, fund:72, sig:'hold', sigTxt:'持有观望' },
  '比亚迪':   { ind:'汽车',      themes:['新能源','电动车'],         tech:65, fund:75, sig:'buy',  sigTxt:'买入'    },
  '隆基绿能': { ind:'电力设备',  themes:['新能源','光伏'],           tech:42, fund:58, sig:'watch',sigTxt:'注意减仓'},
  '通威股份': { ind:'电力设备',  themes:['新能源','光伏'],           tech:38, fund:52, sig:'sell', sigTxt:'减仓'    },
  '寒武纪':   { ind:'半导体',    themes:['AI算力','芯片'],           tech:72, fund:45, sig:'hold', sigTxt:'持有'    },
  '海光信息': { ind:'半导体',    themes:['AI算力','CPU'],            tech:78, fund:55, sig:'buy',  sigTxt:'买入'    },
  '澜起科技': { ind:'半导体',    themes:['AI算力','DDR5'],           tech:70, fund:60, sig:'buy',  sigTxt:'买入'    },
  '天孚通信': { ind:'通信',      themes:['AI算力','光模块'],         tech:82, fund:68, sig:'buy',  sigTxt:'买入'    },
  '贵州茅台': { ind:'食品饮料',  themes:['白酒','消费'],             tech:68, fund:85, sig:'hold', sigTxt:'持有'    },
  '五粮液':   { ind:'食品饮料',  themes:['白酒','消费'],             tech:65, fund:80, sig:'hold', sigTxt:'持有'    },
  '恒瑞医药': { ind:'医药生物',  themes:['创新药'],                  tech:55, fund:70, sig:'hold', sigTxt:'持有'    },
  '迈瑞医疗': { ind:'医疗器械',  themes:['医疗','出海'],             tech:62, fund:78, sig:'buy',  sigTxt:'买入'    },
  '招商银行': { ind:'银行',      themes:['金融','高股息'],           tech:60, fund:75, sig:'hold', sigTxt:'持有'    },
  '中国平安': { ind:'保险',      themes:['金融'],                    tech:55, fund:65, sig:'hold', sigTxt:'持有'    },
  '腾讯控股': { ind:'互联网',    themes:['互联网','AI应用'],         tech:72, fund:82, sig:'buy',  sigTxt:'买入'    },
  '北方华创': { ind:'半导体设备',themes:['国产替代','半导体'],       tech:68, fund:72, sig:'buy',  sigTxt:'买入'    },
  '科大讯飞': { ind:'计算机',    themes:['AI应用','大模型'],         tech:60, fund:48, sig:'watch',sigTxt:'注意'    },
  '中芯国际': { ind:'半导体',    themes:['国产替代','芯片'],         tech:65, fund:68, sig:'buy',  sigTxt:'买入'    },
  '东方财富': { ind:'非银金融',  themes:['金融','互联网'],           tech:58, fund:62, sig:'hold', sigTxt:'持有'    },
  '万科A':    { ind:'房地产',    themes:['地产'],                    tech:30, fund:35, sig:'sell', sigTxt:'减仓'    },
}

const DEFAULT_PORTFOLIO: PortfolioItem[] = [
  { name:'宁德时代', amount:20 }, { name:'隆基绿能', amount:15 },
  { name:'通威股份', amount:10 }, { name:'寒武纪',   amount:12 },
  { name:'海光信息', amount:8  }, { name:'贵州茅台', amount:10 },
  { name:'恒瑞医药', amount:10 }, { name:'招商银行', amount:15 },
]

const LOADING_STEPS = [
  '正在计算行业集中度…', '正在识别隐性主题关联…',
  '正在评估逐仓健康度…', '正在与量化信号交叉比对…',
  'AI 正在生成诊断报告…',
]

const CHART_COLORS = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4','#ec4899','#84cc16']

/* ─── Analysis Engine ────────────────────────────────────────────────────── */
function runAnalysis(portfolio: PortfolioItem[]) {
  const total = portfolio.reduce((s, p) => s + p.amount, 0)
  const indMap: Record<string, number> = {}
  const themeMap: Record<string, { pct: number; stocks: string[] }> = {}

  portfolio.forEach(p => {
    const info = DB[p.name]; if (!info) return
    const pct  = (p.amount / total) * 100
    indMap[info.ind] = (indMap[info.ind] || 0) + pct
    info.themes.forEach(t => {
      if (!themeMap[t]) themeMap[t] = { pct:0, stocks:[] }
      themeMap[t].pct += pct; themeMap[t].stocks.push(p.name)
    })
  })

  const hhi = Object.values(indMap).reduce((s, w) => s + (w/100)**2, 0) * 10000

  const topThemes = Object.entries(themeMap)
    .filter(([,v]) => v.stocks.length >= 2)
    .sort((a,b) => b[1].pct - a[1].pct).slice(0,6)

  const scores = portfolio.map(p => {
    const info = DB[p.name] ?? { tech:50, fund:50, sig:'hold' as const, sigTxt:'持有', ind:'未知', themes:[] }
    const comp = Math.round(info.tech * 0.5 + info.fund * 0.5)
    return { ...p, ...info, comp, pct:(p.amount/total)*100 }
  })

  const avgHealth = scores.reduce((s,p) => s + p.comp, 0) / scores.length
  const pen = hhi > 2500 ? 20 : hhi > 1500 ? 10 : 0
  const overall = Math.min(99, Math.round(avgHealth - pen))

  const risks: { lv:'high'|'medium'|'low'; title:string; desc:string }[] = []
  Object.entries(indMap).forEach(([ind,pct]) => {
    if (pct > 40) risks.push({ lv:'high',   title:`行业高度集中：${ind}`, desc:`${ind} 行业占比高达 ${pct.toFixed(1)}%，超过 40% 警戒线，单一行业系统性回调风险极高。` })
    else if(pct>25) risks.push({ lv:'medium', title:`行业集中偏高：${ind}`, desc:`${ind} 行业占比 ${pct.toFixed(1)}%，建议关注是否需要适度减仓。` })
  })
  topThemes.forEach(([theme,data]) => {
    if (data.pct > 28) risks.push({ lv:'high', title:`隐性主题集中：${theme}`, desc:`${data.stocks.join('、')} 均属「${theme}」主题，合计仓位 ${data.pct.toFixed(1)}%，表面分散实为高度押注，波动时将同向运动。` })
  })
  const sellStocks = scores.filter(s => s.sig === 'sell')
  if (sellStocks.length) risks.push({ lv:'high', title:'减仓信号触发', desc:`${sellStocks.map(s=>s.name).join('、')} 当前触发平台减仓信号，建议优先评估是否调整。` })
  const lowH = scores.filter(s => s.comp < 50)
  if (lowH.length) risks.push({ lv:'medium', title:'低健康度标的', desc:`${lowH.map(s=>s.name).join('、')} 综合评分低于 50，技术面或基本面存在明显隐患。` })
  if (!risks.length) risks.push({ lv:'low', title:'整体风险可控', desc:'当前持仓未发现明显集中度或信号异常，建议保持定期观察。' })

  const topInd = Object.entries(indMap).sort((a,b) => b[1]-a[1])[0] as [string,number]
  const indChartData  = Object.entries(indMap).sort((a,b)=>b[1]-a[1]).map(([name,value])=>({ name, value:+value.toFixed(1) }))
  const themeChartData = topThemes.map(([name,data]) => ({ name, value:+data.pct.toFixed(1), fill: data.pct>35?'#ef4444':data.pct>20?'#f59e0b':'#3b82f6' }))

  return { indMap, themeMap, topThemes, hhi, scores, overall, risks, total, indChartData, themeChartData, topInd }
}

/* ─── Chat AI ────────────────────────────────────────────────────────────── */
function genReply(q: string, a: AnalysisResult): string {
  const { scores, indMap, topThemes } = a
  const topInd   = a.topInd
  const topTheme = topThemes[0] as [string,{pct:number;stocks:string[]}] | undefined
  const sells    = scores.filter(s => s.sig==='sell')
  const watches  = scores.filter(s => s.sig==='watch')
  const buys     = scores.filter(s => s.sig==='buy')
  const worst    = [...scores].sort((x,y) => x.comp-y.comp)[0]
  const ql       = q.toLowerCase()

  if (ql.includes('最大')||ql.includes('主要')||ql.includes('问题'))
    return `你当前最大的问题是<b>行业集中度过高</b>。${topInd[0]} 行业占比 ${topInd[1].toFixed(1)}%，超过建议 30% 上限。${topTheme?`同时「${topTheme[0]}」主题隐性集中（${topTheme[1].stocks.join('、')} 合计 ${topTheme[1].pct.toFixed(1)}%），实际风险远比账面严重。`:''}`
  if (ql.includes('新能源')||ql.includes('光伏')||ql.includes('锂电'))
    return `你的新能源方向（含电力设备）合计约 ${(indMap['电力设备']??0).toFixed(1)}%。通威股份触发减仓信号，隆基绿能处于注意区间，光伏行业面临供给过剩压力，建议将该方向降至 20% 以下。`
  if (ql.includes('优先')||ql.includes('哪支')||ql.includes('重点'))
    return `建议优先关注 <b>${worst.name}</b>（综合评分 ${worst.comp}，持仓中最低）。${sells.length?`同时 ${sells.map(s=>s.name).join('、')} 已触发减仓信号，`:''}需要第一优先级评估是否继续持有。`
  if (ql.includes('优化')||ql.includes('调整')||ql.includes('结构'))
    return `优化三步走：① 降低 ${topInd[0]} 方向集中度，换仓至相关性更低行业；② ${sells.length?`处理 ${sells.map(s=>s.name).join('、')} 的减仓信号`:'保持现有止损纪律'}；③ 新增资金优先配置买入信号标的：${buys.map(s=>s.name).join('、')||'暂无'}。`
  if (ql.includes('加仓')||ql.includes('买入'))
    return `当前平台买入信号标的：<b>${buys.map(s=>s.name).join('、')||'暂无'}</b>。但建议先处理集中度问题，避免在结构未优化前继续加码同方向。`
  if (ql.includes('减仓')||ql.includes('卖出'))
    return `信号评级：${[...sells.map(s=>`${s.name}（减仓）`),...watches.map(s=>`${s.name}（注意）`)].join('、')||'暂无明确减仓信号'}。信号仅供参考，请结合持仓成本综合判断。`
  return `基于你当前持仓，集中度是核心风险——${topInd[0]} 方向 ${topInd[1].toFixed(1)}% 的暴露是重中之重。可结合报告中的风险预警逐项评估，或告诉我你对哪支标的有具体问题。`
}

/* ─── Design Tokens ──────────────────────────────────────────────────────── */
const sc = (v:number) => v>=70 ? '#10b981' : v>=50 ? '#f59e0b' : '#ef4444'
const sg = (v:number) => v>=70 ? 'rgba(16,185,129,0.35)' : v>=50 ? 'rgba(245,158,11,0.35)' : 'rgba(239,68,68,0.35)'

/* ─── Score Ring ─────────────────────────────────────────────────────────── */
function ScoreRing({ value, size=130 }: { value:number; size?:number }) {
  const r    = size/2 - 10
  const circ = 2 * Math.PI * r
  const dash = (value/100) * circ
  const color = sc(value)
  return (
    <svg width={size} height={size} style={{ transform:'rotate(-90deg)' }}>
      <defs>
        <filter id="ring-glow">
          <feGaussianBlur stdDeviation="3" result="blur"/>
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth={10}/>
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={10}
              strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
              filter="url(#ring-glow)"
              style={{ transition:'stroke-dasharray 1.2s cubic-bezier(0.4,0,0.2,1)' }}/>
    </svg>
  )
}

/* ─── Gradient Bar ───────────────────────────────────────────────────────── */
function GradBar({ value }: { value:number }) {
  const color = sc(value), glow = sg(value)
  const grad  = value>=70 ? 'linear-gradient(90deg,#059669,#10b981)'
              : value>=50 ? 'linear-gradient(90deg,#d97706,#f59e0b)'
              :             'linear-gradient(90deg,#dc2626,#ef4444)'
  return (
    <div style={{ display:'flex', alignItems:'center', gap:8 }}>
      <div style={{ flex:1, height:6, borderRadius:3, background:'var(--gr-border-light)', overflow:'hidden' }}>
        <div style={{ height:'100%', width:`${value}%`, borderRadius:3, background:grad,
                      boxShadow:`0 0 8px ${glow}`, transition:'width 0.8s cubic-bezier(0.4,0,0.2,1)' }}/>
      </div>
      <span style={{ fontSize:11, fontWeight:700, color, width:22, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>
        {value}
      </span>
    </div>
  )
}

/* ─── Ind Tag ────────────────────────────────────────────────────────────── */
const IND_COLORS: Record<string,[string,string]> = {
  '电力设备':  ['rgba(16,185,129,0.12)','#10b981'], '汽车':      ['rgba(16,185,129,0.12)','#10b981'],
  '半导体':    ['rgba(59,130,246,0.12)','#60a5fa'],  '半导体设备':['rgba(59,130,246,0.12)','#60a5fa'],
  '计算机':    ['rgba(59,130,246,0.12)','#60a5fa'],  '通信':      ['rgba(59,130,246,0.12)','#60a5fa'],
  '互联网':    ['rgba(59,130,246,0.12)','#60a5fa'],
  '食品饮料':  ['rgba(239,68,68,0.1)','#f87171'],
  '银行':      ['rgba(139,92,246,0.12)','#a78bfa'],  '保险':      ['rgba(139,92,246,0.12)','#a78bfa'],
  '非银金融':  ['rgba(139,92,246,0.12)','#a78bfa'],
  '医药生物':  ['rgba(245,158,11,0.12)','#fbbf24'],  '医疗器械':  ['rgba(245,158,11,0.12)','#fbbf24'],
  '房地产':    ['rgba(100,116,139,0.12)','#94a3b8'],
}
function IndTag({ ind }: { ind:string }) {
  const [bg, color] = IND_COLORS[ind] ?? ['rgba(100,116,139,0.1)','#94a3b8']
  return (
    <span style={{ fontSize:10, padding:'2px 8px', borderRadius:4, fontWeight:600,
                   background:bg, color, border:`1px solid ${color}30`, whiteSpace:'nowrap' }}>
      {ind}
    </span>
  )
}

/* ─── Sig Badge ──────────────────────────────────────────────────────────── */
const SIG: Record<string,[string,string,string]> = {
  buy:  ['rgba(16,185,129,0.12)','#10b981','rgba(16,185,129,0.3)'],
  sell: ['rgba(239,68,68,0.12)', '#ef4444','rgba(239,68,68,0.3)'],
  hold: ['rgba(100,116,139,0.1)','#94a3b8','transparent'],
  watch:['rgba(245,158,11,0.12)','#f59e0b','rgba(245,158,11,0.3)'],
}
function SigBadge({ sig, txt }: { sig:string; txt:string }) {
  const [bg,color,shadow] = SIG[sig] ?? SIG.hold
  return (
    <span style={{ fontSize:10, padding:'3px 8px', borderRadius:6, fontWeight:700,
                   background:bg, color, border:`1px solid ${color}40`,
                   boxShadow: shadow!=='transparent' ? `0 0 8px ${shadow}` : 'none',
                   whiteSpace:'nowrap' }}>
      {txt}
    </span>
  )
}

/* ─── Accent Card ────────────────────────────────────────────────────────── */
function ACard({ children, accent, style }: {
  children:React.ReactNode; accent:string; style?:React.CSSProperties
}) {
  return (
    <div style={{ borderRadius:16, overflow:'hidden', background:'var(--gr-card)',
                  border:'1px solid var(--gr-border-light)',
                  boxShadow:'0 4px 24px rgba(0,0,0,0.07)', ...style }}>
      <div style={{ height:3, background:accent }}/>
      <div style={{ padding:'18px 20px' }}>{children}</div>
    </div>
  )
}

/* ─── Section Header ─────────────────────────────────────────────────────── */
function SHeader({ title, sub }: { title:string; sub:string }) {
  return (
    <div style={{ marginBottom:14 }}>
      <div style={{ fontSize:13, fontWeight:700, color:'var(--gr-text)', marginBottom:2 }}>{title}</div>
      <div style={{ fontSize:11, color:'var(--gr-text-tertiary)' }}>{sub}</div>
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN PAGE
   ═══════════════════════════════════════════════════════════════════════════ */
export default function PortfolioDiagnosisPage() {
  const [portfolio, setPortfolio]       = useState<PortfolioItem[]>(DEFAULT_PORTFOLIO)
  const [phase, setPhase]               = useState<'input'|'loading'|'results'>('input')
  const [loadingStep, setLoadingStep]   = useState(0)
  const [inputName, setInputName]       = useState('')
  const [inputAmount, setInputAmount]   = useState('')
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput]       = useState('')
  const [isTyping, setIsTyping]         = useState(false)
  const chatBoxRef  = useRef<HTMLDivElement>(null)
  const resultsRef  = useRef<HTMLDivElement>(null)

  const total    = portfolio.reduce((s,p) => s+p.amount, 0)
  const analysis = useMemo(
    () => phase==='results' ? runAnalysis(portfolio) : null,
    [portfolio, phase]
  )

  useEffect(() => {
    if (phase !== 'loading') return
    let step = 0
    const iv = setInterval(() => {
      step++; setLoadingStep(step)
      if (step >= LOADING_STEPS.length) {
        clearInterval(iv)
        setTimeout(() => { setPhase('results'); setTimeout(() => resultsRef.current?.scrollIntoView({ behavior:'smooth' }), 80) }, 400)
      }
    }, 600)
    return () => clearInterval(iv)
  }, [phase])

  useEffect(() => { if (chatBoxRef.current) chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight }, [chatMessages, isTyping])

  const addStock = () => {
    if (!inputName.trim() || !inputAmount) return
    if (!DB[inputName])                            { alert('请从建议列表中选择股票'); return }
    if (portfolio.find(p => p.name===inputName))   { alert('该股票已在持仓中');       return }
    setPortfolio(prev => [...prev, { name:inputName, amount:parseFloat(inputAmount) }])
    setInputName(''); setInputAmount('')
  }

  const sendChat = (question?: string) => {
    const q = question ?? chatInput.trim()
    if (!q || !analysis) return
    setChatMessages(prev => [...prev, { role:'user', content:q }])
    if (!question) setChatInput('')
    setIsTyping(true)
    setTimeout(() => { setIsTyping(false); setChatMessages(prev => [...prev, { role:'ai', content:genReply(q, analysis) }]) }, 900)
  }

  return (
    <div>
      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <div style={{ position:'relative', overflow:'hidden',
                    background:'linear-gradient(135deg,#0a0f1e 0%,#0f2557 45%,#1a1145 80%,#0a0f1e 100%)',
                    padding:'40px 24px 36px' }}>
        {/* Glow orbs */}
        {/* 显式标注元素类型：三个光斑各自只给了 top/right/left/bottom 里的一部分 */}
        {([
          { top:-100, right:-80,  w:380, h:380, bg:'rgba(99,102,241,0.18)', blur:80 },
          { top:10,   left:'40%', w:140, h:140, bg:'rgba(59,130,246,0.12)', blur:40 },
          { bottom:-80, left:60,  w:260, h:260, bg:'rgba(139,92,246,0.12)', blur:60 },
        ] as { top?:number|string; right?:number|string; left?:number|string; bottom?:number|string
               w:number; h:number; bg:string; blur:number }[]).map((o,i) => (
          <div key={i} style={{ position:'absolute', borderRadius:'50%', pointerEvents:'none',
                                top:o.top, right:o.right, left:o.left, bottom:o.bottom,
                                width:o.w, height:o.h, background:o.bg, filter:`blur(${o.blur}px)` }}/>
        ))}

        {/* Dot grid overlay */}
        <div style={{ position:'absolute', inset:0, pointerEvents:'none', opacity:0.06,
                      backgroundImage:'radial-gradient(circle, #fff 1px, transparent 1px)',
                      backgroundSize:'28px 28px' }}/>

        <div style={{ maxWidth:900, margin:'0 auto', position:'relative' }}>
          <div style={{ display:'flex', gap:8, marginBottom:16, flexWrap:'wrap' }}>
            {[
              { t:'AI POWERED',  bg:'rgba(59,130,246,0.2)',  c:'#93c5fd',  b:'rgba(99,179,237,0.3)'  },
              { t:'量化分析',    bg:'rgba(139,92,246,0.18)', c:'#c4b5fd',  b:'rgba(139,92,246,0.3)'  },
              { t:'三维诊断',    bg:'rgba(16,185,129,0.15)', c:'#6ee7b7',  b:'rgba(16,185,129,0.25)' },
            ].map(tag => (
              <span key={tag.t} style={{ fontSize:10, fontWeight:700, padding:'4px 12px', borderRadius:20,
                                         letterSpacing:'0.06em', background:tag.bg, color:tag.c,
                                         border:`1px solid ${tag.b}` }}>
                {tag.t}
              </span>
            ))}
          </div>

          <h1 style={{ fontSize:32, fontWeight:900, margin:'0 0 10px', lineHeight:1.1,
                       background:'linear-gradient(135deg,#ffffff 0%,#bfdbfe 45%,#c4b5fd 100%)',
                       WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>
            持仓诊断中心
          </h1>
          <p style={{ color:'rgba(255,255,255,0.4)', fontSize:13, margin:0 }}>
            集中度风险 · 持仓健康度 · 量化信号匹配 — 三维模型深度解析你的组合
          </p>
        </div>
      </div>

      <div style={{ maxWidth:900, margin:'0 auto', padding:'24px 24px 60px' }}>

        {/* ── Input Card ───────────────────────────────────────────────────── */}
        <div style={{ borderRadius:16, overflow:'hidden', marginBottom:14,
                      background:'var(--gr-card)', border:'1px solid var(--gr-border-light)',
                      boxShadow:'0 4px 28px rgba(0,0,0,0.08)' }}>
          <div style={{ height:3, background:'linear-gradient(90deg,#3b82f6,#8b5cf6,#06b6d4)' }}/>
          <div style={{ padding:'20px' }}>

            {/* Header */}
            <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between',
                          marginBottom:18, flexWrap:'wrap', gap:12 }}>
              <div>
                <h2 style={{ fontSize:14, fontWeight:700, color:'var(--gr-text)', margin:'0 0 3px' }}>我的持仓</h2>
                <p style={{ fontSize:11, color:'var(--gr-text-tertiary)', margin:0 }}>输入每支标的的持仓金额（万元）</p>
              </div>
              <div style={{ display:'flex', gap:20 }}>
                {[{ label:'总金额', val:total.toFixed(1), unit:'万' },
                  { label:'持仓数', val:`${portfolio.length}`, unit:'支' }].map(m => (
                  <div key={m.label} style={{ textAlign:'right' }}>
                    <div style={{ fontSize:10, color:'var(--gr-text-tertiary)', marginBottom:2 }}>{m.label}</div>
                    <div style={{ fontSize:16, fontWeight:800, color:'var(--gr-text)', fontVariantNumeric:'tabular-nums', lineHeight:1 }}>
                      {m.val}<span style={{ fontSize:11, fontWeight:400, color:'var(--gr-text-tertiary)', marginLeft:2 }}>{m.unit}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Table */}
            <div style={{ overflowX:'auto', marginBottom:16 }}>
              <table style={{ width:'100%', borderCollapse:'collapse' }}>
                <thead>
                  <tr style={{ borderBottom:'1px solid var(--gr-border-light)' }}>
                    {['股票名称','行业','主题标签','持仓（万）','仓位占比',''].map(h => (
                      <th key={h} style={{ textAlign:'left', paddingBottom:10, paddingRight:14,
                                           fontSize:10, fontWeight:600, letterSpacing:'0.04em',
                                           color:'var(--gr-text-tertiary)', whiteSpace:'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {portfolio.map((p, i) => {
                    const info = DB[p.name]
                    const pct  = total > 0 ? (p.amount/total*100) : 0
                    const barC = pct>30 ? '#ef4444' : pct>20 ? '#f59e0b' : '#3b82f6'
                    return (
                      <tr key={p.name}
                          style={{ borderBottom:'1px solid var(--gr-border-light)', transition:'background 0.15s' }}
                          onMouseEnter={e => (e.currentTarget.style.background='rgba(59,130,246,0.03)')}
                          onMouseLeave={e => (e.currentTarget.style.background='transparent')}>
                        <td style={{ padding:'10px 14px 10px 0', fontSize:13, fontWeight:700, color:'var(--gr-text)' }}>{p.name}</td>
                        <td style={{ padding:'10px 14px 10px 0' }}><IndTag ind={info?.ind??'未知'}/></td>
                        <td style={{ padding:'10px 14px 10px 0' }}>
                          <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
                            {info?.themes.slice(0,2).map(t => (
                              <span key={t} style={{ fontSize:10, padding:'2px 6px', borderRadius:4,
                                                     background:'var(--gr-border-light)', color:'var(--gr-text-secondary)' }}>{t}</span>
                            ))}
                          </div>
                        </td>
                        <td style={{ padding:'10px 14px 10px 0', fontSize:13, fontWeight:600, color:'var(--gr-text)', fontVariantNumeric:'tabular-nums' }}>{p.amount}</td>
                        <td style={{ padding:'10px 14px 10px 0', minWidth:120 }}>
                          <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                            <div style={{ flex:1, height:4, borderRadius:2, background:'var(--gr-border-light)', overflow:'hidden' }}>
                              <div style={{ height:'100%', width:`${Math.min(100,pct*2)}%`, borderRadius:2, background:barC }}/>
                            </div>
                            <span style={{ fontSize:11, fontWeight:700, color:barC, minWidth:38, fontVariantNumeric:'tabular-nums' }}>{pct.toFixed(1)}%</span>
                          </div>
                        </td>
                        <td style={{ padding:'10px 0' }}>
                          <button onClick={() => setPortfolio(prev=>prev.filter((_,idx)=>idx!==i))}
                            style={{ width:24, height:24, borderRadius:6, border:'1px solid var(--gr-border-light)',
                                     background:'transparent', cursor:'pointer', fontSize:10,
                                     color:'var(--gr-text-tertiary)', display:'flex', alignItems:'center', justifyContent:'center', transition:'all 0.15s' }}
                            onMouseEnter={e=>{const el=e.currentTarget;el.style.background='rgba(239,68,68,0.1)';el.style.color='#ef4444';el.style.borderColor='rgba(239,68,68,0.3)'}}
                            onMouseLeave={e=>{const el=e.currentTarget;el.style.background='transparent';el.style.color='var(--gr-text-tertiary)';el.style.borderColor='var(--gr-border-light)'}}>✕</button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Add row */}
            <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
              <input list="stock-dl" value={inputName} onChange={e=>setInputName(e.target.value)}
                placeholder="股票名称"
                style={{ flex:1, minWidth:140, padding:'9px 12px', borderRadius:8, fontSize:12, outline:'none',
                         background:'var(--gr-border-light)', border:'1px solid transparent', color:'var(--gr-text)', transition:'border-color 0.15s' }}
                onFocus={e=>e.target.style.borderColor='rgba(59,130,246,0.5)'}
                onBlur={e=>e.target.style.borderColor='transparent'}/>
              <datalist id="stock-dl">{Object.keys(DB).map(n=><option key={n} value={n}/>)}</datalist>
              <input type="number" min={0.1} step={0.1} value={inputAmount}
                onChange={e=>setInputAmount(e.target.value)} onKeyDown={e=>e.key==='Enter'&&addStock()}
                placeholder="金额（万元）"
                style={{ width:130, padding:'9px 12px', borderRadius:8, fontSize:12, outline:'none',
                         background:'var(--gr-border-light)', border:'1px solid transparent', color:'var(--gr-text)', transition:'border-color 0.15s' }}
                onFocus={e=>e.target.style.borderColor='rgba(59,130,246,0.5)'}
                onBlur={e=>e.target.style.borderColor='transparent'}/>
              <button onClick={addStock}
                style={{ padding:'9px 16px', borderRadius:8, fontSize:12, fontWeight:600, cursor:'pointer',
                         background:'rgba(59,130,246,0.1)', border:'1px solid rgba(59,130,246,0.2)', color:'#3b82f6', transition:'all 0.15s' }}
                onMouseEnter={e=>{const el=e.currentTarget;el.style.background='rgba(59,130,246,0.18)';el.style.borderColor='rgba(59,130,246,0.4)'}}
                onMouseLeave={e=>{const el=e.currentTarget;el.style.background='rgba(59,130,246,0.1)';el.style.borderColor='rgba(59,130,246,0.2)'}}>
                ＋ 添加
              </button>
            </div>
          </div>
        </div>

        {/* ── Analyze Button ───────────────────────────────────────────────── */}
        {phase !== 'results' && (
          <button onClick={() => { if(portfolio.length<2){alert('请至少添加 2 支股票');return} setPhase('loading');setLoadingStep(0);window.scrollTo({top:0,behavior:'smooth'}) }}
            style={{ width:'100%', padding:'15px', borderRadius:12, fontSize:14, fontWeight:800,
                     color:'white', cursor:'pointer', marginBottom:16, border:'none', letterSpacing:'0.03em',
                     background:'linear-gradient(135deg,#2563eb 0%,#7c3aed 100%)',
                     boxShadow:'0 4px 20px rgba(37,99,235,0.4),0 2px 8px rgba(124,58,237,0.2)',
                     transition:'all 0.2s' }}
            onMouseEnter={e=>{const el=e.currentTarget;el.style.transform='translateY(-2px)';el.style.boxShadow='0 8px 30px rgba(37,99,235,0.45),0 4px 14px rgba(124,58,237,0.3)'}}
            onMouseLeave={e=>{const el=e.currentTarget;el.style.transform='translateY(0)';el.style.boxShadow='0 4px 20px rgba(37,99,235,0.4),0 2px 8px rgba(124,58,237,0.2)'}}>
            🔍 开始 AI 持仓诊断
          </button>
        )}

        {/* ── Loading ──────────────────────────────────────────────────────── */}
        {phase === 'loading' && (
          <div style={{ borderRadius:16, padding:44, textAlign:'center', marginBottom:16,
                        background:'var(--gr-card)', border:'1px solid var(--gr-border-light)',
                        boxShadow:'0 8px 40px rgba(0,0,0,0.08)' }}>
            <div style={{ display:'flex', justifyContent:'center', gap:10, marginBottom:28 }}>
              {[0,1,2,3,4].map(i => (
                <div key={i} style={{ width:10, height:10, borderRadius:'50%',
                                      background:'linear-gradient(135deg,#3b82f6,#8b5cf6)',
                                      animation:`gr-bounce 1.4s infinite ${i*0.15}s` }}/>
              ))}
            </div>
            <div style={{ fontSize:15, fontWeight:700, color:'var(--gr-text)', marginBottom:6 }}>AI 正在分析你的持仓</div>
            <div style={{ fontSize:12, color:'var(--gr-text-tertiary)', marginBottom:24 }}>
              {LOADING_STEPS[Math.min(loadingStep, LOADING_STEPS.length-1)]}
            </div>

            {/* Step indicators */}
            <div style={{ display:'flex', alignItems:'center', justifyContent:'center', gap:4, marginBottom:24, flexWrap:'wrap' }}>
              {LOADING_STEPS.map((_, i) => (
                <div key={i} style={{ display:'flex', alignItems:'center', gap:4 }}>
                  <div style={{ width:22, height:22, borderRadius:'50%', fontSize:9, fontWeight:800,
                                display:'flex', alignItems:'center', justifyContent:'center', transition:'all 0.4s',
                                background: i<loadingStep ? 'linear-gradient(135deg,#3b82f6,#8b5cf6)' : 'var(--gr-border-light)',
                                color: i<loadingStep ? 'white' : 'var(--gr-text-tertiary)',
                                boxShadow: i<loadingStep ? '0 0 10px rgba(59,130,246,0.4)' : 'none' }}>
                    {i < loadingStep ? '✓' : i+1}
                  </div>
                  {i < LOADING_STEPS.length-1 && (
                    <div style={{ width:24, height:2, borderRadius:1, transition:'all 0.4s',
                                  background: i<loadingStep-1 ? 'linear-gradient(90deg,#3b82f6,#8b5cf6)' : 'var(--gr-border-light)' }}/>
                  )}
                </div>
              ))}
            </div>

            <div style={{ maxWidth:340, margin:'0 auto', height:6, borderRadius:3,
                          background:'var(--gr-border-light)', overflow:'hidden' }}>
              <div style={{ height:'100%', borderRadius:3, transition:'width 0.5s ease',
                            width:`${(loadingStep/LOADING_STEPS.length)*100}%`,
                            background:'linear-gradient(90deg,#3b82f6,#8b5cf6)',
                            boxShadow:'0 0 10px rgba(59,130,246,0.5)' }}/>
            </div>
          </div>
        )}

        {/* ── Results ──────────────────────────────────────────────────────── */}
        {phase === 'results' && analysis && (
          <div ref={resultsRef} style={{ opacity:0, animation:'fadeIn 0.4s ease-out forwards' }}>

            <button onClick={()=>{setPhase('input');setChatMessages([])}}
              style={{ marginBottom:16, fontSize:11, padding:'6px 14px', borderRadius:8, cursor:'pointer',
                       background:'var(--gr-border-light)', border:'1px solid var(--gr-border-light)',
                       color:'var(--gr-text-secondary)', transition:'all 0.15s' }}
              onMouseEnter={e=>e.currentTarget.style.color='#3b82f6'}
              onMouseLeave={e=>e.currentTarget.style.color='var(--gr-text-secondary)'}>
              ← 重新编辑持仓
            </button>

            {/* Score Hero */}
            <ScoreHero analysis={analysis} portfolioLen={portfolio.length}/>

            {/* Charts */}
            <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(300px,1fr))', gap:16, marginBottom:16 }}>
              <ACard accent="linear-gradient(90deg,#3b82f6,#06b6d4)">
                <SHeader title="行业分布" sub="各行业占总仓位比例"/>
                <ResponsiveContainer width="100%" height={210}>
                  <PieChart>
                    <Pie data={analysis.indChartData} cx="50%" cy="50%"
                         innerRadius={56} outerRadius={82} dataKey="value" paddingAngle={3}>
                      {analysis.indChartData.map((_,i) => <Cell key={i} fill={CHART_COLORS[i%CHART_COLORS.length]} stroke="transparent"/>)}
                    </Pie>
                    <Tooltip formatter={(v:number)=>[`${v}%`,'']}
                      contentStyle={{ background:'var(--gr-card)', border:'1px solid var(--gr-border-light)', borderRadius:10, fontSize:12, boxShadow:'0 4px 20px rgba(0,0,0,0.1)' }}/>
                    <Legend iconSize={8} iconType="circle" wrapperStyle={{ fontSize:11 }}/>
                  </PieChart>
                </ResponsiveContainer>
              </ACard>

              <ACard accent="linear-gradient(90deg,#8b5cf6,#ec4899)">
                <SHeader title="隐性主题集中度" sub="跨行业主题合计占比（红 = 高风险）"/>
                <ResponsiveContainer width="100%" height={210}>
                  <BarChart data={analysis.themeChartData} margin={{ top:4,right:8,bottom:4,left:-16 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--gr-border-light)" vertical={false}/>
                    <XAxis dataKey="name" tick={{ fontSize:10, fill:'var(--gr-text-tertiary)' }} axisLine={false} tickLine={false}/>
                    <YAxis tick={{ fontSize:10, fill:'var(--gr-text-tertiary)' }} tickFormatter={v=>`${v}%`} axisLine={false} tickLine={false}/>
                    <Tooltip formatter={(v:number)=>[`${v}%`,'仓位占比']}
                      contentStyle={{ background:'var(--gr-card)', border:'1px solid var(--gr-border-light)', borderRadius:10, fontSize:12, boxShadow:'0 4px 20px rgba(0,0,0,0.1)' }}/>
                    <Bar dataKey="value" radius={[6,6,0,0]}>
                      {analysis.themeChartData.map((d,i)=><Cell key={i} fill={d.fill}/>)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </ACard>
            </div>

            {/* Risk */}
            <RiskSection risks={analysis.risks}/>

            {/* Health */}
            <HealthSection scores={analysis.scores}/>

            {/* Report */}
            <ReportSection analysis={analysis} portfolioLen={portfolio.length}/>

            {/* Chat */}
            <ChatSection
              messages={chatMessages} input={chatInput} setInput={setChatInput}
              onSend={()=>sendChat()} onSuggest={(q)=>sendChat(q)}
              isTyping={isTyping} chatBoxRef={chatBoxRef}/>
          </div>
        )}
      </div>

      <style>{`
        @keyframes gr-bounce {
          0%,80%,100%{ transform:translateY(0) scale(0.75); opacity:0.35; }
          40%         { transform:translateY(-9px) scale(1.15); opacity:1; }
        }
      `}</style>
    </div>
  )
}

/* ─── Score Hero ─────────────────────────────────────────────────────────── */
function ScoreHero({ analysis, portfolioLen }: { analysis:AnalysisResult; portfolioLen:number }) {
  const s      = analysis.overall
  const color  = sc(s), glow = sg(s)
  const label  = s>=75 ? '持仓健康' : s>=55 ? '中等风险' : '高风险'
  const topInd = analysis.topInd
  const tiC    = topInd[1]>40 ? '#ef4444' : topInd[1]>25 ? '#f59e0b' : '#10b981'
  const hhiC   = analysis.hhi>2500 ? '#ef4444' : analysis.hhi>1500 ? '#f59e0b' : '#10b981'
  const hhiL   = analysis.hhi>2500 ? '高度集中' : analysis.hhi>1500 ? '中度集中' : '分散良好'
  const warnCnt = analysis.scores.filter(x=>x.sig==='sell'||x.sig==='watch').length

  return (
    <div style={{ borderRadius:16, overflow:'hidden', marginBottom:16,
                  background:'linear-gradient(135deg,#080d1a 0%,#0d1f4a 55%,#130d3a 100%)',
                  boxShadow:'0 8px 48px rgba(8,13,26,0.45)',
                  border:'1px solid rgba(255,255,255,0.06)' }}>
      <div style={{ padding:'24px 24px 20px' }}>
        <div style={{ display:'flex', gap:24, alignItems:'flex-start', flexWrap:'wrap' }}>

          {/* Ring */}
          <div style={{ display:'flex', flexDirection:'column', alignItems:'center', flexShrink:0 }}>
            <div style={{ position:'relative', width:130, height:130 }}>
              <ScoreRing value={s} size={130}/>
              <div style={{ position:'absolute', inset:0, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center' }}>
                <span style={{ fontSize:36, fontWeight:900, lineHeight:1, color, textShadow:`0 0 24px ${glow}`, fontVariantNumeric:'tabular-nums' }}>{s}</span>
                <span style={{ fontSize:10, color:'rgba(255,255,255,0.35)', marginTop:2 }}>健康分</span>
              </div>
            </div>
            <span style={{ marginTop:10, fontSize:12, fontWeight:700, padding:'4px 16px', borderRadius:20,
                           background:`${color}20`, color, border:`1px solid ${color}40`, boxShadow:`0 0 14px ${glow}` }}>
              {label}
            </span>
          </div>

          {/* Metrics */}
          <div style={{ flex:1, minWidth:200, display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:10 }}>
            {[
              { label:'HHI 集中度',  value:Math.round(analysis.hhi), hint:hhiL,          color:hhiC },
              { label:'最大行业占比', value:`${topInd[1].toFixed(0)}%`, hint:topInd[0],   color:tiC  },
              { label:'预警信号',    value:`${warnCnt} 支`,           hint:'减仓或注意',  color:warnCnt?'#f59e0b':'#10b981' },
              { label:'持仓支数',    value:portfolioLen,               hint:'当前诊断',    color:'rgba(255,255,255,0.65)' },
              { label:'综合健康度',  value:s,                          hint:'综合评分',    color },
              { label:'总仓位',      value:`${analysis.total.toFixed(0)}万`, hint:'诊断组合', color:'rgba(255,255,255,0.65)' },
            ].map(m => (
              <div key={m.label} style={{ padding:'13px 14px', borderRadius:10,
                                          background:'rgba(255,255,255,0.04)',
                                          border:'1px solid rgba(255,255,255,0.07)',
                                          backdropFilter:'blur(8px)' }}>
                <div style={{ fontSize:10, color:'rgba(255,255,255,0.3)', marginBottom:5 }}>{m.label}</div>
                <div style={{ fontSize:18, fontWeight:900, color:m.color, fontVariantNumeric:'tabular-nums', lineHeight:1, textShadow: m.color!=='rgba(255,255,255,0.65)'?`0 0 10px ${m.color}44`:'none' }}>{m.value}</div>
                <div style={{ fontSize:10, color:'rgba(255,255,255,0.25)', marginTop:4 }}>{m.hint}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div style={{ padding:'8px 24px', borderTop:'1px solid rgba(255,255,255,0.05)',
                    background:'rgba(0,0,0,0.25)', fontSize:10, color:'rgba(255,255,255,0.2)' }}>
        ⚡ 基于行业集中度 HHI 指数 · 逐仓技术/基本面评分 · 量化信号交叉比对 三维综合评定
      </div>
    </div>
  )
}

/* ─── Risk Section ───────────────────────────────────────────────────────── */
const RISK_CFG = {
  high:   { bar:'#ef4444', bg:'rgba(239,68,68,0.05)',   border:'rgba(239,68,68,0.14)',  ico:'🔴' },
  medium: { bar:'#f59e0b', bg:'rgba(245,158,11,0.05)',  border:'rgba(245,158,11,0.14)', ico:'🟡' },
  low:    { bar:'#10b981', bg:'rgba(16,185,129,0.05)',  border:'rgba(16,185,129,0.14)', ico:'🟢' },
}
function RiskSection({ risks }: { risks:AnalysisResult['risks'] }) {
  return (
    <ACard accent="linear-gradient(90deg,#ef4444,#f59e0b,#10b981)" style={{ marginBottom:16 }}>
      <SHeader title="⚠️ 风险预警" sub="AI 识别出以下持仓风险点"/>
      <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
        {risks.map((r,i) => {
          const cfg = RISK_CFG[r.lv]
          return (
            <div key={i} style={{ display:'flex', borderRadius:10, overflow:'hidden',
                                   border:`1px solid ${cfg.border}`, background:cfg.bg }}>
              <div style={{ width:3, background:cfg.bar, flexShrink:0 }}/>
              <div style={{ padding:'11px 14px', display:'flex', gap:10 }}>
                <span style={{ fontSize:14, flexShrink:0, marginTop:1 }}>{cfg.ico}</span>
                <div>
                  <div style={{ fontSize:12, fontWeight:700, color:'var(--gr-text)', marginBottom:4 }}>{r.title}</div>
                  <div style={{ fontSize:11, lineHeight:1.65, color:'var(--gr-text-secondary)' }}>{r.desc}</div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </ACard>
  )
}

/* ─── Health Section ─────────────────────────────────────────────────────── */
function HealthSection({ scores }: { scores:AnalysisResult['scores'] }) {
  const sorted = [...scores].sort((a,b)=>a.comp-b.comp)
  const prio = (s: typeof sorted[0]) =>
    s.comp<50      ? { t:'⚡ 优先关注',  c:'#ef4444' } :
    s.sig==='sell' ? { t:'📉 考虑减仓',  c:'#f59e0b' } :
    s.sig==='buy'  ? { t:'✅ 可关注加仓',c:'#10b981' } :
                     { t:'👀 正常观察',  c:'var(--gr-text-tertiary)' }
  return (
    <ACard accent="linear-gradient(90deg,#3b82f6,#10b981)" style={{ marginBottom:16 }}>
      <SHeader title="逐仓健康度评估" sub="技术面 + 基本面综合评分，按评分从低到高排列"/>
      <div style={{ overflowX:'auto' }}>
        <table style={{ width:'100%', borderCollapse:'collapse' }}>
          <thead>
            <tr style={{ borderBottom:'1px solid var(--gr-border-light)' }}>
              {['标的','技术面','基本面','综合评分','平台信号','建议'].map(h => (
                <th key={h} style={{ textAlign:'left', paddingBottom:10, paddingRight:14,
                                     fontSize:10, fontWeight:600, letterSpacing:'0.04em',
                                     color:'var(--gr-text-tertiary)', whiteSpace:'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(s => {
              const p = prio(s)
              return (
                <tr key={s.name} style={{ borderBottom:'1px solid var(--gr-border-light)', transition:'background 0.15s' }}
                    onMouseEnter={e=>(e.currentTarget.style.background='rgba(59,130,246,0.03)')}
                    onMouseLeave={e=>(e.currentTarget.style.background='transparent')}>
                  <td style={{ padding:'10px 14px 10px 0' }}>
                    <div style={{ fontSize:12, fontWeight:700, color:'var(--gr-text)' }}>{s.name}</div>
                    <div style={{ fontSize:10, color:'var(--gr-text-tertiary)' }}>{s.pct.toFixed(1)}% 仓位</div>
                  </td>
                  <td style={{ padding:'10px 14px 10px 0', minWidth:90 }}><GradBar value={s.tech}/></td>
                  <td style={{ padding:'10px 14px 10px 0', minWidth:90 }}><GradBar value={s.fund}/></td>
                  <td style={{ padding:'10px 14px 10px 0', minWidth:90 }}><GradBar value={s.comp}/></td>
                  <td style={{ padding:'10px 14px 10px 0' }}><SigBadge sig={s.sig} txt={s.sigTxt}/></td>
                  <td style={{ padding:'10px 0', fontSize:11, fontWeight:700, color:p.c, whiteSpace:'nowrap' }}>{p.t}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </ACard>
  )
}

/* ─── Report Section ─────────────────────────────────────────────────────── */
function ReportSection({ analysis, portfolioLen }: { analysis:AnalysisResult; portfolioLen:number }) {
  const { scores, overall:s, total } = analysis
  const best2  = [...scores].sort((a,b)=>b.comp-a.comp).slice(0,2).map(x=>x.name)
  const worst2 = [...scores].sort((a,b)=>a.comp-b.comp).slice(0,2).map(x=>x.name)
  const topInd = analysis.topInd
  const topTh  = analysis.topThemes[0] as [string,{pct:number;stocks:string[]}]|undefined
  const sells  = scores.filter(x=>x.sig==='sell')
  const buys   = scores.filter(x=>x.sig==='buy')
  const lvl    = s>=75?'整体健康':s>=55?'中等风险水平':'较高风险水平'

  const sections = [
    { icon:'📊', color:'#3b82f6', title:'总体评估',
      body:`你的持仓综合健康分为 ${s} 分，整体处于${lvl}。当前持有 ${portfolioLen} 支标的，总仓位 ${total.toFixed(0)} 万元。从量化模型视角来看，集中度风险是当前持仓最突出的问题。` },
    { icon:'⚠️', color:'#f59e0b', title:'集中度分析',
      body:`行业集中度 HHI 指数为 ${Math.round(analysis.hhi)}（>2500 为高度集中）。${topInd[0]} 占比高达 ${topInd[1].toFixed(1)}%，是最主要集中风险来源。${topTh?`「${topTh[0]}」主题隐性集中：${topTh[1].stocks.join('、')} 合计 ${topTh[1].pct.toFixed(1)}%，表面分散实为高度押注。`:''}` },
    { icon:'🏥', color:'#10b981', title:'持仓健康度',
      body:`评分较好的标的是 ${best2.join('、')}，技术面与基本面相对健康。评分偏低、需重点关注的是 ${worst2.join('、')}，建议密切跟踪其趋势变化。` },
    { icon:'📡', color:'#8b5cf6', title:'信号交叉比对',
      body:`${sells.length?`量化模型对 ${sells.map(x=>x.name).join('、')} 给出减仓信号，建议优先评估这部分仓位。`:'当前无明确减仓信号。'} ${buys.length?`${buys.map(x=>x.name).join('、')} 处于量化买入区间，如有加仓计划可优先参考。`:''}` },
    { icon:'💡', color:'#06b6d4', title:'优化建议',
      body:`① 降低 ${topInd[0]} 方向集中度，换仓至相关性较低行业；② 优先处理平台减仓信号标的；③ 新增资金优先配置信号评级高且与现有持仓相关性低的方向，实现真正分散。` },
  ]

  return (
    <ACard accent="linear-gradient(90deg,#3b82f6,#8b5cf6,#ec4899)" style={{ marginBottom:16 }}>
      <SHeader title="🤖 AI 诊断报告" sub="由 AI 基于量化模型输出生成，仅供参考，不构成投资建议"/>
      <div style={{ display:'flex', flexDirection:'column' }}>
        {sections.map((sec,i) => (
          <div key={sec.title} style={{ display:'flex', gap:14, padding:'14px 0',
                                         borderBottom: i<sections.length-1?'1px solid var(--gr-border-light)':'none' }}>
            <div style={{ width:34, height:34, borderRadius:9, flexShrink:0,
                          display:'flex', alignItems:'center', justifyContent:'center', fontSize:16,
                          background:`${sec.color}15`, border:`1px solid ${sec.color}25` }}>
              {sec.icon}
            </div>
            <div style={{ flex:1 }}>
              <div style={{ fontSize:10, fontWeight:800, color:sec.color, marginBottom:5, letterSpacing:'0.06em' }}>
                {sec.title.toUpperCase()}
              </div>
              <p style={{ fontSize:12, lineHeight:1.75, color:'var(--gr-text-secondary)', margin:0 }}>{sec.body}</p>
            </div>
          </div>
        ))}
      </div>
      <div style={{ marginTop:14, padding:'10px 14px', borderRadius:8, fontSize:11, lineHeight:1.6,
                    background:'rgba(245,158,11,0.06)', border:'1px solid rgba(245,158,11,0.15)',
                    color:'var(--gr-text-tertiary)' }}>
        ⚠️ 以上内容由 AI 基于量化模型计算结果生成，仅供参考，不构成任何投资建议。市场存在风险，请审慎决策。
      </div>
    </ACard>
  )
}

/* ─── Chat Section ───────────────────────────────────────────────────────── */
function ChatSection({ messages, input, setInput, onSend, onSuggest, isTyping, chatBoxRef }: {
  messages:ChatMessage[]; input:string; setInput:(v:string)=>void
  onSend:()=>void; onSuggest:(q:string)=>void
  isTyping:boolean; chatBoxRef:React.RefObject<HTMLDivElement | null>
}) {
  return (
    <div style={{ borderRadius:16, overflow:'hidden', background:'var(--gr-card)',
                  border:'1px solid var(--gr-border-light)', boxShadow:'0 4px 24px rgba(0,0,0,0.07)' }}>
      {/* Header */}
      <div style={{ padding:'16px 20px', display:'flex', alignItems:'center', gap:12,
                    background:'linear-gradient(135deg,#0d1f4a 0%,#130d3a 100%)',
                    borderBottom:'1px solid rgba(255,255,255,0.06)' }}>
        <div style={{ width:34, height:34, borderRadius:10, flexShrink:0,
                      background:'linear-gradient(135deg,#3b82f6,#8b5cf6)',
                      display:'flex', alignItems:'center', justifyContent:'center',
                      fontSize:12, fontWeight:800, color:'white',
                      boxShadow:'0 0 16px rgba(59,130,246,0.4)' }}>AI</div>
        <div>
          <div style={{ fontSize:13, fontWeight:700, color:'white' }}>继续问 AI</div>
          <div style={{ fontSize:10, color:'rgba(255,255,255,0.35)' }}>针对你的持仓进一步追问</div>
        </div>
        <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:5 }}>
          <div style={{ width:7, height:7, borderRadius:'50%', background:'#10b981',
                        boxShadow:'0 0 8px rgba(16,185,129,0.7)', animation:'gr-pulse 2s infinite' }}/>
          <span style={{ fontSize:10, color:'rgba(255,255,255,0.4)' }}>在线</span>
        </div>
      </div>

      <div style={{ padding:'16px 20px' }}>
        {/* Chips */}
        <div style={{ display:'flex', flexWrap:'wrap', gap:6, marginBottom:16 }}>
          {['最大风险是什么？','新能源集中度问题','优先关注哪支？','如何优化组合？','哪些可以加仓？'].map(q => (
            <button key={q} onClick={()=>onSuggest(q)}
              style={{ fontSize:11, padding:'6px 13px', borderRadius:20, cursor:'pointer',
                       border:'1px solid var(--gr-border-light)',
                       background:'transparent', color:'var(--gr-text-secondary)', transition:'all 0.15s' }}
              onMouseEnter={e=>{const el=e.currentTarget;el.style.borderColor='rgba(59,130,246,0.5)';el.style.color='#3b82f6';el.style.background='rgba(59,130,246,0.06)'}}
              onMouseLeave={e=>{const el=e.currentTarget;el.style.borderColor='var(--gr-border-light)';el.style.color='var(--gr-text-secondary)';el.style.background='transparent'}}>
              {q}
            </button>
          ))}
        </div>

        {/* Messages */}
        {(messages.length > 0 || isTyping) && (
          <div ref={chatBoxRef} style={{ display:'flex', flexDirection:'column', gap:12, marginBottom:14,
                                          maxHeight:280, overflowY:'auto', padding:'2px 0' }}>
            {messages.map((m,i) => (
              <div key={i} style={{ display:'flex', gap:8, flexDirection:m.role==='user'?'row-reverse':'row',
                                     animation:'fadeIn 0.2s ease-out' }}>
                <div style={{ width:28, height:28, borderRadius:8, flexShrink:0,
                              display:'flex', alignItems:'center', justifyContent:'center',
                              fontSize:10, fontWeight:800,
                              background: m.role==='ai' ? 'linear-gradient(135deg,#2563eb,#7c3aed)' : 'var(--gr-border-light)',
                              color: m.role==='ai' ? 'white' : 'var(--gr-text-secondary)' }}>
                  {m.role==='ai'?'AI':'我'}
                </div>
                <div style={{ maxWidth:'78%', padding:'9px 13px', fontSize:12, lineHeight:1.65,
                              ...(m.role==='ai'
                                ? { background:'var(--gr-border-light)', color:'var(--gr-text)', borderRadius:'3px 10px 10px 10px' }
                                : { background:'linear-gradient(135deg,#2563eb,#7c3aed)', color:'white', borderRadius:'10px 3px 10px 10px' }) }}
                  dangerouslySetInnerHTML={{ __html:m.content }}/>
              </div>
            ))}
            {isTyping && (
              <div style={{ display:'flex', gap:8 }}>
                <div style={{ width:28, height:28, borderRadius:8, flexShrink:0,
                              display:'flex', alignItems:'center', justifyContent:'center',
                              fontSize:10, fontWeight:800, color:'white',
                              background:'linear-gradient(135deg,#2563eb,#7c3aed)' }}>AI</div>
                <div style={{ padding:'9px 14px', background:'var(--gr-border-light)',
                              borderRadius:'3px 10px 10px 10px', display:'flex', alignItems:'center', gap:5 }}>
                  {[0,1,2].map(i => (
                    <div key={i} style={{ width:5, height:5, borderRadius:'50%', background:'var(--gr-text-tertiary)',
                                          animation:`gr-bounce 1.2s infinite ${i*0.2}s` }}/>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Input */}
        <div style={{ display:'flex', gap:8 }}>
          <input value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==='Enter'&&onSend()}
            placeholder="输入问题，例如：我应该减仓哪个方向？"
            style={{ flex:1, padding:'10px 14px', borderRadius:10, fontSize:12, outline:'none',
                     background:'var(--gr-border-light)', border:'1px solid transparent',
                     color:'var(--gr-text)', transition:'border-color 0.15s' }}
            onFocus={e=>e.target.style.borderColor='rgba(59,130,246,0.5)'}
            onBlur={e=>e.target.style.borderColor='transparent'}/>
          <button onClick={onSend}
            style={{ padding:'10px 20px', borderRadius:10, fontSize:12, fontWeight:700, color:'white',
                     cursor:'pointer', border:'none', transition:'all 0.15s',
                     background:'linear-gradient(135deg,#2563eb,#7c3aed)',
                     boxShadow:'0 2px 12px rgba(37,99,235,0.35)' }}
            onMouseEnter={e=>{const el=e.currentTarget;el.style.transform='translateY(-1px)';el.style.boxShadow='0 4px 16px rgba(37,99,235,0.45)'}}
            onMouseLeave={e=>{const el=e.currentTarget;el.style.transform='translateY(0)';el.style.boxShadow='0 2px 12px rgba(37,99,235,0.35)'}}>
            发送
          </button>
        </div>
      </div>
    </div>
  )
}