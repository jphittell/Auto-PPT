import type { Template, SlideSpec, ContentBlock } from '../types'

const ONAC_PREVIEW_THEME = {
  bg: '#2A2F2F',
  text: '#FFFFFF',
  accent: '#C74634',
  muted: '#89B2B0',
  teal: '#04536F',
  gold: '#F0CC71',
  softText: '#FBF9F8',
  panel: '#343B3B',
  panelBorder: '#4A5353',
}

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
  onTitleChange?: (title: string) => void
  onSpeakerNotesChange?: (notes: string) => void
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

function previewItems(slide: SlideSpec) {
  return previewPlainText(slide)
    .flatMap((text) => text.split('\n'))
    .map((item) => item.replace(/^[\u2022*-]\s*/, '').trim())
    .filter(Boolean)
}

function previewTableRows(slide: SlideSpec) {
  for (const block of slide.blocks) {
    const data = block.data
    if (!data || typeof data !== 'object' || !('rows' in data) || !Array.isArray(data.rows)) continue
    const rows = data.rows
      .map((row) => {
        if (Array.isArray(row)) {
          return row.map((cell) => (typeof cell === 'string' ? cell : String(cell ?? ''))).slice(0, 2)
        }
        if (row && typeof row === 'object') {
          const values = Object.values(row).map((cell) => (typeof cell === 'string' ? cell : String(cell ?? '')))
          return values.slice(0, 2)
        }
        return []
      })
      .filter((row) => row.length > 0)
    if (rows.length > 0) return rows
  }

  return previewItems(slide)
    .slice(0, 6)
    .map((item, index) => [`Topic ${index + 1}`, item])
}

export type PreviewColumn = { title: string; text: string; isPlaceholder?: boolean }

function previewColumns(slide: SlideSpec, count: number): PreviewColumn[] {
  const cards = previewCards(slide)
  if (cards.length > 0) {
    return cards.slice(0, count).map((card, index) => ({
      title: card.title || `Column ${index + 1}`,
      text: card.text || '',
      isPlaceholder: !card.title && !card.text,
    }))
  }

  const items = previewItems(slide)
  const plain = previewPlainText(slide)
  return Array.from({ length: count }, (_, index) => {
    const text = items[index] ?? plain[index] ?? ''
    return {
      title: text ? `Column ${index + 1}` : '',
      text,
      isPlaceholder: !text,
    }
  })
}

