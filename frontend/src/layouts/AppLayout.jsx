import { Outlet, NavLink } from 'react-router-dom'
import { LayoutDashboard, MessageSquare, Network, Settings, HelpCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/chat', icon: MessageSquare, label: 'Chat' },
  { to: '/graph', icon: Network, label: 'Graph' },
]

export default function AppLayout() {
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
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
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
                {label}
              </span>
            </NavLink>
          ))}
        </div>

        <div className="py-2 border-t" style={{ borderColor: 'hsl(217 33% 17%)' }}>
          <button className="flex items-center gap-3 px-4 py-2.5 text-sm w-full opacity-60 hover:opacity-100 transition-opacity"
                  style={{ color: 'hsl(215 20% 65%)' }}>
            <Settings size={18} className="shrink-0" />
            <span className="whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">Settings</span>
          </button>
          <button className="flex items-center gap-3 px-4 py-2.5 text-sm w-full opacity-60 hover:opacity-100 transition-opacity"
                  style={{ color: 'hsl(215 20% 65%)' }}>
            <HelpCircle size={18} className="shrink-0" />
            <span className="whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">Help</span>
          </button>
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
