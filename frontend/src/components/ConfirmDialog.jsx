import { useEffect } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  danger = false,
  onConfirm,
  onCancel,
}) {
  const { t } = useTranslation()

  useEffect(() => {
    if (!open) return
    const handleKey = (e) => {
      if (e.key === 'Escape') onCancel?.()
      if (e.key === 'Enter') onConfirm?.()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [open, onConfirm, onCancel])

  if (!open) return null

  const titleText = title ?? t('common.confirm')
  const confirmText = confirmLabel ?? t('common.confirm')
  const cancelText = cancelLabel ?? t('common.cancel')

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0,0,0,0.6)' }}
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm rounded-lg border p-5 shadow-2xl"
        style={{
          backgroundColor: 'var(--bg-1)',
          borderColor: 'var(--border-strong)',
          color: 'var(--fg)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          {danger && (
            <div className="shrink-0 mt-0.5">
              <AlertTriangle size={20} style={{ color: 'var(--bad)' }} />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold mb-1">{titleText}</h3>
            <p className="text-xs opacity-70">{message}</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded transition-opacity opacity-70 hover:opacity-100"
            style={{ backgroundColor: 'var(--bg-3)' }}
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs rounded font-medium text-white transition-opacity hover:opacity-90"
            style={{
              backgroundColor: danger ? 'var(--bad)' : 'var(--signature)',
            }}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