function PreviewImagePlaceholder({ label = 'Image', tall = false }: { label?: string; tall?: boolean }) {
  return (
    <div
      className={`flex h-full min-h-0 flex-col items-center justify-center rounded-2xl border border-dashed ${tall ? 'min-h-[18rem]' : 'min-h-[12rem]'} p-6 text-center shadow-[0_10px_24px_rgba(0,0,0,0.18)]`}
      style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}
    >
      <div
        className="flex h-12 w-12 items-center justify-center rounded-full border text-lg font-semibold"
        style={{ borderColor: ONAC_PREVIEW_THEME.muted, color: ONAC_PREVIEW_THEME.muted }}
      >
        +
      </div>
      <div className="mt-4 text-sm font-semibold uppercase tracking-[0.18em]" style={{ color: ONAC_PREVIEW_THEME.text }}>
        {label}
      </div>
      <div className="mt-2 text-sm leading-6" style={{ color: ONAC_PREVIEW_THEME.muted }}>
        Visual placeholder
      </div>
    </div>
  )
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
  const items = previewItems(slide)
  const lead = textBlocks[0] ?? ''

  if (slide.template_id === 'title.cover') {
    return (
      <div
        className="flex h-full flex-col rounded-[28px] border p-10 shadow-[0_24px_80px_rgba(0,0,0,0.28)]"
        style={{
          borderColor: ONAC_PREVIEW_THEME.panelBorder,
          background: `radial-gradient(circle at top, rgba(199,70,52,0.22), transparent 38%), linear-gradient(180deg, ${ONAC_PREVIEW_THEME.bg} 0%, #232828 100%)`,
        }}
      >
        <div className="flex items-center justify-between text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.muted }}>
          <div className="flex items-center gap-3">
            <div className="rounded-lg px-3 py-2 font-semibold text-white" style={{ backgroundColor: ONAC_PREVIEW_THEME.accent }}>O</div>
            <span>Oracle</span>
          </div>
          <div className="flex items-center gap-6">
            <span className="rounded-full px-3 py-1 text-[11px] font-semibold tracking-normal" style={{ backgroundColor: ONAC_PREVIEW_THEME.teal, color: ONAC_PREVIEW_THEME.softText }}>Live Presentation</span>
            <span className="tracking-normal" style={{ color: ONAC_PREVIEW_THEME.gold }}>Technical Session</span>
          </div>
        </div>

        <div className="mt-16 max-w-4xl">
          <h1 className="text-6xl font-semibold leading-[1.05] tracking-[-0.03em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h1>
          <p className="mt-5 text-2xl leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.muted }}>
            {lead || 'A consulting-grade architecture for polished presentation generation and enterprise delivery.'}
          </p>
        </div>
        <div className="mt-auto flex items-end justify-between pt-10 text-sm" style={{ color: ONAC_PREVIEW_THEME.muted }}>
          <div>
            <div className="font-medium" style={{ color: ONAC_PREVIEW_THEME.text }}>[Presenter Name]</div>
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
      <div className="flex h-full flex-col rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="flex items-center justify-between border-b pb-5" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder }}>
          <div className="flex items-center gap-3">
            <div className="rounded-lg px-3 py-2 font-semibold text-white" style={{ backgroundColor: ONAC_PREVIEW_THEME.accent }}>O</div>
            <span className="font-medium" style={{ color: ONAC_PREVIEW_THEME.text }}>Oracle</span>
          </div>
          <div className="flex items-center gap-6 text-sm" style={{ color: ONAC_PREVIEW_THEME.muted }}>
            <span className="rounded-full px-3 py-1 text-[11px] font-semibold" style={{ backgroundColor: ONAC_PREVIEW_THEME.teal, color: ONAC_PREVIEW_THEME.softText }}>Live Presentation</span>
            <span>Technical Session</span>
          </div>
        </div>

        <div className="mt-7 grid min-h-0 flex-1 grid-cols-[1.1fr_1.6fr] gap-8">
          <div className="flex min-h-0 flex-col overflow-hidden">
            <h2 className="text-4xl font-semibold tracking-[-0.02em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
            <p className="mt-6 text-xl leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.muted }}>{leftSummary}</p>
            <div className="mt-8 rounded-2xl border p-5" style={{ borderColor: ONAC_PREVIEW_THEME.accent, backgroundColor: '#364040' }}>
              <div className="text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.accent }}>Key insight</div>
              <div className="mt-2 text-lg leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.text }}>{insight}</div>
            </div>
            <div className="mt-auto flex gap-6 pt-8 text-sm" style={{ color: ONAC_PREVIEW_THEME.muted }}>
              <span>{footer}</span>
              <span>{cards.length} cards</span>
            </div>
          </div>

          <div className="grid min-h-0 auto-rows-fr grid-cols-1 gap-4">
            {cards.length > 0 ? (
              cards.slice(0, 3).map((card, index) => (
                <div key={`${card.title}-${index}`} className="rounded-2xl border p-5 shadow-[0_10px_24px_rgba(0,0,0,0.18)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
                  <div className="text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{card.title}</div>
                  <div className="mt-2 text-sm leading-6" style={{ color: ONAC_PREVIEW_THEME.muted }}>{card.text}</div>
                </div>
              ))
            ) : (
              <div
                className="flex min-h-[12rem] flex-col items-center justify-center rounded-2xl border border-dashed p-8 text-center"
                style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, color: ONAC_PREVIEW_THEME.muted }}
              >
                <div className="text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>
                  No supporting points yet
                </div>
                <div className="mt-2 text-xs leading-5">
                  Add slide text or regenerate with a source document to populate summary cards.
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (slide.template_id === 'compare.2col') {
    return (
      <div className="flex h-full flex-col rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>Comparison</div>
            <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
            <p className="mt-4 max-w-3xl text-lg leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.muted }}>
              {lead || 'Compare two perspectives, options, or decision criteria side by side.'}
            </p>
          </div>
          <div className="rounded-full px-4 py-2 text-sm font-medium" style={{ backgroundColor: ONAC_PREVIEW_THEME.teal, color: ONAC_PREVIEW_THEME.softText }}>2 columns</div>
        </div>
        <div className="mt-8 grid flex-1 grid-cols-2 gap-4">
          {textBlocks.slice(0, 2).map((text, index) => (
            <div key={index} className="rounded-3xl border p-5 shadow-[0_10px_24px_rgba(0,0,0,0.18)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
              <div className="text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{index === 0 ? 'Perspective A' : 'Perspective B'}</div>
              <div className="mt-3 text-sm leading-6" style={{ color: ONAC_PREVIEW_THEME.muted }}>{text}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (slide.template_id === 'closing.actions') {
    return (
      <div className="flex h-full flex-col rounded-[28px] border p-10 shadow-[0_20px_60px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>Closing</div>
        <h2 className="mt-3 text-5xl font-semibold tracking-[-0.03em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
        <div className="mt-10 grid gap-4">
          {textBlocks
            .flatMap((text) => text.split('\n'))
            .map((item) => item.replace(/^[\u2022*-]\s*/, '').trim())
            .filter(Boolean)
            .slice(0, 6)
            .map((item, index) => (
              <div key={`${item}-${index}`} className="flex items-center gap-5 rounded-2xl border px-5 py-4" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
                <div className="flex h-9 w-9 items-center justify-center rounded-full text-sm font-semibold text-white" style={{ backgroundColor: ONAC_PREVIEW_THEME.accent }}>
                  {index + 1}
                </div>
                <div className="text-lg" style={{ color: ONAC_PREVIEW_THEME.text }}>{item}</div>
              </div>
            ))}
        </div>
      </div>
    )
  }

  if (slide.template_id === 'section.divider') {
    return (
      <div
        className="flex h-full flex-col items-center justify-center rounded-[28px] border px-12 text-center shadow-[0_24px_80px_rgba(0,0,0,0.28)]"
        style={{
          borderColor: ONAC_PREVIEW_THEME.panelBorder,
          background: `linear-gradient(180deg, ${ONAC_PREVIEW_THEME.bg} 0%, #232828 100%)`,
        }}
      >
        <div className="h-1 w-28 rounded-full" style={{ backgroundColor: ONAC_PREVIEW_THEME.accent }} />
        <h2 className="mt-10 text-6xl font-semibold tracking-[-0.03em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>
          {slide.title}
        </h2>
        <p className="mt-6 max-w-3xl text-2xl leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.muted }}>
          {lead || audience || deckTitle || 'Transition to the next chapter'}
        </p>
      </div>
    )
  }

  if (slide.template_id === 'quote.photo') {
    const attribution = textBlocks[1] ?? slide.title
    return (
      <div className="grid h-full grid-cols-[1.2fr_0.8fr] gap-6 rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="flex min-h-0 flex-col justify-center rounded-2xl border p-8" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
          <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>Quote</div>
          <div className="mt-6 text-4xl italic leading-[1.25]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>
            "{lead || 'Orchestrator of deterministic tools'}"
          </div>
          <div className="mt-8 text-base" style={{ color: ONAC_PREVIEW_THEME.muted }}>
            {attribution}
          </div>
        </div>
        <PreviewImagePlaceholder label="Photo" tall />
      </div>
    )
  }

  if (slide.template_id === 'quote.texture') {
    return (
      <div
        className="relative flex h-full flex-col items-center justify-center overflow-hidden rounded-[28px] border px-16 text-center shadow-[0_24px_80px_rgba(0,0,0,0.28)]"
        style={{
          borderColor: ONAC_PREVIEW_THEME.panelBorder,
          background: `radial-gradient(circle at 20% 20%, rgba(240,204,113,0.14), transparent 22%), radial-gradient(circle at 80% 75%, rgba(4,83,111,0.18), transparent 24%), linear-gradient(180deg, ${ONAC_PREVIEW_THEME.bg} 0%, #232828 100%)`,
        }}
      >
        <div className="absolute left-10 top-10 h-20 w-20 rounded-full border" style={{ borderColor: 'rgba(137,178,176,0.35)' }} />
        <div className="absolute bottom-10 right-10 h-24 w-24 rounded-full border" style={{ borderColor: 'rgba(199,70,52,0.28)' }} />
        <div className="text-6xl leading-none" style={{ color: ONAC_PREVIEW_THEME.accent, fontFamily: 'Georgia, serif' }}>
          “
        </div>
        <div className="mt-4 max-w-4xl text-5xl italic leading-[1.2]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>
          {lead || slide.title}
        </div>
      </div>
    )
  }

  if (slide.template_id === 'impact.statement') {
    return (
      <div className="flex h-full flex-col items-center justify-center rounded-[28px] border px-16 text-center shadow-[0_24px_80px_rgba(0,0,0,0.28)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="max-w-5xl text-6xl font-semibold leading-[1.08] tracking-[-0.04em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>
          {lead || slide.title}
        </div>
        <div className="mt-8 h-1 w-40 rounded-full" style={{ backgroundColor: ONAC_PREVIEW_THEME.accent }} />
      </div>
    )
  }

  if (slide.template_id === 'content.3col' || slide.template_id === 'content.4col') {
    const columnCount = slide.template_id === 'content.4col' ? 4 : 3
    const columns = previewColumns(slide, columnCount)
    return (
      <div className="flex h-full flex-col rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div>
          <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>{slide.template_id === 'content.4col' ? 'Four-column layout' : 'Three-column layout'}</div>
          <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
          {lead ? <p className="mt-4 text-lg leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.muted }}>{lead}</p> : null}
        </div>
        <div className={`mt-8 grid min-h-0 flex-1 gap-4 ${columnCount === 4 ? 'grid-cols-4' : 'grid-cols-3'}`}>
          {columns.map((column, index) => (
            <div
              key={`${column.title || 'empty'}-${index}`}
              className={`rounded-2xl border p-5 ${column.isPlaceholder ? 'border-dashed' : 'shadow-[0_10px_24px_rgba(0,0,0,0.18)]'}`}
              style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: column.isPlaceholder ? 'transparent' : ONAC_PREVIEW_THEME.panel }}
            >
              {column.isPlaceholder ? (
                <div className="text-xs uppercase tracking-[0.18em]" style={{ color: ONAC_PREVIEW_THEME.muted }}>
                  Column {index + 1} — add content
                </div>
              ) : (
                <>
                  <div className="text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{column.title}</div>
                  <div className="mt-3 text-sm leading-6" style={{ color: ONAC_PREVIEW_THEME.muted }}>{column.text}</div>
                </>
              )}
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (slide.template_id === 'icons.3' || slide.template_id === 'icons.4') {
    const iconCount = slide.template_id === 'icons.4' ? 4 : 3
    const iconCards = previewColumns(slide, iconCount)
    return (
      <div className="flex h-full flex-col rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div>
          <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>{slide.template_id === 'icons.4' ? 'Four icon cards' : 'Three icon cards'}</div>
          <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
        </div>
        <div className={`mt-8 grid min-h-0 flex-1 gap-4 ${iconCount === 4 ? 'grid-cols-4' : 'grid-cols-3'}`}>
          {iconCards.map((card, index) => (
            <div
              key={`${card.title || 'empty'}-${index}`}
              className={`flex min-h-0 flex-col rounded-2xl border p-5 ${card.isPlaceholder ? 'border-dashed' : 'shadow-[0_10px_24px_rgba(0,0,0,0.18)]'}`}
              style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: card.isPlaceholder ? 'transparent' : ONAC_PREVIEW_THEME.panel }}
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-full text-lg font-semibold" style={{ backgroundColor: ONAC_PREVIEW_THEME.teal, color: ONAC_PREVIEW_THEME.softText }}>
                {index + 1}
              </div>
              {card.isPlaceholder ? (
                <div className="mt-4 text-xs uppercase tracking-[0.18em]" style={{ color: ONAC_PREVIEW_THEME.muted }}>
                  Add content
                </div>
              ) : (
                <>
                  <div className="mt-4 text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{card.title}</div>
                  <div className="mt-3 text-sm leading-6" style={{ color: ONAC_PREVIEW_THEME.muted }}>{card.text}</div>
                </>
              )}
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (slide.template_id === 'content.photo') {
    return (
      <div className="grid h-full grid-cols-[1.35fr_0.75fr] gap-6 rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="flex min-h-0 flex-col">
          <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>Content with photo</div>
          <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
          {lead ? <p className="mt-4 text-lg leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.muted }}>{lead}</p> : null}
          <div className="mt-8 space-y-3">
            {(items.length > 0 ? items : textBlocks.slice(1)).slice(0, 5).map((item, index) => (
              <div key={`${item}-${index}`} className="rounded-2xl border px-4 py-3" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
                <div className="text-sm leading-6" style={{ color: ONAC_PREVIEW_THEME.text }}>{item}</div>
              </div>
            ))}
          </div>
        </div>
        <PreviewImagePlaceholder label="Image" tall />
      </div>
    )
  }

  if (slide.template_id === 'bold.photo') {
    return (
      <div className="grid h-full grid-cols-2 gap-0 overflow-hidden rounded-[28px] border shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="flex flex-col justify-center p-10" style={{ backgroundColor: ONAC_PREVIEW_THEME.bg }}>
          <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>Bold statement</div>
          <div className="mt-6 text-5xl font-semibold leading-[1.1] tracking-[-0.03em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>
            {lead || slide.title}
          </div>
        </div>
        <div className="p-6" style={{ backgroundColor: '#313838' }}>
          <PreviewImagePlaceholder label="Photo" tall />
        </div>
      </div>
    )
  }

  if (slide.template_id === 'split.content') {
    const leftText = textBlocks[0] ?? 'Left-side framing'
    const rightText = textBlocks[1] ?? textBlocks[2] ?? 'Right-side framing'
    return (
      <div className="flex h-full flex-col rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>Split content</div>
        <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
        <div className="mt-8 grid min-h-0 flex-1 grid-cols-[1fr_auto_1fr] gap-6">
          <div className="rounded-2xl border p-6" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
            <div className="text-sm leading-7" style={{ color: ONAC_PREVIEW_THEME.text }}>{leftText}</div>
          </div>
          <div className="w-px rounded-full" style={{ backgroundColor: ONAC_PREVIEW_THEME.accent }} />
          <div className="rounded-2xl border p-6" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
            <div className="text-sm leading-7" style={{ color: ONAC_PREVIEW_THEME.text }}>{rightText}</div>
          </div>
        </div>
      </div>
    )
  }

  if (slide.template_id === 'agenda.table') {
    const rows = previewTableRows(slide)
    return (
      <div className="flex h-full flex-col rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>Agenda table</div>
        <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
        <div className="mt-8 overflow-hidden rounded-2xl border" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder }}>
          <div className="grid grid-cols-[0.7fr_1.3fr] border-b px-5 py-3 text-xs font-semibold uppercase tracking-[0.18em]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: '#3A4444', color: ONAC_PREVIEW_THEME.gold }}>
            <div>Section</div>
            <div>Focus</div>
          </div>
          <div className="divide-y" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder }}>
            {rows.slice(0, 5).map((row, index) => (
              <div key={`${row[0]}-${index}`} className="grid grid-cols-[0.7fr_1.3fr] px-5 py-4" style={{ backgroundColor: index % 2 === 0 ? ONAC_PREVIEW_THEME.panel : '#2F3636' }}>
                <div className="text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{row[0]}</div>
                <div className="text-sm leading-6" style={{ color: ONAC_PREVIEW_THEME.muted }}>{row[1] ?? ''}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  if (slide.template_id === 'screenshot') {
    return (
      <div className="flex h-full flex-col rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>Screenshot</div>
        <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
        {lead ? <p className="mt-4 text-lg leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.muted }}>{lead}</p> : null}
        <div className="mt-8 min-h-0 flex-1 rounded-[24px] border p-6" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
          <div className="flex h-full min-h-[20rem] flex-col rounded-[20px] border" style={{ borderColor: '#596262', backgroundColor: '#222727' }}>
            <div className="flex items-center gap-2 border-b px-4 py-3" style={{ borderColor: '#596262' }}>
              <div className="h-3 w-3 rounded-full" style={{ backgroundColor: ONAC_PREVIEW_THEME.accent }} />
              <div className="h-3 w-3 rounded-full" style={{ backgroundColor: ONAC_PREVIEW_THEME.gold }} />
              <div className="h-3 w-3 rounded-full" style={{ backgroundColor: ONAC_PREVIEW_THEME.teal }} />
            </div>
            <div className="flex flex-1 items-center justify-center p-6">
              <PreviewImagePlaceholder label="Screenshot" tall />
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (slide.template_id === 'headline.evidence' || slide.template_id === 'kpi.big' || slide.template_id === 'chart.takeaway') {
    const isKpi = slide.template_id === 'kpi.big'
    const cols = isKpi ? 3 : cards.length > 3 ? 2 : 1
    const colsClass = cols === 3 ? 'grid-cols-3' : cols === 2 ? 'grid-cols-2' : 'grid-cols-1'
    return (
      <div className="flex h-full flex-col rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>{slide.template_id}</div>
            <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
            {lead ? <p className="mt-4 max-w-3xl text-lg leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.muted }}>{lead}</p> : null}
          </div>
          <div className="rounded-full px-4 py-2 text-sm font-medium capitalize" style={{ backgroundColor: ONAC_PREVIEW_THEME.teal, color: ONAC_PREVIEW_THEME.softText }}>{slide.purpose}</div>
        </div>
        {cards.length > 0 ? (
          <div className={`mt-8 grid min-h-0 flex-1 auto-rows-fr ${colsClass} gap-5`}>
            {cards.map((card, index) => (
              <div key={`${card.title}-${index}`} className="rounded-2xl border p-6 shadow-[0_10px_24px_rgba(0,0,0,0.18)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
                <div className="text-base font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{card.title}</div>
                <div className="mt-2 text-sm leading-6" style={{ color: ONAC_PREVIEW_THEME.muted }}>{card.text}</div>
              </div>
            ))}
          </div>
        ) : kpis.length > 0 ? (
          <div className="mt-8 grid min-h-0 flex-1 auto-rows-fr grid-cols-3 gap-5">
            {kpis.map((item, index) => (
              <div key={`${item.label}-${index}`} className="flex flex-col items-center justify-center rounded-3xl border p-6 shadow-[0_10px_24px_rgba(0,0,0,0.18)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
                <div className="text-4xl font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{item.value}</div>
                <div className="mt-2 text-sm" style={{ color: ONAC_PREVIEW_THEME.muted }}>{item.label}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-8 min-h-0 flex-1 space-y-4">
            {textBlocks.slice(1).map((text, index) => (
              <div key={index} className="rounded-2xl border p-5 text-base leading-relaxed" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel, color: ONAC_PREVIEW_THEME.muted }}>{text}</div>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col rounded-[28px] border p-8 shadow-[0_24px_70px_rgba(0,0,0,0.24)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.bg }}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs uppercase tracking-[0.24em]" style={{ color: ONAC_PREVIEW_THEME.gold }}>{slide.template_id}</div>
          <h2 className="mt-3 text-4xl font-semibold tracking-[-0.02em]" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>{slide.title}</h2>
        </div>
        <div className="rounded-full px-4 py-2 text-sm font-medium capitalize" style={{ backgroundColor: ONAC_PREVIEW_THEME.teal, color: ONAC_PREVIEW_THEME.softText }}>{slide.purpose}</div>
      </div>
      <div className="mt-8 min-h-0 flex-1 space-y-4">
        {slide.blocks.map((block) => (
          <GenericBlockPreview key={block.id} block={block} />
        ))}
      </div>
    </div>
  )
}

function GenericBlockPreview({ block }: { block: ContentBlock }) {
  if (block.kind === 'bullets') {
    const items: string[] =
      block.data && typeof block.data === 'object' && 'items' in block.data && Array.isArray(block.data.items)
        ? block.data.items.filter((i): i is string => typeof i === 'string')
        : block.content.split('\n').map((s) => s.replace(/^[\u2022*-]\s*/, '').trim()).filter(Boolean)
    return (
      <div className="rounded-2xl border p-5" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
        <ul className="list-disc space-y-2 pl-5">
          {items.map((item, i) => (
            <li key={i} className="text-sm leading-6" style={{ color: ONAC_PREVIEW_THEME.muted }}>{item}</li>
          ))}
        </ul>
      </div>
    )
  }

  if (block.kind === 'callout') {
    const cards =
      block.data && typeof block.data === 'object' && 'cards' in block.data && Array.isArray(block.data.cards)
        ? (block.data.cards as Array<{ title?: string; text?: string }>)
        : null
    if (cards && cards.length > 0) {
      return (
        <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${Math.min(cards.length, 3)}, 1fr)` }}>
          {cards.map((card, i) => (
            <div key={i} className="rounded-2xl border p-4 shadow-[0_10px_24px_rgba(0,0,0,0.18)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
              <div className="text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{card.title ?? ''}</div>
              <div className="mt-2 text-sm" style={{ color: ONAC_PREVIEW_THEME.muted }}>{card.text ?? ''}</div>
            </div>
          ))}
        </div>
      )
    }
    return (
      <div className="rounded-2xl border-l-4 p-5" style={{ borderColor: ONAC_PREVIEW_THEME.accent, backgroundColor: '#364040' }}>
        <div className="text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.accent }}>Callout</div>
        <div className="mt-2 text-base leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.text }}>{block.content}</div>
      </div>
    )
  }

  if (block.kind === 'kpi_cards') {
    const items: Array<{ value: string; label: string }> =
      block.data && typeof block.data === 'object' && 'items' in block.data && Array.isArray(block.data.items)
        ? (block.data.items as Array<{ value?: string; label?: string }>).map((item) => ({
            value: typeof item.value === 'string' ? item.value : '',
            label: typeof item.label === 'string' ? item.label : '',
          }))
        : block.content.split('\n').filter(Boolean).map((line) => {
            const [value, label] = line.split('|')
            return { value: value ?? '', label: label ?? '' }
          })
    return (
      <div className="grid gap-4 grid-cols-3">
        {items.map((item, i) => (
          <div key={i} className="flex flex-col items-center justify-center rounded-3xl border p-6 shadow-[0_10px_24px_rgba(0,0,0,0.18)]" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
            <div className="text-4xl font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{item.value}</div>
            <div className="mt-2 text-sm" style={{ color: ONAC_PREVIEW_THEME.muted }}>{item.label}</div>
          </div>
        ))}
      </div>
    )
  }

  if (block.kind === 'timeline') {
    const items: Array<{ label?: string; title?: string; date?: string; description?: string }> =
      (block.data as any)?.items ?? []
    return (
      <div className="flex gap-3 overflow-x-auto py-2">
        {items.map((item, i) => (
          <div key={i} className="flex-1 min-w-0 rounded-xl border p-3" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
            {item.date && <div className="text-xs font-semibold mb-1" style={{ color: ONAC_PREVIEW_THEME.accent }}>{item.date}</div>}
            <div className="text-sm font-medium" style={{ color: ONAC_PREVIEW_THEME.text }}>{item.label ?? item.title ?? ''}</div>
            {item.description && <div className="text-xs mt-1" style={{ color: ONAC_PREVIEW_THEME.muted }}>{item.description}</div>}
          </div>
        ))}
      </div>
    )
  }

  if (block.kind === 'steps') {
    const steps: Array<{ number?: number; title?: string; description?: string }> =
      (block.data as any)?.steps ?? []
    return (
      <div className="flex gap-3 overflow-x-auto py-2">
        {steps.map((step, i) => (
          <div key={i} className="flex-1 min-w-0 rounded-xl border p-3" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
            <div className="text-xl font-bold mb-1" style={{ color: ONAC_PREVIEW_THEME.accent }}>{step.number ?? i + 1}</div>
            <div className="text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{step.title ?? ''}</div>
            {step.description && <div className="text-xs mt-1" style={{ color: ONAC_PREVIEW_THEME.muted }}>{step.description}</div>}
          </div>
        ))}
      </div>
    )
  }

  if (block.kind === 'people_cards') {
    const people: Array<{ name?: string; title?: string; bio?: string }> =
      (block.data as any)?.people ?? []
    return (
      <div className="flex gap-4 flex-wrap">
        {people.map((person, i) => (
          <div key={i} className="flex-1 min-w-[120px] rounded-xl border p-4 text-center" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
            <div className="w-12 h-12 rounded-full mx-auto mb-2 flex items-center justify-center text-lg font-bold" style={{ backgroundColor: ONAC_PREVIEW_THEME.accent, color: '#fff' }}>
              {(person.name ?? '?')[0]}
            </div>
            <div className="text-sm font-semibold" style={{ color: ONAC_PREVIEW_THEME.text }}>{person.name ?? ''}</div>
            <div className="text-xs mt-0.5" style={{ color: ONAC_PREVIEW_THEME.muted }}>{person.title ?? ''}</div>
            {person.bio && <div className="text-xs mt-1" style={{ color: ONAC_PREVIEW_THEME.muted }}>{person.bio}</div>}
          </div>
        ))}
      </div>
    )
  }

  if (block.kind === 'matrix') {
    const quadrants: Array<{ quadrant?: string; title?: string; items?: string[] }> =
      (block.data as any)?.quadrants ?? []
    return (
      <div className="grid grid-cols-2 gap-2 h-full">
        {quadrants.map((q, i) => (
          <div key={i} className="rounded-xl border p-3" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
            <div className="text-xs font-bold mb-1" style={{ color: ONAC_PREVIEW_THEME.accent }}>{q.title ?? q.quadrant ?? ''}</div>
            {(q.items ?? []).map((item, j) => (
              <div key={j} className="text-xs" style={{ color: ONAC_PREVIEW_THEME.muted }}>• {item}</div>
            ))}
          </div>
        ))}
      </div>
    )
  }

  if (block.kind === 'quote') {
    return (
      <div className="rounded-2xl border-l-4 p-5" style={{ borderColor: ONAC_PREVIEW_THEME.gold, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
        <div className="text-lg italic leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.text, fontFamily: 'Georgia, serif' }}>
          "{block.content}"
        </div>
      </div>
    )
  }

  if (block.kind === 'image') {
    return <PreviewImagePlaceholder label="Image" />
  }

  if (block.kind === 'table') {
    const rows: string[][] =
      block.data && typeof block.data === 'object' && 'rows' in block.data && Array.isArray(block.data.rows)
        ? (block.data.rows as unknown[][]).map((row) =>
            Array.isArray(row) ? row.map((cell) => String(cell ?? '')) : [String(row ?? '')]
          )
        : block.content.split('\n').filter(Boolean).map((line) => line.split('|').map((s) => s.trim()))
    return (
      <div className="overflow-hidden rounded-2xl border" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder }}>
        {rows.map((row, i) => (
          <div key={i} className="grid px-5 py-3" style={{ gridTemplateColumns: `repeat(${Math.max(row.length, 1)}, 1fr)`, backgroundColor: i % 2 === 0 ? ONAC_PREVIEW_THEME.panel : '#2F3636' }}>
            {row.map((cell, j) => (
              <div key={j} className="text-sm leading-6" style={{ color: i === 0 ? ONAC_PREVIEW_THEME.text : ONAC_PREVIEW_THEME.muted, fontWeight: i === 0 ? 600 : 400 }}>{cell}</div>
            ))}
          </div>
        ))}
      </div>
    )
  }

  // Default: text, chart, or unknown kind
  return (
    <div className="rounded-2xl border p-5" style={{ borderColor: ONAC_PREVIEW_THEME.panelBorder, backgroundColor: ONAC_PREVIEW_THEME.panel }}>
      <div className="text-base leading-relaxed" style={{ color: ONAC_PREVIEW_THEME.muted }}>{block.content}</div>
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
  onTitleChange,
  onSpeakerNotesChange,
  previewLoading = false,
}: SlideCanvasProps) {
  return (
    <div className="flex min-h-0 flex-1">
      {/* Main preview area */}
      <div className="flex min-w-0 flex-1 flex-col p-6">
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
              <div className="text-xs text-slate-500">{themeName || 'ONAC'}</div>
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
          <div className="mx-auto aspect-[16/9] w-full max-w-6xl overflow-hidden rounded-[28px] p-6 shadow-inner" style={{ backgroundColor: '#1E2323' }}>
            <SlidePreviewSurface slide={previewSlide ?? slide} deckTitle={deckTitle} audience={audience} />
          </div>
        </div>
      </div>

      {/* Right editing panel */}
      <div className="flex w-80 flex-col gap-4 overflow-y-auto border-l border-slate-200 bg-white p-5">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Slide title</div>
          <input
            type="text"
            value={slide.title}
            onChange={(e) => onTitleChange?.(e.target.value)}
            className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-900 outline-none focus:border-indigo-400"
          />
        </div>

        <div className="flex-1">
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Content</div>
          <textarea
            value={promptText}
            onChange={(event) => onPromptTextChange(event.target.value)}
            className="min-h-40 w-full resize-y rounded-xl border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-900 outline-none focus:border-indigo-400"
          />
        </div>

        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Speaker notes</div>
          <textarea
            value={slide.speaker_notes ?? ''}
            onChange={(e) => onSpeakerNotesChange?.(e.target.value)}
            placeholder="Add speaker notes..."
            className="min-h-24 w-full resize-y rounded-xl border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-700 outline-none focus:border-indigo-400"
          />
        </div>
      </div>
    </div>
  )
}
