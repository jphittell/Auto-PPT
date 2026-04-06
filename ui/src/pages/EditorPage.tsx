import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { exportDeck, generateSlidePreview, getTemplates } from '../api/client'
import { ExportPreflightModal } from '../components/ExportPreflightModal'
import { SlideCanvas } from '../components/SlideCanvas'
import { SlideRail } from '../components/SlideRail'
import { useDeckStore } from '../store/deckStore'
import { useUIStore } from '../store/uiStore'
import type { SlideSpec, Template } from '../types'

export function EditorPage() {
  const { deckId } = useParams<{ deckId: string }>()
  const [templates, setTemplates] = useState<Template[]>([])
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewSlide, setPreviewSlide] = useState<SlideSpec | null>(null)
  const [promptText, setPromptText] = useState('')
  const currentDeck = useDeckStore((state) => state.currentDeck)
  const loadDeck = useDeckStore((state) => state.loadDeck)
  const updateSlide = useDeckStore((state) => state.updateSlide)
  const addSlide = useDeckStore((state) => state.addSlide)
  const selectedSlideIndex = useDeckStore((state) => state.selectedSlideIndex)
  const setSelectedSlide = useDeckStore((state) => state.setSelectedSlide)
  const ui = useUIStore()

  useEffect(() => {
    if (deckId) void loadDeck(deckId)
  }, [deckId, loadDeck])

  useEffect(() => {
    getTemplates().then(setTemplates).catch(() => setTemplates([]))
  }, [])

  const slide = currentDeck?.slides[selectedSlideIndex] ?? null
  const imageIssueCount = useMemo(
    () => currentDeck?.slides.flatMap((item) => item.blocks).filter((block) => block.kind === 'image').length ?? 0,
    [currentDeck],
  )

  useEffect(() => {
    setPreviewSlide(null)
  }, [currentDeck?.id, selectedSlideIndex, slide?.template_id])

  useEffect(() => {
    if (!slide) {
      setPromptText('')
      return
    }
    setPromptText(slide.blocks.map((block) => block.content.trim()).filter(Boolean).join('\n\n'))
  }, [slide])

  async function handleGeneratePreview() {
    if (!slide || !currentDeck) return
    const content = promptText.trim()
    if (!content) {
      ui.addToast('Add slide text before generating a preview.', 'info')
      return
    }

    try {
      setPreviewLoading(true)
      const preview = await generateSlidePreview({
        slide_id: slide.id,
        title: slide.title,
        purpose: slide.purpose,
        template_id: slide.template_id,
        content,
        audience: currentDeck.audience,
        goal: currentDeck.goal,
      })
      setPreviewSlide(preview)
      // Update the slide's template if the pipeline chose a better one
      if (preview.template_id && preview.template_id !== slide.template_id) {
        updateSlide(selectedSlideIndex, { template_id: preview.template_id })
      }
      ui.addToast('Slide preview generated with consulting-style copy.', 'success')
    } catch (error) {
      ui.addToast(error instanceof Error ? error.message : 'Slide preview failed', 'error')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handlePdfExport() {
    await handleDeckExport('pdf')
  }

  async function handlePptxExport() {
    await handleDeckExport('pptx')
  }

  async function handleDeckExport(format: 'pdf' | 'pptx') {
    if (!currentDeck) return
    try {
      const result = await exportDeck(currentDeck.id, format)
      const url = URL.createObjectURL(result.blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${currentDeck.id}.${format}`
      anchor.click()
      URL.revokeObjectURL(url)
      ui.setPreflightModalOpen(false)
      ui.addToast(`${format.toUpperCase()} exported.`, 'success')
    } catch (error) {
      ui.addToast(error instanceof Error ? error.message : `${format.toUpperCase()} export failed`, 'error')
    }
  }

  if (!currentDeck || !slide) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="text-slate-500">Loading deck...</div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <SlideRail slides={currentDeck.slides} selectedSlideIndex={selectedSlideIndex} onSelect={setSelectedSlide} onAddSlide={addSlide} />

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-6 py-4 text-sm">
          <Link to="/" className="text-slate-600">
            {'<- Back to decks'}
          </Link>
          <span className="text-slate-300">|</span>
          <label className="flex items-center gap-2">
            <span>Theme:</span>
            <select
              value={slide.template_id}
              onChange={(event) => updateSlide(selectedSlideIndex, { template_id: event.target.value })}
              className="rounded-lg border border-slate-200 px-3 py-2"
            >
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="text-slate-600" onClick={() => ui.addToast('Layout controls coming soon.')}>
            Layout
          </button>
          <button type="button" className="text-slate-600" onClick={() => ui.addToast('Accessibility checks available in preflight.')}>
            Accessibility
          </button>
          <span className="ml-auto" />
          <button type="button" className="text-slate-600" onClick={() => ui.addToast('Share is not wired yet.')}>
            Share
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => ui.setPreflightModalOpen(true)}
              className="rounded-xl border border-slate-200 px-4 py-2"
            >
              Export PDF
            </button>
            <button
              type="button"
              onClick={() => void handlePptxExport()}
              className="rounded-xl bg-slate-950 px-4 py-2 text-white"
            >
              Export PPTX
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1">
          <SlideCanvas
            slide={slide}
            previewSlide={previewSlide}
            deckTitle={currentDeck.title}
            audience={currentDeck.audience}
            themeName={currentDeck.theme?.name}
            promptText={promptText}
            onPromptTextChange={setPromptText}
            onGeneratePreview={handleGeneratePreview}
            previewLoading={previewLoading}
          />
        </div>
      </main>

      <ExportPreflightModal
        open={ui.preflightModalOpen}
        imageIssueCount={imageIssueCount}
        onClose={() => ui.setPreflightModalOpen(false)}
        onContinue={handlePdfExport}
      />
    </div>
  )
}
