import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Upload, ArrowRight, LayoutDashboard } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { fetchCorpusStats } from '@/lib/api'

const USER_ID = 'admin'

/**
 * Empty-state hero for the chat page.
 * Shows corpus orientation (stats), three question seeds, and entry
 * points (upload + browse). Replaces the bare-icon-and-placeholder
 * empty state pre-2026-04-27 frontend polish sprint (F01).
 *
 * Props:
 *   onSuggestionClick: (text) => void — fired when user clicks a seed.
 *   onUploadClick:     () => void  — optional. If absent, navigates to /
 *                                    where the dashboard's upload sits.
 */
export default function ChatEmptyState({ onSuggestionClick, onUploadClick }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({
    queryKey: ['corpus-stats'],
    queryFn: () => fetchCorpusStats(USER_ID),
    staleTime: 30_000,
  })

  const stats = data || { chunks: 0, collections: 0, edges: 0, documents: 0 }

  // Pull the three suggestion strings from i18n (translatable per locale).
  const suggestions = [
    t('chat.suggestion1'),
    t('chat.suggestion2'),
    t('chat.suggestion3'),
  ]

  return (
    <div
      className="flex flex-col items-start justify-center h-full px-8 max-w-[640px] mx-auto"
      style={{ color: 'var(--fg)' }}
    >
      {/* Corpus stats */}
      <div className="w-full mb-7">
        <div
          className="text-[11px] mb-2 tracking-widest"
          style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono, ui-monospace, monospace)' }}
        >
          {t('chat.corpusStats')}
        </div>
        <div className="flex gap-9 items-baseline flex-wrap">
          <Stat value={isLoading ? '—' : formatNumber(stats.chunks)} label={t('chat.corpusChunks')} />
          <Stat value={isLoading ? '—' : String(stats.collections)} label={t('chat.corpusCollections')} />
          <Stat value={isLoading ? '—' : formatNumber(stats.edges)} label={t('chat.corpusEdges')} />
        </div>
      </div>

      {/* Try asking */}
      <div className="w-full mb-6">
        <div
          className="text-[11px] mb-3 tracking-widest"
          style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono, ui-monospace, monospace)' }}
        >
          {t('chat.tryAsking')}
        </div>
        <div className="flex flex-col gap-2">
          {suggestions.map((s, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onSuggestionClick?.(s)}
              className="text-left text-sm px-3.5 py-2 rounded-full transition-colors"
              style={{
                border: '1px solid var(--border-2, rgba(255,255,255,0.08))',
                backgroundColor: 'var(--bg-2)',
                color: 'var(--fg-1)',
              }}
            >
              <ArrowRight size={12} className="inline-block mr-2" style={{ verticalAlign: '-2px' }} />
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2.5">
        <button
          type="button"
          onClick={() => onUploadClick ? onUploadClick() : navigate('/')}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm transition-colors"
          style={{ backgroundColor: 'var(--signature)', color: '#fff', border: '1px solid var(--signature)' }}
        >
          <Upload size={14} />
          {t('chat.upload')}
        </button>
        <button
          type="button"
          onClick={() => navigate('/')}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm transition-colors"
          style={{
            backgroundColor: 'transparent',
            color: 'var(--signature)',
            border: '1px solid var(--signature)',
          }}
        >
          <LayoutDashboard size={14} />
          {t('chat.browseDashboard')}
        </button>
      </div>
    </div>
  )
}

function Stat({ value, label }) {
  return (
    <div>
      <div
        style={{
          fontFamily: 'var(--mono, ui-monospace, monospace)',
          fontSize: '32px',
          color: 'var(--fg)',
          lineHeight: 1.05,
        }}
      >
        {value}
      </div>
      <div
        style={{
          fontFamily: 'var(--mono, ui-monospace, monospace)',
          fontSize: '10px',
          color: 'var(--fg-faint)',
          letterSpacing: '0.14em',
          marginTop: '2px',
        }}
      >
        {label}
      </div>
    </div>
  )
}

function formatNumber(n) {
  if (typeof n !== 'number') return String(n)
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, '') + 'K'
  return n.toLocaleString()
}
