import type { ContentBlock } from '../types'

interface BlockRendererProps {
  block: ContentBlock
  onChange: (content: string) => void
  mode?: 'editor' | 'preview'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
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

function renderCardsFromData(data: unknown) {
  if (!isRecord(data) || !Array.isArray(data.cards)) return []
  return data.cards
    .filter((item): item is Record<string, unknown> => isRecord(item))
    .map((item) => ({
      title: typeof item.title === 'string' ? item.title : '',
      text: typeof item.text === 'string' ? item.text : '',
    }))
}

function renderBulletItems(block: ContentBlock) {
  if (isRecord(block.data) && Array.isArray(block.data.items)) {
    return block.data.items.filter((item): item is string => typeof item === 'string')
  }
  return block.content
    .split('\n')
    .filter(Boolean)
    .map((item) => item.replace(/^[\u2022*-]\s*/, ''))
}

export function BlockRenderer({ block, onChange, mode = 'editor' }: BlockRendererProps) {
  const isPreview = mode === 'preview'

  const renderEditor = (className: string) => (
    <textarea
      value={block.content}
      onChange={(event) => onChange(event.target.value)}
      className={className}
    />
  )

  if (block.kind === 'image') {
    return (
      <div className="rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">
        <div className="mb-2 font-medium text-slate-700">Image slot</div>
        {isPreview ? (
          <div className="rounded-xl border border-slate-200 bg-white p-3 text-slate-500">{block.content || 'No image selected.'}</div>
        ) : (
          renderEditor('h-24 w-full resize-none rounded-xl border border-slate-200 bg-white p-3 outline-none')
        )}
      </div>
    )
  }

  if (block.kind === 'quote') {
    return (
      <blockquote className="rounded-2xl border-l-4 border-indigo-500 bg-indigo-50 p-5">
        {isPreview ? (
          <div className="text-lg italic text-slate-800">{block.content}</div>
        ) : (
          renderEditor('h-24 w-full resize-none border-none bg-transparent text-lg italic text-slate-800 outline-none')
        )}
      </blockquote>
    )
  }

  if (block.kind === 'callout') {
    const cards = renderCardsFromData(block.data)
    if (cards.length > 0 && isPreview) {
      return (
        <div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {cards.map((card, index) => (
              <div key={`${card.title}-${index}`} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="text-sm font-semibold text-slate-950">{card.title}</div>
                <div className="mt-2 text-sm text-slate-600">{card.text}</div>
              </div>
            ))}
          </div>
        </div>
      )
    }
    return (
      <div className="rounded-2xl bg-amber-50 p-5 ring-1 ring-amber-200">
        {isPreview ? (
          <div className="text-slate-900">{block.content}</div>
        ) : (
          renderEditor('h-24 w-full resize-none border-none bg-transparent text-slate-900 outline-none')
        )}
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
        {!isPreview ? renderEditor('mt-4 h-24 w-full resize-none rounded-xl border border-slate-200 p-3 text-sm outline-none') : null}
      </div>
    )
  }

  if (block.kind === 'bullets') {
    const items = renderBulletItems(block)
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-5">
        <ul className="mb-4 list-disc space-y-2 pl-5 text-slate-800">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        {!isPreview ? renderEditor('h-28 w-full resize-none rounded-xl border border-slate-200 p-3 text-sm outline-none') : null}
      </div>
    )
  }

  if (isPreview) {
    return <div className="rounded-2xl border border-slate-200 bg-white p-4 text-slate-900 shadow-sm">{block.content}</div>
  }

  return renderEditor('min-h-28 w-full resize-y rounded-2xl border border-slate-200 bg-white p-4 text-slate-900 outline-none shadow-sm')
}
