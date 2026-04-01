import { useEffect, useRef } from 'react'

export default function ContextMenu({ x, y, items, onClose }) {
  const ref = useRef(null)

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  if (!items || items.length === 0) return null

  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-[160px] py-1 rounded-lg shadow-xl"
      style={{
        left: x,
        top: y,
        backgroundColor: 'hsl(222 47% 12%)',
        border: '1px solid hsl(217 33% 22%)',
      }}
    >
      {items.map((item, i) =>
        item.separator ? (
          <div key={i} className="my-1 border-t" style={{ borderColor: 'hsl(217 33% 17%)' }} />
        ) : (
          <button
            key={i}
            onClick={() => { item.action(); onClose() }}
            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-left transition-colors hover:bg-white/10"
            style={{ color: item.danger ? 'hsl(0 84% 60%)' : 'hsl(210 40% 98%)' }}
          >
            {item.icon && <item.icon size={12} />}
            {item.label}
          </button>
        )
      )}
    </div>
  )
}
