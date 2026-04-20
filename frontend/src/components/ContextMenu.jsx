import { useEffect, useRef } from 'react'

export default function ContextMenu({ x, y, items, onClose }) {
  const ref = useRef(null)

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    const keyHandler = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', handler)
    document.addEventListener('click', handler)
    document.addEventListener('contextmenu', handler)
    document.addEventListener('keydown', keyHandler)
    return () => {
      document.removeEventListener('mousedown', handler)
      document.removeEventListener('click', handler)
      document.removeEventListener('contextmenu', handler)
      document.removeEventListener('keydown', keyHandler)
    }
  }, [onClose])

  if (!items || items.length === 0) return null

  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-[160px] py-1 rounded-lg shadow-xl"
      style={{
        left: x,
        top: y,
        backgroundColor: 'var(--bg-2)',
        border: '1px solid var(--border-strong)',
      }}
    >
      {items.map((item, i) =>
        item.separator ? (
          <div key={i} className="my-1 border-t" style={{ borderColor: 'var(--border-strong)' }} />
        ) : (
          <button
            key={i}
            onClick={() => { item.action(); onClose() }}
            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-left transition-colors hover:bg-white/10"
            style={{ color: item.danger ? 'var(--bad)' : 'var(--fg)' }}
          >
            {item.icon && <item.icon size={12} />}
            {item.label}
          </button>
        )
      )}
    </div>
  )
}
