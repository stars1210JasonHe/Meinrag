import { useRef, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

const API_BASE = import.meta.env.VITE_API_URL
const USER_ID = 'admin'

/**
 * Renders a .docx document in the browser via docx-preview, then wraps
 * each chunk's text in a marker span for highlight + scroll-to.
 *
 * Props:
 *   docId               — document id (URL :docId)
 *   activeChunkIndex    — number | null; chunk to highlight + scroll to
 */
export default function DocxViewer({ docId, activeChunkIndex }) {
  const { t } = useTranslation()
  const containerRef = useRef(null)
  const [status, setStatus] = useState('loading')  // 'loading' | 'ready' | 'error'
  const [errorMsg, setErrorMsg] = useState('')
  const [blob, setBlob] = useState(null)

  useEffect(() => {
    if (!docId) return
    let cancelled = false
    setStatus('loading')
    fetch(`${API_BASE}/documents/${docId}/download`, { headers: { 'X-User-Id': USER_ID } })
      .then(r => {
        if (!r.ok) throw new Error(`Backend returned HTTP ${r.status}`)
        return r.blob()
      })
      .then(b => {
        if (!cancelled) setBlob(b)
      })
      .catch(err => {
        if (!cancelled) {
          setStatus('error')
          setErrorMsg(err.message)
        }
      })
    return () => { cancelled = true }
  }, [docId])

  // TODO Task 4.2-4.5: fetch blob + chunks, render via docx-preview, wrap chunks.

  return (
    <div className="flex flex-col h-full overflow-auto p-4" ref={containerRef}>
      {status === 'loading' && (
        <div className="opacity-40 text-sm">
          {t('pdfViewer.loadingDocx', { defaultValue: 'Loading document…' })}
        </div>
      )}
      {status === 'error' && (
        <div className="opacity-60 text-sm" style={{ color: 'var(--warn)' }}>
          {t('pdfViewer.docxRenderFailed', { defaultValue: 'Failed to render .docx' })}
          {errorMsg && <div className="text-xs opacity-60 mt-1">{errorMsg}</div>}
        </div>
      )}
    </div>
  )
}
