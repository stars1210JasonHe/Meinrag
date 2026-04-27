import { useEffect, useState, useCallback } from 'react'
import { Outlet, NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import {
  LayoutDashboard, MessageSquare, Network, ChevronLeft, ChevronRight,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import LanguageSwitcher from '@/components/LanguageSwitcher'
import ThemeToggle from '@/components/ThemeToggle'
import HistoryPanel from '@/components/HistoryPanel'

function Breadcrumb() {
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const path = location.pathname

  if (path === '/') return null

  const crumbs = [{ label: t('nav.dashboard'), to: '/' }]

  if (path.startsWith('/chat')) {
    const docName = searchParams.get('name')
    const collection = searchParams.get('collection')
    const suffix = docName ? `: ${docName}` : collection ? `: ${collection}` : ''
    crumbs.push({ label: `${t('nav.chat')}${suffix}` })
  } else if (path.startsWith('/graph')) {
    crumbs.push({ label: t('nav.graph') })
    const docId = path.replace('/graph/', '').replace('/graph', '')
    if (docId) crumbs.push({ label: docId })
  } else if (path.startsWith('/pdf')) {
    crumbs.push({ label: t('nav.pdfViewer') })
  }

  return (
    <div
      className="flex items-center gap-1.5 px-4 py-1.5 text-xs border-b shrink-0"
      style={{
        borderColor: 'var(--border)',
        color: 'var(--fg-faint)',
        fontFamily: 'var(--mono)',
        letterSpacing: '0.05em',
      }}
    >
      {crumbs.map((c, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <span className="opacity-40">/</span>}
          {c.to ? (
            <NavLink to={c.to} className="hover:underline opacity-60 hover:opacity-100">{c.label}</NavLink>
          ) : (
            <span style={{ color: 'var(--fg-1)' }}>{c.label}</span>
          )}
        </span>
      ))}
    </div>
  )
}

const NAV_ITEMS = [
  { to: '/', icon: LayoutDashboard, labelKey: 'nav.dashboard' },
  { to: '/chat', icon: MessageSquare, labelKey: 'nav.chat' },
  { to: '/graph', icon: Network, labelKey: 'nav.graph' },
]

const SIDEBAR_COLLAPSED_KEY = 'meinrag.sidebar.collapsed'

export default function AppLayout() {
  const { t } = useTranslation()
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const [collapsed, setCollapsed] = useState(() => {
    if (typeof localStorage === 'undefined') return false
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1'
  })
  useEffect(() => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  // History panel only on /chat routes
  const showHistoryPanel = location.pathname.startsWith('/chat')
  const activeSessionId = searchParams.get('session') || null

  const onSelectSession = useCallback((sid) => {
    // Use URL state so ChatPage can react via useSearchParams.
    setSearchParams(prev => {
      const p = new URLSearchParams(prev)
      p.set('session', sid)
      return p
    })
  }, [setSearchParams])

  const onNewChat = useCallback(() => {
    // Strip session param + navigate to /chat for a fresh start.
    setSearchParams(prev => {
      const p = new URLSearchParams(prev)
      p.delete('session')
      return p
    })
    if (!location.pathname.startsWith('/chat')) navigate('/chat')
  }, [setSearchParams, navigate, location.pathname])

  return (
    <div className="flex h-screen" style={{ backgroundColor: 'var(--bg)' }}>
      {/* Sidebar — labels visible by default, collapse user-toggled */}
      <nav
        className={cn(
          'flex flex-col border-r overflow-hidden transition-[width] duration-200',
          collapsed ? 'w-14' : 'w-52',
        )}
        style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-1)' }}
      >
        {/* Brand */}
        <div
          className="flex items-center gap-2.5 px-4 py-4 border-b shrink-0"
          style={{ borderColor: 'var(--border)' }}
        >
          <div
            className="shrink-0 rounded-md flex items-center justify-center overflow-hidden"
            style={{ width: 22, height: 22, background: 'var(--fg)' }}
          >
            <div
              style={{
                width: 12, height: 12,
                background: 'var(--signature)',
                transform: 'rotate(45deg)',
                boxShadow: '0 0 12px var(--signature-glow)',
              }}
            />
          </div>
          {!collapsed && (
            <span
              className="text-[17px] font-medium whitespace-nowrap"
              style={{
                color: 'var(--fg)',
                fontFamily: 'var(--display)',
                fontStyle: 'italic',
                letterSpacing: '-0.02em',
              }}
            >
              MeinRAG
            </span>
          )}
        </div>

        <div className="flex-1 py-2">
          {NAV_ITEMS.map(({ to, icon: Icon, labelKey }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-4 py-2.5 text-sm transition-colors relative',
                  isActive ? 'font-medium' : 'opacity-60 hover:opacity-100',
                )
              }
              style={({ isActive }) => ({
                color: isActive ? 'var(--fg)' : 'var(--fg-dim)',
                backgroundColor: isActive ? 'var(--bg-3)' : 'transparent',
              })}
              title={collapsed ? t(labelKey) : undefined}
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      aria-hidden
                      className="absolute left-0 top-1/2 -translate-y-1/2"
                      style={{
                        width: 3, height: 16,
                        background: 'var(--signature)',
                        borderRadius: '0 3px 3px 0',
                        boxShadow: '0 0 12px var(--signature-glow)',
                      }}
                    />
                  )}
                  <Icon
                    size={18}
                    className="shrink-0"
                    style={{ color: isActive ? 'var(--signature)' : 'currentColor' }}
                  />
                  {!collapsed && (
                    <span className="whitespace-nowrap">{t(labelKey)}</span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </div>

        <div
          className="border-t flex items-center justify-between px-2 py-1.5"
          style={{ borderColor: 'var(--border)' }}
        >
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <LanguageSwitcher />
          </div>
          <button
            type="button"
            onClick={() => setCollapsed(c => !c)}
            className="p-1.5 rounded transition-colors hover:bg-white/5"
            title={collapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
            aria-label={collapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
            style={{ color: 'var(--fg-faint)' }}
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>
      </nav>

      {/* History panel — only on /chat */}
      {showHistoryPanel && (
        <HistoryPanel
          activeSessionId={activeSessionId}
          onSelectSession={onSelectSession}
          onNewChat={onNewChat}
        />
      )}

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <Breadcrumb />
        <div className="flex-1 overflow-auto">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
