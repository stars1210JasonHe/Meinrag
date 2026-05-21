import { useRef, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchDocumentChunks } from '@/lib/api'
import { wrapChunkSpans } from '@/lib/docxChunkMapper'

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

  const { data: chunksData } = useQuery({
    queryKey: ['doc-chunks-all', docId],
    queryFn: () => fetchDocumentChunks(docId, null, USER_ID),
    enabled: !!docId,
    staleTime: 5 * 60_000,
  })
  const chunks = chunksData?.chunks || []

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

  // Render the docx into the container DOM once the blob is fetched.
  useEffect(() => {
    if (!blob || !containerRef.current) return
    let cancelled = false

    // Lazy-load docx-preview only when we actually need it. Keeps the
    // initial Vite chunk small for users who never open a .docx.
    import('docx-preview').then(({ renderAsync }) => {
      if (cancelled) return
      // Clear any previous render
      containerRef.current.innerHTML = ''
      return renderAsync(blob, containerRef.current, null, {
        inWrapper: true,
        breakPages: false,
        ignoreWidth: false,
        ignoreHeight: true,
        useBase64URL: true,
      })
    }).then(() => {
      if (cancelled) return
      if (containerRef.current && chunks.length > 0) {
        const summary = wrapChunkSpans(containerRef.current, chunks)
        console.log(
          `[DocxViewer] wrapped ${summary.matched} chunks, skipped ${summary.skipped}`,
          summary.skippedChunks.length > 0 ? { skippedChunks: summary.skippedChunks } : ''
        )
      }
      setStatus('ready')
    }).catch(err => {
      if (!cancelled) {
        setStatus('error')
        setErrorMsg(err.message || 'docx-preview render failed')
      }
    })

    return () => { cancelled = true }
  }, [blob, chunks])

  // When activeChunkIndex changes, scroll to + highlight that chunk.
  useEffect(() => {
    if (status !== 'ready' || activeChunkIndex == null || !containerRef.current) return

    // Clear previous active class
    containerRef.current.querySelectorAll('.chunk-marker.chunk-active')
      .forEach(el => el.classList.remove('chunk-active'))

    const el = containerRef.current.querySelector(`[data-chunk-index="${activeChunkIndex}"]`)
    if (!el) {
      console.warn(`[DocxViewer] activeChunkIndex ${activeChunkIndex} not found in DOM`)
      return
    }
    el.classList.add('chunk-active')
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [status, activeChunkIndex])

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
