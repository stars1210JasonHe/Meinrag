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
