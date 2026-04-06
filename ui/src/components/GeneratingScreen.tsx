import { useEffect, useState } from 'react'

const steps = [
  'Parsing document structure...',
  'Retrieving relevant content...',
  'Planning slide structure...',
  'Resolving layouts...',
  'Assembling deck...',
]

interface GeneratingScreenProps {
  complete: boolean
  error: string | null
  onComplete: () => void
  onRetry: () => void
}

export function GeneratingScreen({ complete, error, onComplete, onRetry }: GeneratingScreenProps) {
  const [completeCount, setCompleteCount] = useState(0)

  useEffect(() => {
    setCompleteCount(0)
    const timers = steps.map((_, index) => window.setTimeout(() => setCompleteCount(index + 1), (index + 1) * 450))
    return () => timers.forEach((timer) => window.clearTimeout(timer))
  }, [error])

  useEffect(() => {
    if (!complete || error) return
    const timer = window.setTimeout(onComplete, 400)
    return () => window.clearTimeout(timer)
  }, [complete, error, onComplete])

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-10 shadow-panel">
      <h2 className="text-2xl font-semibold text-slate-950">Generating your deck</h2>
      <div className="mt-6 space-y-3">
        {steps.map((step, index) => (
          <div key={step} className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3 text-sm">
            <span className="text-slate-700">{step}</span>
            <span className={index < completeCount || complete ? 'text-emerald-600' : 'text-slate-400'}>
              {index < completeCount || complete ? 'Done' : '...'}
            </span>
          </div>
        ))}
      </div>
      {error ? (
        <div className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 p-4">
          <div className="text-sm text-rose-900">{error}</div>
          <button type="button" onClick={onRetry} className="mt-4 rounded-xl bg-slate-950 px-4 py-2 text-sm text-white">
            Try again
          </button>
        </div>
      ) : null}
    </div>
  )
}
