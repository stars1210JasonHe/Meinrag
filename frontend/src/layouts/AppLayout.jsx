import { Outlet, NavLink, useLocation, useSearchParams } from 'react-router-dom'
import { LayoutDashboard, MessageSquare, Network } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import LanguageSwitcher from '@/components/LanguageSwitcher'
import ThemeToggle from '@/components/ThemeToggle'

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

export default function AppLayout() {
  const { t } = useTranslation()
  return (
    <div className="flex h-screen" style={{ backgroundColor: 'var(--bg)' }}>
      {/* Sidebar — collapsed, expands on hover */}
      <nav
        className="group flex w-14 hover:w-48 flex-col border-r transition-all duration-200 overflow-hidden"
        style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-1)' }}
      >
        {/* Brand: rhombus-in-square mark */}
        <div
          className="flex items-center gap-2.5 px-4 py-4 border-b shrink-0"
          style={{ borderColor: 'var(--border)' }}
        >
          <div
            className="shrink-0 rounded-md flex items-center justify-center overflow-hidden"
            style={{
              width: 22, height: 22,
              background: 'var(--fg)',
            }}
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
          <span
            className="text-[17px] font-medium whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity"
            style={{
              color: 'var(--fg)',
              fontFamily: 'var(--display)',
              fontStyle: 'italic',
              letterSpacing: '-0.02em',
            }}
          >
            MeinRAG
          </span>
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
                  isActive ? 'font-medium' : 'opacity-60 hover:opacity-100'
                )
              }
              style={({ isActive }) => ({
                color: isActive ? 'var(--fg)' : 'var(--fg-dim)',
                backgroundColor: isActive ? 'var(--bg-3)' : 'transparent',
              })}
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
                  <span className="whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
                    {t(labelKey)}
                  </span>
                </>
              )}
            </NavLink>
          ))}
        </div>

        <div className="border-t" style={{ borderColor: 'var(--border)' }}>
          <ThemeToggle />
          <LanguageSwitcher />
        </div>
      </nav>

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
