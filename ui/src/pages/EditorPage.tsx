import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { exportDeck, generateSlidePreview, getTemplates } from '../api/client'
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
  const [selectedThemeName, setSelectedThemeName] = useState<'ONAC'>('ONAC')
  const currentDeck = useDeckStore((state) => state.currentDeck)
  const loadDeck = useDeckStore((state) => state.loadDeck)
  const updateSlide = useDeckStore((state) => state.updateSlide)
  const replaceSlide = useDeckStore((state) => state.replaceSlide)
  const addSlide = useDeckStore((state) => state.addSlide)
  const deleteSlide = useDeckStore((state) => state.deleteSlide)
  const duplicateSlide = useDeckStore((state) => state.duplicateSlide)
  const moveSlide = useDeckStore((state) => state.moveSlide)
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
        deck_id: currentDeck.id,
      })
      setPreviewSlide(preview)
      replaceSlide(selectedSlideIndex, { ...preview, index: slide.index })
      ui.addToast('Slide preview generated with consulting-style copy.', 'success')
    } catch (error) {
      ui.addToast(error instanceof Error ? error.message : 'Slide preview failed', 'error')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleDeckExport(format: 'pdf' | 'pptx') {
    if (!currentDeck) return
    try {
      const result = await exportDeck(currentDeck.id, format, currentDeck.slides)
      const url = URL.createObjectURL(result.blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${currentDeck.id}.${format}`
      anchor.click()
      URL.revokeObjectURL(url)
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
      <SlideRail
        slides={currentDeck.slides}
        selectedSlideIndex={selectedSlideIndex}
        onSelect={setSelectedSlide}
        onAddSlide={addSlide}
        onDeleteSlide={deleteSlide}
        onDuplicateSlide={duplicateSlide}
        onMoveSlide={moveSlide}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-6 py-4 text-sm">
          <Link to="/" className="text-slate-600">
            {'<- Back to decks'}
          </Link>
          <span className="text-slate-300">|</span>
          <label className="flex items-center gap-2">
            <span>Theme:</span>
            <select
              value={selectedThemeName}
              onChange={(event) => setSelectedThemeName(event.target.value as 'ONAC')}
              className="rounded-lg border border-slate-200 px-3 py-2"
            >
              <option value="ONAC">ONAC</option>
            </select>
          </label>
          <button type="button" className="text-slate-600" onClick={() => ui.addToast('Layout controls coming soon.')}>
            Layout
          </button>
          <span className="ml-auto" />
          <button type="button" className="text-slate-600" onClick={() => ui.addToast('Share is not wired yet.')}>
            Share
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void handleDeckExport('pdf')}
              className="rounded-xl border border-slate-200 px-4 py-2"
            >
              Export PDF
            </button>
            <button
              type="button"
              onClick={() => void handleDeckExport('pptx')}
              className="rounded-xl bg-slate-950 px-4 py-2 text-white"
            >
              Export PPTX
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1">
          <SlideCanvas
            slide={slide}
            templates={templates}
            previewSlide={previewSlide}
            deckTitle={currentDeck.title}
            audience={currentDeck.audience}
            themeName={selectedThemeName}
            promptText={promptText}
            onPromptTextChange={setPromptText}
            onSlideTypeChange={(templateId) => updateSlide(selectedSlideIndex, { template_id: templateId })}
            onGeneratePreview={handleGeneratePreview}
            onTitleChange={(title) => updateSlide(selectedSlideIndex, { title })}
            onSpeakerNotesChange={(notes) => updateSlide(selectedSlideIndex, { speaker_notes: notes })}
            previewLoading={previewLoading}
          />
        </div>
      </main>

    </div>
  )
}
