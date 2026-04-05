import { useEffect, useState } from 'react'

const steps = [
  'Parsing document structure…',
  'Retrieving relevant content…',
  'Planning slide structure…',
  'Resolving layouts…',
  'Assembling deck…',
]

export function GeneratingScreen({ onComplete }: { onComplete: () => void }) {
  const [completeCount, setCompleteCount] = useState(0)

  useEffect(() => {
    const timers = steps.map((_, index) =>
      window.setTimeout(() => {
        setCompleteCount(index + 1)
        if (index === steps.length - 1) {
          window.setTimeout(onComplete, 400)
        }
      }, (index + 1) * 600),
    )
    return () => timers.forEach((timer) => window.clearTimeout(timer))
  }, [onComplete])

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-10 shadow-panel">
      <h2 className="text-2xl font-semibold text-slate-950">Generating your deck</h2>
      <div className="mt-6 space-y-3">
        {steps.map((step, index) => (
          <div key={step} className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3 text-sm">
            <span className="text-slate-700">{step}</span>
            <span className={index < completeCount ? 'text-emerald-600' : 'text-slate-400'}>
              {index < completeCount ? '✓' : '…'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
