import type { IngestResult } from '../types'

export function IngestResultCard({ result, onRemove }: { result: IngestResult; onRemove?: () => void }) {
  const sections = result.element_types.heading ?? 0
  const paragraphs = result.element_types.paragraph ?? 0
  const bulletItems = result.element_types.list_item ?? 0
  const summaryParts = [
    `${result.title} was processed into ${result.chunk_count} content chunks.`,
    sections > 0 ? `It includes ${sections} section heading${sections === 1 ? '' : 's'}.` : null,
    paragraphs > 0 ? `The document contains ${paragraphs} paragraph block${paragraphs === 1 ? '' : 's'}.` : null,
    bulletItems > 0 ? `It also includes ${bulletItems} bullet item${bulletItems === 1 ? '' : 's'}.` : null,
  ].filter(Boolean)

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-panel">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm text-slate-500">Uploaded document</p>
          <h3 className="text-lg font-semibold text-slate-950">{result.title}</h3>
        </div>
        <div className="flex gap-6 text-sm">
          {onRemove ? (
            <button type="button" onClick={onRemove} className="self-start rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-600">
              Remove
            </button>
          ) : null}
        </div>
      </div>
      <div className="mt-4 rounded-2xl bg-slate-50 p-4 text-sm leading-6 text-slate-700">{summaryParts.join(' ')}</div>
    </div>
  )
}
