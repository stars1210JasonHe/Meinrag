import { useMemo } from 'react'
import { MessageSquarePlus, Trash2 } from 'lucide-react'

function groupByDate(sessions) {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
  const weekAgo = new Date(today); weekAgo.setDate(today.getDate() - 7)

  const groups = { Today: [], Yesterday: [], 'Last 7 Days': [], Older: [] }
  for (const s of sessions) {
    const d = new Date(s.last_access)
    if (d >= today) groups.Today.push(s)
    else if (d >= yesterday) groups.Yesterday.push(s)
    else if (d >= weekAgo) groups['Last 7 Days'].push(s)
    else groups.Older.push(s)
  }
  return groups
}

export default function ChatHistoryPanel({
  sessions, currentSessionId, onNewChat, onSelectSession, onDeleteSession,
}) {
  const grouped = useMemo(() => groupByDate(sessions), [sessions])

  return (
    <div className="chat-history-panel">
      <div className="panel-header">
        <span className="panel-title">Chat History</span>
        <button className="new-chat-sidebar-btn" onClick={onNewChat} title="New Chat">
          <MessageSquarePlus size={16} />
        </button>
      </div>
      <div className="chat-history-list">
        {sessions.length === 0 && (
          <div className="empty-hint">No conversations yet</div>
        )}
        {Object.entries(grouped).map(([label, items]) =>
          items.length > 0 && (
            <div key={label} className="date-group">
              <div className="date-group-label">{label}</div>
              {items.map(s => (
                <div
                  key={s.session_id}
                  className={`history-item ${s.session_id === currentSessionId ? 'active' : ''}`}
                  onClick={() => onSelectSession(s.session_id)}
                >
                  <span className="history-preview">{s.preview}</span>
                  <button
                    className="history-delete"
                    onClick={e => { e.stopPropagation(); onDeleteSession(s.session_id) }}
                    title="Delete"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          )
        )}
      </div>
    </div>
  )
}
