import type { SlideSpec } from '../types'
import { BlockRenderer } from './BlockRenderer'

interface SlideCanvasProps {
  slide: SlideSpec
  onTitleChange: (title: string) => void
  onBlockChange: (blockIndex: number, content: string) => void
}

export function SlideCanvas({ slide, onTitleChange, onBlockChange }: SlideCanvasProps) {
  return (
    <div className="flex-1 p-6">
      <div className="rounded-[32px] border border-slate-200 bg-white p-8 shadow-panel">
        <div className="mb-6 flex items-start justify-between gap-4">
          <input
            value={slide.title}
            onChange={(event) => onTitleChange(event.target.value)}
            className="w-full border-none bg-transparent text-3xl font-semibold text-slate-950 outline-none"
          />
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-indigo-50 px-3 py-1 text-sm font-medium capitalize text-indigo-700">
              {slide.purpose}
            </span>
            {slide.archetype ? (
              <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-600">
                {slide.archetype.replace(/_/g, ' ')}
              </span>
            ) : null}
          </div>
        </div>
        <div className="space-y-5">
          {slide.blocks.map((block, index) => (
            <div key={block.id}>
              <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">{block.kind.replace('_', ' ')}</div>
              <BlockRenderer block={block} onChange={(content) => onBlockChange(index, content)} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
