import type { IngestResult } from '../types'

export function IngestResultCard({ result }: { result: IngestResult }) {
  const total = Object.values(result.element_types).reduce((sum, count) => sum + count, 0) || 1

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-panel">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm text-slate-500">Detected document</p>
          <h3 className="text-lg font-semibold text-slate-950">{result.title}</h3>
        </div>
        <div className="flex gap-6 text-sm">
          <div>
            <p className="text-slate-500">Chunks</p>
            <p className="font-semibold text-slate-950">{result.chunk_count}</p>
          </div>
          <div>
            <p className="text-slate-500">Doc ID</p>
            <p className="font-semibold text-slate-950">{result.doc_id}</p>
          </div>
        </div>
      </div>
      <div className="mt-5 space-y-3">
        {Object.entries(result.element_types).map(([key, count]) => (
          <div key={key} className="space-y-1">
            <div className="flex items-center justify-between text-sm">
              <span className="capitalize text-slate-700">{key.replace('_', ' ')}</span>
              <span className="font-medium text-slate-900">{count}</span>
            </div>
            <div className="h-2 rounded-full bg-slate-100">
              <div className="h-2 rounded-full bg-indigo-500" style={{ width: `${(count / total) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
