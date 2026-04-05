import { useState } from 'react'

import type { SlideSpec } from '../types'

interface OutlineTreeEditorProps {
  slides: SlideSpec[]
  onTitleChange: (index: number, title: string) => void
  onReorder: (fromIndex: number, toIndex: number) => void
}

export function OutlineTreeEditor({ slides, onTitleChange, onReorder }: OutlineTreeEditorProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  return (
    <div className="space-y-3">
      {slides.map((slide, index) => (
        <div
          key={slide.id}
          draggable
          onDragStart={() => setDragIndex(index)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={() => {
            if (dragIndex !== null && dragIndex !== index) onReorder(dragIndex, index)
            setDragIndex(null)
          }}
          className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
        >
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-sm font-semibold text-slate-700">
              {index + 1}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium capitalize text-indigo-700">
                  {slide.purpose}
                </span>
                <input
                  value={slide.title}
                  onChange={(event) => onTitleChange(index, event.target.value)}
                  className="min-w-0 flex-1 border-none bg-transparent text-base font-semibold text-slate-950 outline-none"
                />
                <button
                  type="button"
                  onClick={() => setExpanded((state) => ({ ...state, [slide.id]: !state[slide.id] }))}
                  className="text-sm text-slate-500"
                >
                  {expanded[slide.id] ? 'Collapse' : 'Expand'}
                </button>
              </div>
              {expanded[slide.id] ? (
                <ul className="mt-3 space-y-2 text-sm text-slate-600">
                  {slide.blocks.map((block) => (
                    <li key={block.id}>
                      <span className="font-medium capitalize text-slate-800">{block.kind.replace('_', ' ')}:</span>{' '}
                      {block.content.slice(0, 110)}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
