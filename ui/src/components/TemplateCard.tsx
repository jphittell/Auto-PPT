import type { Template } from '../types'

interface TemplateCardProps {
  template: Template
  selected?: boolean
  onSelect?: () => void
}

export function TemplateCard({ template, selected = false, onSelect }: TemplateCardProps) {
  const columns = Array.from({ length: template.columns })

  return (
    <div className={`rounded-3xl border p-4 shadow-sm ${selected ? 'border-indigo-500 bg-indigo-50' : 'border-slate-200 bg-white'}`}>
      <div className="mb-4 rounded-2xl border border-slate-200 bg-slate-50 p-3">
        <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${template.columns}, minmax(0, 1fr))` }}>
          {columns.map((_, index) => (
            <div key={index} className="h-16 rounded-xl bg-gradient-to-b from-indigo-100 to-white ring-1 ring-inset ring-slate-200" />
          ))}
        </div>
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold text-slate-950">{template.name}</h3>
          <span className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">{template.columns} col</span>
        </div>
        <p className="text-xs uppercase tracking-wide text-slate-500">{template.alias}</p>
        <p className="text-sm text-slate-600">{template.description}</p>
      </div>
      {onSelect ? (
        <button
          type="button"
          onClick={onSelect}
          className={`mt-4 w-full rounded-xl px-4 py-2 text-sm font-medium ${
            selected ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-white'
          }`}
        >
          {selected ? 'Selected' : 'Select'}
        </button>
      ) : null}
    </div>
  )
}
