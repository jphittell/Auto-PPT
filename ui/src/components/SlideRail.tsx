import type { SlideSpec } from '../types'

interface SlideRailProps {
  slides: SlideSpec[]
  selectedSlideIndex: number
  onSelect: (index: number) => void
  onAddSlide: () => void
}

export function SlideRail({ slides, selectedSlideIndex, onSelect, onAddSlide }: SlideRailProps) {
  return (
    <aside className="flex h-full w-60 flex-col border-r border-slate-200 bg-white">
      <div className="flex-1 overflow-y-auto p-4">
        <div className="space-y-3">
          {slides.map((slide, index) => (
            <button
              key={slide.id}
              type="button"
              onClick={() => onSelect(index)}
              className={`w-full rounded-2xl border p-3 text-left ${
                selectedSlideIndex === index ? 'border-indigo-500 bg-indigo-50' : 'border-slate-200 bg-white'
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold text-slate-500">#{index + 1}</span>
                <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] capitalize text-slate-600">
                  {slide.purpose}
                </span>
              </div>
              <div className="mt-2 line-clamp-2 text-sm font-medium text-slate-900">{slide.title}</div>
            </button>
          ))}
        </div>
      </div>
      <div className="border-t border-slate-200 p-4">
        <button
          type="button"
          onClick={onAddSlide}
          className="w-full rounded-xl bg-slate-950 px-4 py-2 text-sm font-medium text-white"
        >
          + Add slide
        </button>
      </div>
    </aside>
  )
}
