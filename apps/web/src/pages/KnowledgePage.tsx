import { useState, useEffect } from 'react'
import Tag from '@/components/Tag'

// Mock data aligned with API structure
interface Article {
  id: string
  title: string
  tags: string[]
  summary: string
  publishedAt: string
}

const mockArticles: Article[] = [
  {
    id: 'ART_001',
    title: '这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题',
    tags: ['这是一个文章标签', '这是一个文章标签'],
    summary: 'As Guangdong\'s foreign trade is set to exceed 9 trillion yuan in 2024, driven by a 10% year-on-year growth and contributing 40.9% to China\'s national trade, AI-driven financial analysis is highlighting the growing intersection of the Belt and Road Initiative (BRI) and the new energy vehicle (NEV) sector.\n\nGuangdong\'s robust export growth, particularly in the NEV industry, is increasingly fueled by the BRI\'s global infrastructure projects and cross-border trade expansions. With the demand for sustainable transportation rising across BRI countries, Guangdong\'s NEV exports are positioned to surge, offering significant investment opportunities in the green technology and automotive sectors.\n\nThis dynamic convergence of Guangdong\'s trade strength, the BRI\'s global expansion, and the rise of NEVs signals a new wave of economic growth and innovation. As these factors align, financial experts anticipate strong market performance, making this an exciting time for both domestic and international investors.',
    publishedAt: '04.12 18:32',
  },
  {
    id: 'ART_002',
    title: '这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题这是一个文章标题',
    tags: ['这是一个文章标签', '这是一个文章标签'],
    summary: 'As Guangdong\'s foreign trade is set to exceed 9 trillion yuan in 2024, driven by a 10% year-on-year growth and contributing 40.9% to China\'s national trade, AI-driven financial analysis is highlighting the growing intersection of the Belt and Road Initiative (BRI) and the new energy vehicle (NEV) sector.\n\nGuangdong\'s robust export growth, particularly in the NEV industry, is increasingly fueled by the BRI\'s global infrastructure projects and cross-border trade expansions. With the demand for sustainable transportation rising across BRI countries, Guangdong\'s NEV exports are positioned to surge, offering significant investment opportunities in the green technology and automotive sectors.\n\nThis dynamic convergence of Guangdong\'s trade strength, the BRI\'s global expansion, and the rise of NEVs signals a new wave of economic growth and innovation. As these factors align, financial experts anticipate strong market performance, making this an exciting time for both domestic and international investors.',
    publishedAt: '04.12 18:32',
  },
]

export default function KnowledgePage() {
  const [loading, setLoading] = useState(true)
  const [articles, setArticles] = useState<Article[]>([])

  useEffect(() => {
    // TODO: Replace with API call
    // fetch('/api/knowledge/articles').then(r => r.json()).then(setArticles)
    setTimeout(() => {
      setArticles(mockArticles)
      setLoading(false)
    }, 500)
  }, [])

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-6">
      {/* Section header */}
      <div className="flex items-center gap-2 mb-5">
        <BookOpenIcon />
        <h1 className="text-2xl font-bold" style={{ color: 'var(--gr-text)' }}>
          知识库
        </h1>
      </div>

      {/* Article list */}
      <div className="space-y-4">
        {loading
          ? Array.from({ length: 2 }).map((_, i) => (
              <ArticleSkeleton key={i} />
            ))
          : articles.map((article, index) => (
              <ArticleCard key={article.id} article={article} delay={index * 100} />
            ))}
      </div>
    </div>
  )
}

/* ---------- Sub Components ---------- */

function BookOpenIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--gr-text)' }}>
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
    </svg>
  )
}

function ArticleCard({ article, delay }: { article: Article; delay: number }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div
      className="rounded-xl p-5 cursor-pointer card-shadow card-shadow-hover"
      style={{
        background: 'var(--gr-card)',
        opacity: 0,
        animation: `fadeIn 0.2s ease-out ${delay}ms forwards`,
      }}
      onClick={() => setExpanded(!expanded)}
    >
      {/* Title + time row */}
      <div className="flex items-start justify-between gap-4 mb-2">
        <h2
          className="text-sm font-semibold leading-relaxed line-clamp-2"
          style={{ color: 'var(--gr-text)' }}
        >
          {article.title}
        </h2>
        <span className="text-xs shrink-0 mt-0.5" style={{ color: 'var(--gr-text-tertiary)' }}>
          {article.publishedAt}
        </span>
      </div>

      {/* Tags */}
      <div className="flex gap-2 mb-3">
        {article.tags.map((tag) => (
          <Tag key={tag} variant="red">{tag}</Tag>
        ))}
      </div>

      {/* Summary */}
      <p
        className="text-sm leading-relaxed whitespace-pre-line"
        style={{
          color: 'var(--gr-text-secondary)',
          display: '-webkit-box',
          WebkitLineClamp: expanded ? undefined : 3,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}
      >
        {article.summary}
      </p>
    </div>
  )
}

function ArticleSkeleton() {
  return (
    <div
      className="rounded-xl p-5 card-shadow"
      style={{
        background: 'var(--gr-card)',
      }}
    >
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="h-4 skeleton w-full" />
        <div className="h-3 skeleton w-20 shrink-0" />
      </div>
      <div className="flex gap-2 mb-3">
        <div className="h-5 skeleton w-24" />
        <div className="h-5 skeleton w-24" />
      </div>
      <div className="space-y-2">
        <div className="h-3 skeleton w-full" />
        <div className="h-3 skeleton w-full" />
        <div className="h-3 skeleton w-[80%]" />
      </div>
    </div>
  )
}
