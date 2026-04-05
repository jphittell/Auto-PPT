import type { ContentBlock } from '../types'

interface BlockRendererProps {
  block: ContentBlock
  onChange: (content: string) => void
}

function renderKpiRows(content: string) {
  return content
    .split('\n')
    .filter(Boolean)
    .map((item) => {
      const [value, label] = item.split('|')
      return { value: value ?? '', label: label ?? '' }
    })
}

export function BlockRenderer({ block, onChange }: BlockRendererProps) {
  if (block.kind === 'image') {
    return (
      <div className="rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">
        <div className="mb-2 font-medium text-slate-700">Image slot</div>
        <textarea
          value={block.content}
          onChange={(event) => onChange(event.target.value)}
          className="h-24 w-full resize-none rounded-xl border border-slate-200 bg-white p-3 outline-none"
        />
      </div>
    )
  }

  if (block.kind === 'quote') {
    return (
      <blockquote className="rounded-2xl border-l-4 border-indigo-500 bg-indigo-50 p-5">
        <textarea
          value={block.content}
          onChange={(event) => onChange(event.target.value)}
          className="h-24 w-full resize-none border-none bg-transparent text-lg italic text-slate-800 outline-none"
        />
      </blockquote>
    )
  }

  if (block.kind === 'callout') {
    return (
      <div className="rounded-2xl bg-amber-50 p-5 ring-1 ring-amber-200">
        <textarea
          value={block.content}
          onChange={(event) => onChange(event.target.value)}
          className="h-24 w-full resize-none border-none bg-transparent text-slate-900 outline-none"
        />
      </div>
    )
  }

  if (block.kind === 'kpi_cards') {
    const rows = renderKpiRows(block.content)
    return (
      <div>
        <div className="grid gap-4 md:grid-cols-3">
          {rows.map((row, index) => (
            <div key={index} className="rounded-2xl border border-slate-200 bg-white p-4 text-center shadow-sm">
              <div className="text-3xl font-semibold text-slate-950">{row.value}</div>
              <div className="mt-1 text-sm text-slate-500">{row.label}</div>
            </div>
          ))}
        </div>
        <textarea
          value={block.content}
          onChange={(event) => onChange(event.target.value)}
          className="mt-4 h-24 w-full resize-none rounded-xl border border-slate-200 p-3 text-sm outline-none"
        />
      </div>
    )
  }

  if (block.kind === 'bullets') {
    const items = block.content.split('\n').filter(Boolean)
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-5">
        <ul className="mb-4 list-disc space-y-2 pl-5 text-slate-800">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <textarea
          value={block.content}
          onChange={(event) => onChange(event.target.value)}
          className="h-28 w-full resize-none rounded-xl border border-slate-200 p-3 text-sm outline-none"
        />
      </div>
    )
  }

  return (
    <textarea
      value={block.content}
      onChange={(event) => onChange(event.target.value)}
      className="min-h-28 w-full resize-y rounded-2xl border border-slate-200 bg-white p-4 text-slate-900 outline-none shadow-sm"
    />
  )
}
