import { useTranslation } from 'react-i18next'
import { Languages } from 'lucide-react'

const LANGS = [
  { code: 'en', label: 'EN' },
  { code: 'zh', label: '中' },
]

export default function LanguageSwitcher() {
  const { i18n } = useTranslation()
  const current = i18n.resolvedLanguage
  const next = LANGS.find(l => l.code !== current) ?? LANGS[0]
  const currentLabel = LANGS.find(l => l.code === current)?.label ?? 'EN'

  return (
    <button
      onClick={() => i18n.changeLanguage(next.code)}
      className="flex items-center justify-center gap-1 px-2 py-1.5 text-xs rounded transition-colors opacity-60 hover:opacity-100"
      style={{ color: 'var(--fg-dim)' }}
      title={`Switch to ${next.label === 'EN' ? 'English' : '中文'}`}
      aria-label={`Switch language (currently ${currentLabel})`}
    >
      <Languages size={16} className="shrink-0" />
      <span className="font-medium">{currentLabel}</span>
    </button>
  )
}
