import { useEffect, useState } from 'react'
import { Sun, Moon } from 'lucide-react'

const STORAGE_KEY = 'meinrag-theme'

function readInitial() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch { /* localStorage unavailable */ }
  return 'dark'
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(readInitial)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'light') root.setAttribute('data-theme', 'light')
    else root.removeAttribute('data-theme')
    try { localStorage.setItem(STORAGE_KEY, theme) } catch { /* ignore */ }
  }, [theme])

  const toggle = () => setTheme(t => (t === 'light' ? 'dark' : 'light'))
  const Icon = theme === 'light' ? Moon : Sun

  return (
    <button
      onClick={toggle}
      className="flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs rounded transition-colors opacity-60 hover:opacity-100"
      style={{ color: 'var(--fg-dim)' }}
      title={theme === 'light' ? 'Switch to dark' : 'Switch to light'}
      aria-label={theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
    >
      <Icon size={16} className="shrink-0" />
    </button>
  )
}
