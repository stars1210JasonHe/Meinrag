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

  return (
    <button
      onClick={() => i18n.changeLanguage(next.code)}
      className="flex items-center gap-3 px-4 py-2.5 text-sm transition-colors opacity-60 hover:opacity-100 w-full"
      style={{ color: 'var(--fg-dim)' }}
      title={`Switch to ${next.label === 'EN' ? 'English' : '中文'}`}
    >
      <Languages size={18} className="shrink-0" />
      <span className="whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
        {LANGS.find(l => l.code === current)?.label ?? 'EN'}
      </span>
    </button>
  )
}
