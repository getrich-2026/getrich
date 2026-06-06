import { useLocation, useNavigate } from 'react-router-dom'
import { Bell, TrendingUp, BookOpen, Database } from 'lucide-react'

const items = [
  { icon: Bell, label: '信号', path: '/market' },
  { icon: TrendingUp, label: '策略', path: '/strategies' },
  { icon: BookOpen, label: '知识库', path: '/knowledge' },
  { icon: Database, label: '导入', path: '/admin/imports' },
]

export default function SideNav() {
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <nav
      className="fixed top-0 left-0 h-screen z-50 flex flex-col items-center py-4"
      style={{
        width: 56,
        background: '#fff',
        borderRight: '1px solid var(--gr-border)',
      }}
    >
      {/* Logo */}
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center mb-8 cursor-pointer"
        style={{ background: 'var(--gr-text)' }}
        onClick={() => navigate('/market')}
      >
        <TrendingUp size={18} style={{ color: '#fff' }} />
      </div>

      {/* Nav items */}
      <div className="flex flex-col gap-1 flex-1">
        {items.map((item) => {
          const active = location.pathname.startsWith(item.path)
          const Icon = item.icon
          return (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className="relative w-10 h-10 rounded-lg flex items-center justify-center transition-all duration-150"
              style={{
                color: active ? 'var(--gr-text)' : 'var(--gr-text-tertiary)',
                background: active ? 'var(--gr-bg)' : 'transparent',
              }}
              title={item.label}
            >
              {active && (
                <div
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r"
                  style={{ background: 'var(--gr-red)' }}
                />
              )}
              <Icon size={20} />
            </button>
          )
        })}
      </div>

      {/* User avatar placeholder */}
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center"
        style={{ background: 'var(--gr-bg)' }}
      >
        <span className="text-xs font-medium" style={{ color: 'var(--gr-text-secondary)' }}>U</span>
      </div>
    </nav>
  )
}
