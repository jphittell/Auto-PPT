import type { Template, SlideSpec } from '../types'
import { BlockRenderer } from './BlockRenderer'

interface SlideCanvasProps {
  slide: SlideSpec
  templates: Template[]
  previewSlide?: SlideSpec | null
  deckTitle?: string
  audience?: string
  themeName?: string | null
  promptText: string
  onPromptTextChange: (value: string) => void
  onSlideTypeChange: (templateId: string) => void
  onGeneratePreview: () => void
  previewLoading?: boolean
}

function previewCards(slide: SlideSpec) {
  return slide.blocks
    .flatMap((block) => {
      const data = block.data
      if (!data || typeof data !== 'object' || !('cards' in data) || !Array.isArray(data.cards)) return []
      return data.cards
    })
    .filter((item): item is { title?: string; text?: string } => typeof item === 'object' && item !== null)
    .map((item) => ({
      title: typeof item.title === 'string' ? item.title : '',
      text: typeof item.text === 'string' ? item.text : '',
    }))
}

function previewKpis(slide: SlideSpec) {
  return slide.blocks
    .flatMap((block) => {
      const data = block.data
      if (!data || typeof data !== 'object' || !('items' in data) || !Array.isArray(data.items)) return []
      return data.items
    })
    .filter((item): item is { value?: string; label?: string } => typeof item === 'object' && item !== null)
    .map((item) => ({
      value: typeof item.value === 'string' ? item.value : '',
      label: typeof item.label === 'string' ? item.label : '',
    }))
}

function previewPlainText(slide: SlideSpec) {
  return slide.blocks.map((block) => block.content).filter(Boolean)
}

