import { Outlet, NavLink, useLocation, useSearchParams } from 'react-router-dom'
import { LayoutDashboard, MessageSquare, Network } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import LanguageSwitcher from '@/components/LanguageSwitcher'

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
    <div className="flex items-center gap-1.5 px-4 py-1.5 text-xs border-b shrink-0"
         style={{ borderColor: 'hsl(217 33% 12%)', color: 'hsl(215 20% 65%)' }}>
      {crumbs.map((c, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <span className="opacity-30">›</span>}
          {c.to ? (
            <NavLink to={c.to} className="hover:underline opacity-60 hover:opacity-100">{c.label}</NavLink>
          ) : (
            <span style={{ color: 'hsl(210 40% 98%)' }}>{c.label}</span>
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
    <div className="flex h-screen" style={{ backgroundColor: 'hsl(222 47% 6%)' }}>
      {/* Sidebar — collapsed, expands on hover */}
      <nav className="group flex w-14 hover:w-48 flex-col border-r transition-all duration-200 overflow-hidden"
           style={{ borderColor: 'hsl(217 33% 17%)', backgroundColor: 'hsl(222 47% 8%)' }}>
        <div className="flex items-center gap-2 px-4 py-4 border-b" style={{ borderColor: 'hsl(217 33% 17%)' }}>
          <Network size={20} style={{ color: 'hsl(250 80% 65%)' }} className="shrink-0" />
          <span className="text-sm font-semibold whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ color: 'hsl(210 40% 98%)' }}>
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
                  'flex items-center gap-3 px-4 py-2.5 text-sm transition-colors',
                  isActive ? 'font-medium' : 'opacity-60 hover:opacity-100'
                )
              }
              style={({ isActive }) => ({
                color: isActive ? 'hsl(250 80% 65%)' : 'hsl(215 20% 65%)',
                backgroundColor: isActive ? 'hsl(217 33% 17%)' : 'transparent',
              })}
            >
              <Icon size={18} className="shrink-0" />
              <span className="whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
                {t(labelKey)}
              </span>
            </NavLink>
          ))}
        </div>

        <div className="py-2 border-t" style={{ borderColor: 'hsl(217 33% 17%)' }}>
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
