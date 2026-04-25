import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

/* ---------- Mock Data ---------- */

interface NewsItem {
  id: string
  title: string
  summary: string
  category: string
  publishedAt: string
  source: string
  stocks: { symbol: string; changePct: number }[]
  isBreaking: boolean
}

interface SignalEvent {
  id: string
  date: string
  description: string
  signalId: string
}

const categoryColors: Record<string, string> = {
  '市场': '#E8473F',
  '宏观': '#3B82F6',
  '公司': '#22C55E',
  '政策': '#F59E0B',
}

const mockNews: NewsItem[] = [
  {
    id: 'NEWS_001',
    title: 'Guangdong foreign trade to exceed 9 trillion yuan in 2024 with NEV exports surging on Belt and Road growth',
    summary: 'This is a short summary of the news, summarizing the content of the news. This is a short summary of the news, summarizing the content of the news.',
    category: '市场',
    publishedAt: '04.12 18:32',
    source: 'Reuters',
    stocks: [{ symbol: 'MSTR', changePct: 2.3 }, { symbol: 'TSLA', changePct: 1.8 }],
    isBreaking: true,
  },
  {
    id: 'NEWS_002',
    title: 'PBOC injects 100bn yuan via reverse repo, keeps rates steady amid trade data optimism',
    summary: 'This is a short summary of the news, summarizing the content of the news. This is a short summary of the news, summarizing the content of the news.',
    category: '宏观',
    publishedAt: '04.12 16:15',
    source: 'Bloomberg',
    stocks: [{ symbol: 'MSTR', changePct: -2.3 }],
    isBreaking: false,
  },
  {
    id: 'NEWS_003',
    title: 'Tesla announces new battery partnership with CATL, shares up 3.2% in pre-market trading',
    summary: 'This is a short summary of the news, summarizing the content of the news. This is a short summary of the news, summarizing the content of the news.',
    category: '公司',
    publishedAt: '04.12 14:08',
    source: 'CNBC',
    stocks: [{ symbol: 'MSTR', changePct: -2.3 }, { symbol: 'TSLA', changePct: 3.2 }, { symbol: 'CATL', changePct: 1.5 }, { symbol: 'BYD', changePct: -0.8 }],
    isBreaking: false,
  },
  {
    id: 'NEWS_004',
    title: 'China Securities Regulatory Commission releases new guidelines for quantitative trading strategies',
    summary: 'This is a short summary of the news, summarizing the content of the news. This is a short summary of the news, summarizing the content of the news.',
    category: '政策',
    publishedAt: '04.12 10:30',
    source: 'Financial Times',
    stocks: [{ symbol: 'MSTR', changePct: 2.3 }, { symbol: 'IC', changePct: 1.1 }, { symbol: 'IF', changePct: 0.9 }],
    isBreaking: false,
  },
]

const mockSignalEvents: SignalEvent[] = [
  { id: 'EVT_001', date: 'April 5, 2025 - Tesla Energy Summit', description: 'Insights into next-gen battery tech for traders.', signalId: 'SIG_20260415_001' },
  { id: 'EVT_002', date: 'June 15, 2025 - Tesla AI Day 3.0', description: 'Tesla AI Day 3.0: Trading strategies around AI-driven innovations and market volatility.', signalId: 'SIG_20260414_003' },
]

/* ---------- Page Component ---------- */

export default function MarketPage() {
  const [loading, setLoading] = useState(true)
  useEffect(() => { setTimeout(() => setLoading(false), 500) }, [])

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-6">
      <h1 className="text-2xl font-bold mb-6" style={{ color: 'var(--gr-text)' }}>
        市场速递（in 24hrs）
      </h1>

      {/* News list */}
      <div className="space-y-1 mb-8">
        {loading
          ? Array.from({ length: 4 }).map((_, i) => <NewsSkeleton key={i} />)
          : mockNews.map((news, i) => <NewsCard key={news.id} news={news} delay={i * 80} />)}
      </div>

      {/* Signal events */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold mb-4" style={{ color: 'var(--gr-text)' }}>交易信号通知</h2>
        <div className="space-y-3">
          {mockSignalEvents.map((evt, i) => (
            <SignalEventCard key={evt.id} event={evt} delay={i * 80} />
          ))}
        </div>
      </div>
    </div>
  )
}

/* ---------- News Card - Bloomberg/TradingView Style ---------- */

