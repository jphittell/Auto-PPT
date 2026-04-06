import type { IngestResult } from '../types'

export function IngestResultCard({ result, onRemove }: { result: IngestResult; onRemove?: () => void }) {
  const sections = result.element_types.heading ?? 0
  const chunks = result.chunk_count

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-panel">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm text-slate-500">Uploaded document</p>
          <h3 className="text-lg font-semibold text-slate-950">{result.title}</h3>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-slate-400">{chunks} chunks · {sections} sections</span>
          {onRemove ? (
            <button type="button" onClick={onRemove} className="rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-600">
              Remove
            </button>
          ) : null}
        </div>
      </div>
      {result.summary ? (
        <div className="mt-4 rounded-2xl bg-slate-50 p-4 text-sm leading-6 text-slate-700">{result.summary}</div>
      ) : null}
    </div>
  )
}
