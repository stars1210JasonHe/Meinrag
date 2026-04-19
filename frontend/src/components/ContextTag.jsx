import { useState } from 'react'
import { Database } from 'lucide-react'

/**
 * Small pill showing chunks used + token count.
 * Hoverable for explanation. Subtle — sits next to confidence badge.
 *
 * Props:
 *   chunks: number of chunks sent to LLM
 *   available: total chunks available before truncation (optional)
 *   tokens: token count of context
 *   budget: budget tokens
 *   mode: "chunks" | "summary"
 */
export default function ContextTag({ chunks, available, tokens, budget, mode }) {
  const [open, setOpen] = useState(false)
  if (chunks == null) return null

  const truncated = available != null && chunks < available
  const modeLabel = mode === 'summary' ? 'summaries' : 'chunks'
  const tokensK = tokens != null ? `~${(tokens / 1000).toFixed(1)}K` : null
  const budgetK = budget != null ? `/${(budget / 1000).toFixed(1)}K` : ''

  return (
    <span
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      className="relative inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium bg-white/5 border border-white/10 text-[color:var(--fg-dim,#888)] cursor-default"
    >
      <Database size={10} />
      <span>
        {chunks}
        {truncated ? `/${available}` : ''} {modeLabel}
        {tokensK && <span className="opacity-60"> · {tokensK}{budgetK} tok</span>}
      </span>
      {open && (
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 z-10 whitespace-nowrap rounded-md px-2.5 py-1.5 text-[11px] bg-black/85 text-white/90 pointer-events-none shadow-lg">
          {mode === 'summary'
            ? `Using document summaries — ask a follow-up to zoom in.`
            : truncated
              ? `Showing top ${chunks} of ${available} retrieved chunks (fit in context budget).`
              : `${chunks} chunk${chunks === 1 ? '' : 's'} fed to the model.`}
          {tokens != null && budget != null && (
            <div className="opacity-70 mt-0.5">{tokens.toLocaleString()} / {budget.toLocaleString()} tokens used</div>
          )}
        </span>
      )}
    </span>
  )
}