function NewsCard({ news, delay }: { news: NewsItem; delay: number }) {
  return (
    <div
      className="group flex gap-0 cursor-pointer transition-all duration-200"
      style={{
        opacity: 0,
        animation: `fadeIn 0.2s ease-out ${delay}ms forwards`,
      }}
    >
      {/* Left accent bar - red for breaking, gray for normal */}
      <div
        className="flex-shrink-0 w-[3px] rounded-full self-stretch mr-4 transition-colors duration-200"
        style={{
          background: news.isBreaking
            ? 'linear-gradient(to bottom, #E8473F, #F87171)'
            : '#E5E7EB',
        }}
      />

      {/* Content */}
      <div className="flex-1 min-w-0 py-4" style={{ borderBottom: '1px solid var(--gr-border-light)' }}>
        {/* Top row: category + breaking badge */}
        <div className="flex items-center gap-2 mb-2">
          <span
            className="text-[11px] font-semibold uppercase tracking-wider"
            style={{ color: categoryColors[news.category] || '#6B7280' }}
          >
            {news.category}
          </span>
          {news.isBreaking && (
            <span
              className="text-[10px] font-bold px-1.5 py-0.5 rounded"
              style={{ background: '#FEF2F2', color: '#E8473F' }}
            >
              BREAKING
            </span>
          )}
        </div>

        {/* Title - black, not blue */}
        <h3
          className="text-sm font-semibold leading-snug mb-1.5 group-hover:text-[var(--gr-blue)] transition-colors duration-150"
          style={{ color: 'var(--gr-text)' }}
        >
          {news.title}
        </h3>

        {/* Summary */}
        <p className="text-xs leading-relaxed mb-2.5 line-clamp-2" style={{ color: 'var(--gr-text-secondary)' }}>
          {news.summary}
        </p>

        {/* Bottom row: stocks + time + source */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 flex-wrap">
            {news.stocks.map((s, idx) => (
              <span key={idx} className="flex items-center gap-1">
                <span className="text-xs font-medium" style={{ color: 'var(--gr-text-secondary)' }}>
                  {s.symbol}
                </span>
                <span
                  className="text-xs font-semibold tabular"
                  style={{ color: s.changePct >= 0 ? '#E8473F' : '#22C55E' }}
                >
                  {s.changePct >= 0 ? '+' : ''}{s.changePct}%
                </span>
              </span>
            ))}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0 ml-4">
            <span className="text-[11px]" style={{ color: 'var(--gr-text-tertiary)' }}>
              {news.source}
            </span>
            <span className="text-[11px]" style={{ color: 'var(--gr-border)' }}>|</span>
            <span className="text-[11px] tabular" style={{ color: 'var(--gr-text-tertiary)' }}>
              {news.publishedAt}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ---------- Skeleton ---------- */

function NewsSkeleton() {
  return (
    <div className="flex gap-0">
      <div className="flex-shrink-0 w-[3px] rounded-full self-stretch mr-4 skeleton" />
      <div className="flex-1 min-w-0 py-4 space-y-2" style={{ borderBottom: '1px solid var(--gr-border-light)' }}>
        <div className="flex gap-2">
          <div className="h-3 skeleton w-10" />
          <div className="h-3 skeleton w-14" />
        </div>
        <div className="h-4 skeleton w-full" />
        <div className="h-3 skeleton w-[90%]" />
        <div className="flex justify-between">
          <div className="h-3 skeleton w-32" />
          <div className="h-3 skeleton w-24" />
        </div>
      </div>
    </div>
  )
}

/* ---------- Signal Event Card ---------- */

function SignalEventCard({ event, delay }: { event: SignalEvent; delay: number }) {
  const navigate = useNavigate()
  return (
    <div
      className="rounded-xl p-4 cursor-pointer card-shadow card-shadow-hover"
      style={{
        background: 'var(--gr-card)',
        opacity: 0,
        animation: `fadeIn 0.2s ease-out ${delay}ms forwards`,
      }}
      onClick={() => navigate(`/signals/${event.signalId}`)}
    >
      <h3 className="text-sm font-medium mb-1.5" style={{ color: 'var(--gr-red)' }}>
        {event.date}
      </h3>
      <p className="text-xs leading-relaxed" style={{ color: 'var(--gr-text-secondary)' }}>
        {event.description}
      </p>
    </div>
  )
}