function SlidePreviewSurface({
  slide,
  deckTitle,
  audience,
}: {
  slide: SlideSpec
  deckTitle?: string
  audience?: string
}) {
  const cards = previewCards(slide)
  const kpis = previewKpis(slide)
  const textBlocks = previewPlainText(slide)
  const lead = textBlocks[0] ?? ''

  if (slide.template_id === 'title.cover') {
    return (
      <div className="flex h-full flex-col rounded-[28px] border border-stone-200 bg-[radial-gradient(circle_at_top,_rgba(199,70,52,0.14),_transparent_38%),linear-gradient(180deg,_#fff_0%,_#fff8f6_100%)] p-10 shadow-[0_24px_80px_rgba(120,67,52,0.12)]">
        <div className="flex items-center justify-between text-xs uppercase tracking-[0.24em] text-stone-500">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-[#C74634] px-3 py-2 font-semibold text-white">O</div>
            <span>Oracle</span>
          </div>
          <div className="flex items-center gap-6">
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-[11px] font-semibold tracking-normal text-emerald-700">Live Presentation</span>
            <span className="tracking-normal text-stone-500">Technical Session</span>
          </div>
        </div>

        <div className="mt-16 max-w-4xl">
          <h1 className="text-6xl font-semibold leading-[1.05] tracking-[-0.03em] text-stone-900">{slide.title}</h1>
          <p className="mt-5 text-2xl leading-relaxed text-stone-500">
            {lead || 'A consulting-grade architecture for polished presentation generation and enterprise delivery.'}
          </p>
        </div>
        <div className="mt-auto flex items-end justify-between pt-10 text-sm text-stone-500">
          <div>
            <div className="font-medium text-stone-800">[Presenter Name]</div>
            <div>{audience || 'Senior Technical Consultant'}</div>
          </div>
          <div className="text-right">
            <div>{deckTitle || 'Auto-PPT'}</div>
            <div>{new Date().toLocaleDateString()}</div>
          </div>
        </div>
      </div>
    )
  }

  if (slide.template_id === 'exec.summary') {
    const leftSummary = textBlocks[0] ?? 'Executive summary'
    const insight = textBlocks[1] ?? 'Outline-first, template-driven systems improve polish, speed, and governance.'
    const footer = `${cards.length || 3} summary cards`
    return (
      <div className="flex h-full flex-col rounded-[28px] border border-stone-200 bg-white p-8 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
        <div className="flex items-center justify-between border-b border-stone-200 pb-5">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-[#C74634] px-3 py-2 font-semibold text-white">O</div>
            <span className="font-medium text-stone-800">Oracle</span>
          </div>
          <div className="flex items-center gap-6 text-sm text-stone-500">
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-[11px] font-semibold text-emerald-700">Live Presentation</span>
            <span>Technical Session</span>
          </div>
        </div>

        <div className="mt-7 grid min-h-0 flex-1 grid-cols-[1.1fr_1.6fr] gap-8">
          <div className="flex flex-col">
            <h2 className="text-4xl font-semibold tracking-[-0.02em] text-stone-900">{slide.title}</h2>
            <p className="mt-6 text-xl leading-relaxed text-stone-600">{leftSummary}</p>
            <div className="mt-8 rounded-2xl border border-[#E8C6BF] bg-[#FFF7F4] p-5">
              <div className="text-sm font-semibold text-[#B9432F]">Key insight</div>
              <div className="mt-2 text-lg leading-relaxed text-stone-900">{insight}</div>
            </div>
            <div className="mt-auto flex gap-6 pt-8 text-sm text-stone-500">
              <span>{footer}</span>
              <span>{cards.length || 3} cards</span>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4">
            {(cards.length > 0 ? cards : Array.from({ length: 3 }, (_, index) => ({ title: `Point ${index + 1}`, text: 'Add consulting-style detail' }))).slice(0, 3).map((card, index) => (
              <div key={`${card.title}-${index}`} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-[0_10px_24px_rgba(15,23,42,0.05)]">
                <div className="text-sm font-semibold text-stone-900">{card.title}</div>
                <div className="mt-2 text-sm leading-6 text-stone-600">{card.text}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  if (slide.template_id === 'compare.2col') {
    return (
      <div className="flex h-full flex-col rounded-[28px] border border-stone-200 bg-white p-8 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-stone-400">Comparison</div>
            <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em] text-stone-900">{slide.title}</h2>
            <p className="mt-4 max-w-3xl text-lg leading-relaxed text-stone-600">
              {lead || 'Compare two perspectives, options, or decision criteria side by side.'}
            </p>
          </div>
          <div className="rounded-full bg-stone-100 px-4 py-2 text-sm font-medium text-stone-600">2 columns</div>
        </div>
        <div className="mt-8 grid flex-1 grid-cols-2 gap-4">
          {textBlocks.slice(0, 2).map((text, index) => (
            <div key={index} className="rounded-3xl border border-stone-200 bg-[linear-gradient(180deg,_#fff_0%,_#fafaf9_100%)] p-5 shadow-[0_10px_24px_rgba(15,23,42,0.05)]">
              <div className="text-sm font-semibold text-stone-900">{index === 0 ? 'Perspective A' : 'Perspective B'}</div>
              <div className="mt-3 text-sm leading-6 text-stone-600">{text}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (slide.template_id === 'closing.actions') {
    return (
      <div className="flex h-full flex-col rounded-[28px] border border-stone-200 bg-white p-10 shadow-[0_20px_60px_rgba(15,23,42,0.08)]">
        <div className="text-xs uppercase tracking-[0.24em] text-stone-400">Closing</div>
        <h2 className="mt-3 text-5xl font-semibold tracking-[-0.03em] text-stone-900">{slide.title}</h2>
        <div className="mt-10 grid gap-4">
          {textBlocks
            .flatMap((text) => text.split('\n'))
            .map((item) => item.replace(/^[\u2022*-]\s*/, '').trim())
            .filter(Boolean)
            .slice(0, 6)
            .map((item, index) => (
              <div key={`${item}-${index}`} className="flex items-center gap-5 rounded-2xl border border-stone-200 bg-stone-50 px-5 py-4">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#C74634] text-sm font-semibold text-white">
                  {index + 1}
                </div>
                <div className="text-lg text-stone-800">{item}</div>
              </div>
            ))}
        </div>
      </div>
    )
  }

  if (slide.template_id === 'headline.evidence' || slide.template_id === 'kpi.big' || slide.template_id === 'chart.takeaway') {
    const isKpi = slide.template_id === 'kpi.big'
    const cols = isKpi ? 3 : 1
    const colsClass = cols === 3 ? 'grid-cols-3' : cols === 2 ? 'grid-cols-2' : 'grid-cols-1'
    return (
      <div className="flex h-full flex-col rounded-[28px] border border-stone-200 bg-white p-8 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-stone-400">{slide.template_id}</div>
            <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em] text-stone-900">{slide.title}</h2>
            {lead ? <p className="mt-4 max-w-3xl text-lg leading-relaxed text-stone-600">{lead}</p> : null}
          </div>
          <div className="rounded-full bg-stone-100 px-4 py-2 text-sm font-medium capitalize text-stone-600">{slide.purpose}</div>
        </div>
        {cards.length > 0 ? (
          <div className={`mt-8 grid flex-1 ${colsClass} gap-5`}>
            {cards.map((card, index) => (
              <div key={`${card.title}-${index}`} className="rounded-2xl border border-stone-200 bg-[linear-gradient(180deg,_#fff_0%,_#fafaf9_100%)] p-6 shadow-[0_10px_24px_rgba(15,23,42,0.05)]">
                <div className="text-base font-semibold text-stone-900">{card.title}</div>
                <div className="mt-2 text-sm leading-6 text-stone-600">{card.text}</div>
              </div>
            ))}
          </div>
        ) : kpis.length > 0 ? (
          <div className="mt-8 grid flex-1 grid-cols-3 gap-5">
            {kpis.map((item, index) => (
              <div key={`${item.label}-${index}`} className="flex flex-col items-center justify-center rounded-3xl border border-stone-200 bg-white p-6 shadow-[0_10px_24px_rgba(15,23,42,0.05)]">
                <div className="text-4xl font-semibold text-stone-900">{item.value}</div>
                <div className="mt-2 text-sm text-stone-500">{item.label}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-8 min-h-0 flex-1 space-y-4">
            {textBlocks.slice(1).map((text, index) => (
              <div key={index} className="rounded-2xl border border-stone-200 bg-white p-5 text-base leading-relaxed text-stone-700">{text}</div>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col rounded-[28px] border border-stone-200 bg-white p-8 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-stone-400">{slide.template_id}</div>
          <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em] text-stone-900">{slide.title}</h2>
        </div>
        <div className="rounded-full bg-stone-100 px-4 py-2 text-sm font-medium capitalize text-stone-600">{slide.purpose}</div>
      </div>
      <div className="mt-8 min-h-0 flex-1">
        <div className="grid h-full gap-4 auto-rows-fr" style={{ gridTemplateColumns: `repeat(${Math.min(slide.blocks.length, 3)}, 1fr)` }}>
          {slide.blocks.map((block) => (
            <div key={block.id} className="min-h-0">
              <BlockRenderer block={block} mode="preview" onChange={() => {}} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export function SlideCanvas({
  slide,
  templates,
  previewSlide,
  deckTitle,
  audience,
  themeName,
  promptText,
  onPromptTextChange,
  onSlideTypeChange,
  onGeneratePreview,
  previewLoading = false,
}: SlideCanvasProps) {
  return (
    <div className="flex-1 p-6">
      <div className="space-y-6">
        <div className="rounded-[32px] border border-slate-200 bg-white p-8 shadow-panel">
          <div className="mb-3 text-xs uppercase tracking-[0.24em] text-slate-400">Slide Prompt</div>
          <textarea
            value={promptText}
            onChange={(event) => onPromptTextChange(event.target.value)}
            className="min-h-36 w-full resize-y rounded-2xl border border-slate-200 bg-white p-4 text-base leading-7 text-slate-900 outline-none"
          />
        </div>

        <div className="rounded-[32px] border border-slate-200 bg-white p-8 shadow-panel">
          <div className="mb-4 flex items-center justify-between gap-4">
            <div className="text-xs uppercase tracking-[0.24em] text-slate-400">Slide Preview</div>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <span>Slide type</span>
                <select
                  value={slide.template_id}
                  onChange={(event) => onSlideTypeChange(event.target.value)}
                  className="rounded-lg border border-slate-200 px-3 py-2"
                >
                  {templates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="text-xs text-slate-500">{themeName || 'Default'}</div>
              <button
                type="button"
                onClick={onGeneratePreview}
                disabled={previewLoading}
                className="rounded-full border border-slate-200 bg-slate-950 px-4 py-2 text-sm font-medium text-white"
              >
                {previewLoading ? 'Generating...' : 'Generate preview'}
              </button>
            </div>
          </div>
          <div className="mx-auto aspect-[16/9] w-full max-w-6xl overflow-hidden rounded-[28px] bg-[#F8F6F3] p-6 shadow-inner">
            <SlidePreviewSurface slide={previewSlide ?? slide} deckTitle={deckTitle} audience={audience} />
          </div>
        </div>
      </div>
    </div>
  )
}
