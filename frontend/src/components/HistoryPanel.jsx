import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Plus, PanelLeftClose, PanelLeftOpen, History } from 'lucide-react'
import { fetchSessions } from '@/lib/api'
import { cn } from '@/lib/utils'

const USER_ID = 'admin'

/**
 * Persistent chat-session history rail.
 *
 * Lifted out of ChatPage on 2026-04-27 (frontend polish sprint, F02
 * follow-on) so it can live in AppLayout next to the nav rail and stay
 * visible across all chat surfaces.
 *
 * Collapsible — when `collapsed`, renders a thin 32px strip with an
 * expand button. AppLayout owns the state + persists to localStorage.
 *
 * Props:
 *   activeSessionId  (string | null) — id of the session currently loaded
 *   onSelectSession  (id) => void    — fires when a row is clicked
 *   onNewChat        () => void      — fires on the "New Chat" button
 *   collapsed        (bool)          — when true, render thin strip
 *   onToggleCollapse () => void      — fires when user clicks the chevron
 */
export default function HistoryPanel({
  activeSessionId, onSelectSession, onNewChat,
  collapsed = false, onToggleCollapse,
}) {
  const { t } = useTranslation()

  const { data: sessions = [] } = useQuery({
    queryKey: ['sessions', USER_ID],
    queryFn: () => fetchSessions(USER_ID),
    staleTime: 30_000,
    enabled: !collapsed,  // skip fetch if hidden — re-fires on expand
  })

  // Collapsed state: thin 32px strip with an expand button + history icon.
  if (collapsed) {
    return (
      <aside
        className="w-8 border-r flex flex-col items-center shrink-0 py-2 gap-2"
        style={{
          borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
          backgroundColor: 'var(--bg-1)',
        }}
      >
        <button
          type="button"
          onClick={onToggleCollapse}
          className="p-1.5 rounded transition-colors hover:bg-white/5"
          title={t('chat.expandHistory')}
          aria-label={t('chat.expandHistory')}
          style={{ color: 'var(--fg-dim)' }}
        >
          <PanelLeftOpen size={14} />
        </button>
        <History size={14} style={{ color: 'var(--fg-faint)' }} />
      </aside>
    )
  }

  return (
    <aside
      className="w-56 border-r flex flex-col shrink-0"
      style={{
        borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
        backgroundColor: 'var(--bg-1)',
      }}
    >
      <div
        className="p-2 border-b shrink-0 flex items-center gap-2"
        style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}
      >
        <button
          type="button"
          onClick={onNewChat}
          className="flex items-center gap-2 flex-1 px-3 py-2 rounded-lg text-xs transition-colors"
          style={{
            backgroundColor: 'var(--signature)',
            color: '#fff',
            border: '1px solid var(--signature)',
          }}
        >
          <Plus size={14} /> {t('chat.newChat')}
        </button>
        <button
          type="button"
          onClick={onToggleCollapse}
          className="p-1.5 rounded transition-colors hover:bg-white/5 shrink-0"
          title={t('chat.collapseHistory')}
          aria-label={t('chat.collapseHistory')}
          style={{ color: 'var(--fg-dim)' }}
        >
          <PanelLeftClose size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-auto py-1">
        {sessions.length === 0 ? (
          <p className="px-3 py-4 text-xs opacity-30 text-center">
            {t('chat.noSessionsYet')}
          </p>
        ) : (
          sessions.map(s => (
            <button
              key={s.session_id}
              type="button"
              onClick={() => onSelectSession?.(s.session_id)}
              className={cn(
                'w-full px-3 py-2 text-left text-xs truncate transition-colors',
                activeSessionId === s.session_id ? 'bg-white/10' : 'hover:bg-white/5',
              )}
              style={{ color: 'var(--fg)' }}
            >
              <div className="truncate">{s.preview || t('common.empty')}</div>
              <div className="opacity-30 mt-0.5">
                {new Date(s.last_access).toLocaleDateString()}
              </div>
            </button>
          ))
        )}
      </div>
    </aside>
  )
}
