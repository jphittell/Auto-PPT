import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { exportDeck, generateDeck, getTemplates } from '../api/client'
import { AISidepane } from '../components/AISidepane'
import { ExportPreflightModal } from '../components/ExportPreflightModal'
import { SlideCanvas } from '../components/SlideCanvas'
import { SlideRail } from '../components/SlideRail'
import { UpgradeModal } from '../components/UpgradeModal'
import { useDeckStore } from '../store/deckStore'
import { useUIStore } from '../store/uiStore'
import { useWizardStore } from '../store/wizardStore'
import type { Template } from '../types'

export function EditorPage() {
  const { deckId } = useParams<{ deckId: string }>()
  const [templates, setTemplates] = useState<Template[]>([])
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [history, setHistory] = useState<string[]>([])
  const currentDeck = useDeckStore((state) => state.currentDeck)
  const loadDeck = useDeckStore((state) => state.loadDeck)
  const updateSlide = useDeckStore((state) => state.updateSlide)
  const replaceSlide = useDeckStore((state) => state.replaceSlide)
  const insertSlideAfter = useDeckStore((state) => state.insertSlideAfter)
  const addSlide = useDeckStore((state) => state.addSlide)
  const selectedSlideIndex = useDeckStore((state) => state.selectedSlideIndex)
  const setSelectedSlide = useDeckStore((state) => state.setSelectedSlide)
  const ui = useUIStore()
  const brandKit = useWizardStore((state) => state.brandKit)

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

  async function runAiAction(action: string) {
    if (!currentDeck || !slide) return
    try {
      setActionLoading(action)
      const regenerated = await generateDeck({
        doc_id: currentDeck.doc_id,
        goal: `${currentDeck.goal} — ${action}`,
        audience: currentDeck.audience,
        tone: 50,
        slide_count: currentDeck.slides.length,
      })
      const nextSlide = regenerated.slides[Math.min(selectedSlideIndex, regenerated.slides.length - 1)]
      if (action === 'Add slide after this') {
        insertSlideAfter(selectedSlideIndex, {
          ...nextSlide,
          id: `${nextSlide.id}-${Date.now()}`,
          index: selectedSlideIndex + 2,
        })
      } else if (action === 'Regenerate layout') {
        const currentIndex = templates.findIndex((item) => item.id === slide.template_id)
        const selectedTemplate = templates[(currentIndex + 1) % Math.max(templates.length, 1)]
        updateSlide(selectedSlideIndex, { template_id: selectedTemplate?.id ?? slide.template_id })
      } else {
        replaceSlide(selectedSlideIndex, { ...nextSlide, id: slide.id, index: slide.index })
      }
      setHistory((entries) => [action, ...entries].slice(0, 3))
      ui.addToast(action, 'success')
    } catch (error) {
      ui.addToast(error instanceof Error ? error.message : 'AI action failed', 'error')
    } finally {
      setActionLoading(null)
    }
  }

  async function handlePdfExport() {
    if (!currentDeck) return
    try {
      const result = await exportDeck(currentDeck.id, 'pdf')
      if (result.type !== 'pdf') return
      const url = URL.createObjectURL(result.blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${currentDeck.id}.pdf`
      anchor.click()
      URL.revokeObjectURL(url)
      ui.setPreflightModalOpen(false)
      ui.addToast('PDF exported.', 'success')
    } catch (error) {
      ui.addToast(error instanceof Error ? error.message : 'PDF export failed', 'error')
    }
  }

  if (!currentDeck || !slide) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="text-slate-500">Loading deck…</div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <SlideRail slides={currentDeck.slides} selectedSlideIndex={selectedSlideIndex} onSelect={setSelectedSlide} onAddSlide={addSlide} />

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-6 py-4 text-sm">
          <Link to="/" className="text-slate-600">
            ← Back to decks
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
              onClick={() => ui.setUpgradeModalOpen(true)}
              className="rounded-xl bg-slate-950 px-4 py-2 text-white"
            >
              Export PPTX
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1">
          <SlideCanvas
            slide={slide}
            onTitleChange={(title) => updateSlide(selectedSlideIndex, { title })}
            onBlockChange={(blockIndex, content) => {
              const nextBlocks = slide.blocks.map((block, index) => (index === blockIndex ? { ...block, content } : block))
              updateSlide(selectedSlideIndex, { blocks: nextBlocks })
            }}
          />
          <AISidepane
            activeTab={ui.activeTab}
            onTabChange={ui.setActiveTab}
            sidepaneOpen={ui.sidepaneOpen}
            onToggle={ui.toggleSidepane}
            slideTitle={slide.title}
            slidePurpose={slide.purpose}
            templates={templates}
            selectedTemplateId={slide.template_id}
            onTemplateSelect={(templateId) => updateSlide(selectedSlideIndex, { template_id: templateId })}
            brandKit={brandKit}
            onAction={runAiAction}
            actionLoading={actionLoading}
            history={history}
          />
        </div>
      </main>

      <ExportPreflightModal
        open={ui.preflightModalOpen}
        imageIssueCount={imageIssueCount}
        onClose={() => ui.setPreflightModalOpen(false)}
        onContinue={handlePdfExport}
      />
      <UpgradeModal
        open={ui.upgradeModalOpen}
        onClose={() => {
          ui.setUpgradeModalOpen(false)
          ui.addToast('Coming soon')
        }}
        onExportPdf={() => {
          ui.setUpgradeModalOpen(false)
          ui.setPreflightModalOpen(true)
        }}
      />
    </div>
  )
}
