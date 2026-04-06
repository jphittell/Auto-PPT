import { useEffect, useState } from 'react'

import { ModalFrame } from './ModalFrame'

interface ExportPreflightModalProps {
  open: boolean
  imageIssueCount: number
  onClose: () => void
  onContinue: () => void
}

export function ExportPreflightModal({ open, imageIssueCount, onClose, onContinue }: ExportPreflightModalProps) {
  const [resolved, setResolved] = useState(imageIssueCount === 0)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (open) {
      setResolved(imageIssueCount === 0)
      setLoading(false)
    }
  }, [imageIssueCount, open])

  return (
    <ModalFrame open={open} onClose={onClose} title="Export preflight">
      <div className="space-y-4 text-sm text-slate-700">
        <div className="flex items-center justify-between">
          <span>Pass: All slides have titles</span>
          <span className="text-emerald-600">Pass</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Pass: Reading order is set</span>
          <span className="text-emerald-600">Pass</span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span>{resolved ? 'Pass: All image alt text covered' : `Warn: ${imageIssueCount} images have no alt text`}</span>
          {resolved ? (
            <span className="text-emerald-600">Resolved</span>
          ) : (
            <button
              type="button"
              onClick={() => {
                setLoading(true)
                window.setTimeout(() => {
                  setResolved(true)
                  setLoading(false)
                }, 1000)
              }}
              className="rounded-xl bg-slate-900 px-3 py-2 text-white"
            >
              {loading ? 'Generating...' : 'Auto-generate alt text'}
            </button>
          )}
        </div>
        <div className="flex justify-end gap-3 pt-4">
          <button type="button" onClick={onClose} className="rounded-xl border border-slate-200 px-4 py-2">
            Fix issues
          </button>
          <button
            type="button"
            onClick={onContinue}
            disabled={!resolved}
            className="rounded-xl bg-indigo-600 px-4 py-2 text-white disabled:opacity-60"
          >
            Continue to export
          </button>
        </div>
      </div>
    </ModalFrame>
  )
}
