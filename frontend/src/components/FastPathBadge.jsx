import { FileText } from 'lucide-react'
import { useTranslation } from 'react-i18next'

/**
 * Shown when the backend answered via the pre-computed document summary
 * fast-path (skipping full retrieval). Signals to the user that the answer
 * draws on an authoritative doc-level overview rather than chunk synthesis.
 */
export default function FastPathBadge() {
  const { t } = useTranslation()
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium"
      style={{
        backgroundColor: 'var(--signature-soft)',
        color: 'var(--signature)',
      }}
      title={t('chat.fastPathTitle', {
        defaultValue: 'Answer uses pre-computed document summary',
      })}
    >
      <FileText size={10} />
      {t('chat.fastPath', { defaultValue: 'doc summary' })}
    </span>
  )
}
