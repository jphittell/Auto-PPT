import { useEffect, useMemo, useRef } from 'react'
import type { ReactNode } from 'react'

interface ModalFrameProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

export function ModalFrame({ open, title, onClose, children }: ModalFrameProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const previousFocus = useRef<Element | null>(null)
  const titleId = useMemo(() => `modal-${title.toLowerCase().replace(/\s+/g, '-')}`, [title])

  useEffect(() => {
    if (!open) return
    previousFocus.current = document.activeElement
    const container = containerRef.current
    const nodes = container?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []
    nodes[0]?.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key !== 'Tab' || nodes.length === 0) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      if (previousFocus.current instanceof HTMLElement) {
        previousFocus.current.focus()
      }
    }
  }, [onClose, open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/50 px-4">
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-xl rounded-3xl bg-white p-6 shadow-panel"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 id={titleId} className="text-xl font-semibold text-slate-950">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-slate-200 px-3 py-1 text-sm text-slate-600"
            aria-label="Close modal"
          >
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
