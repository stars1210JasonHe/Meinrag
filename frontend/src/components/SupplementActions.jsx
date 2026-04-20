import { Sparkles, Globe } from 'lucide-react'
import { useTranslation } from 'react-i18next'

/**
 * Actions shown below an AI message that refused because the corpus had
 * no relevant content. Offers two escape hatches:
 *   - Ask general AI (uses /query/ask-ai/stream, no corpus)
 *   - Search the web (uses /query/stream with force_web_search=true)
 *
 * Props:
 *   question: string — the original user question to resend
 *   onAskAi: (question: string) => void
 *   onSearchWeb: (question: string) => void
 *   busy: "ai" | "web" | null — whether a supplement request is in flight
 */
export default function SupplementActions({ question, onAskAi, onSearchWeb, busy }) {
  const { t } = useTranslation()

  return (
    <div className="mt-3 flex flex-col gap-2">
      <div className="text-xs" style={{ color: 'var(--fg-dim)' }}>
        {t('supplement.prompt', {
          defaultValue: "The corpus couldn't answer. Try another source?",
        })}
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onAskAi(question)}
          disabled={!!busy}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md
                     bg-[color:var(--signature,#5b7ec9)] text-white font-medium
                     hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed
                     transition"
        >
          <Sparkles size={14} />
          <span>{t('supplement.askAi', { defaultValue: 'Ask general AI' })}</span>
        </button>
        <button
          type="button"
          onClick={() => onSearchWeb(question)}
          disabled={!!busy}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md
                     bg-white/5 text-[color:var(--fg,#f4f2ee)] hover:bg-white/10
                     disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          <Globe size={14} />
          <span>{t('supplement.searchWeb', { defaultValue: 'Search the web' })}</span>
        </button>
      </div>
    </div>
  )
}
