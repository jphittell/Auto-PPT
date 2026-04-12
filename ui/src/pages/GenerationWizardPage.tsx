import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { generateDeck, getTemplates, ingestDocument, planDeckFromPrompt } from '../api/client'
import { FileDropzone } from '../components/FileDropzone'
import { GeneratingScreen } from '../components/GeneratingScreen'
import { IngestResultCard } from '../components/IngestResultCard'
import { WizardStepIndicator } from '../components/WizardStepIndicator'
import { useDeckStore } from '../store/deckStore'
import { useUIStore } from '../store/uiStore'
import { useWizardStore } from '../store/wizardStore'
import type { Template } from '../types'

export function GenerationWizardPage() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [ingesting, setIngesting] = useState(false)
  const [generatingOutline, setGeneratingOutline] = useState(false)
  const [finalizingDeck, setFinalizingDeck] = useState(false)
  const [generationError, setGenerationError] = useState<string | null>(null)
  const [generationComplete, setGenerationComplete] = useState(false)
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const addDeck = useDeckStore((state) => state.addDeck)
  const addToast = useUIStore((state) => state.addToast)
  const wizard = useWizardStore()

  useEffect(() => {
    // Reset wizard state on fresh entry so users always start clean.
    // Only preserve state when explicitly resuming (e.g., back-button navigation).
    if (!searchParams.has('resume')) {
      wizard.reset()
    }
    getTemplates().then(setTemplates).catch(() => setTemplates([]))
  }, [])

  useEffect(() => {
    const template = searchParams.get('template')
    if (template) wizard.setSelectedTemplateId(template)
  }, [searchParams])

  const deckLevelTemplates = useMemo(
    () => templates.filter((template) => template.deck_default_allowed),
    [templates],
  )
  const hasPowerPointSource = wizard.ingestResults.some((result) => result.source_format === 'pptx')

  useEffect(() => {
    if (!deckLevelTemplates.length) return
    if (deckLevelTemplates.some((template) => template.id === wizard.selectedTemplateId)) return
    wizard.setSelectedTemplateId(deckLevelTemplates[0].id)
  }, [deckLevelTemplates, wizard.selectedTemplateId])

  useEffect(() => {
    if (wizard.step !== 4 || finalizingDeck || generationComplete || generationError || !wizard.plannedDraftId) return
    void handleFinalizeDeck()
  }, [wizard.step, wizard.plannedDraftId, finalizingDeck, generationComplete, generationError])

  async function handleFilesSelect(files: File[]) {
    setIngesting(true)
    const nextResults = [...wizard.ingestResults]
    try {
      for (const file of files) {
        const result = await ingestDocument(file)
        const existingIndex = nextResults.findIndex((item) => item.doc_id === result.doc_id)
        if (existingIndex >= 0) {
          nextResults[existingIndex] = result
        } else {
          nextResults.push(result)
        }
        addToast(`Ingested ${result.title}`, 'success')
      }
      wizard.setIngestResults(nextResults)
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Upload failed', 'error')
    } finally {
      setIngesting(false)
    }
  }

  async function handleGenerateOutline() {
    if (wizard.ingestResults.length === 0) {
      addToast('Upload at least one document first.', 'error')
      return
    }
    if (!wizard.prompt.trim()) {
      addToast('Enter a prompt before planning the outline.', 'error')
      return
    }
    try {
      setGeneratingOutline(true)
      const draft = await planDeckFromPrompt({
        doc_ids: wizard.ingestResults.map((result) => result.doc_id),
        prompt: wizard.prompt.trim(),
      })
      wizard.setOutline(draft.slides)
      wizard.setPlannedDraftId(draft.draft_id)
      wizard.setGoal(draft.goal)
      wizard.setAudience(draft.audience)
      wizard.setGeneratedDeckId(null)
      setGenerationComplete(false)
      setGenerationError(null)
      wizard.setStep(3)
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Deck generation failed', 'error')
    } finally {
      setGeneratingOutline(false)
    }
  }

  async function handleFinalizeDeck() {
    if (!wizard.plannedDraftId) {
      setGenerationError('No deck draft is available yet.')
      return
    }
    try {
      setFinalizingDeck(true)
      setGenerationError(null)
      const deck = await generateDeck({
        draft_id: wizard.plannedDraftId,
        outline: wizard.outline.map((slide) => ({
          id: slide.id,
          index: slide.index,
          purpose: slide.purpose,
          title: slide.title,
          template_id: slide.template_id,
        })),
        selected_template_id: wizard.selectedTemplateId,
        theme_name: 'ONAC',
        brand_kit: wizard.brandKit,
      })
      wizard.setGeneratedDeckId(deck.id)
      addDeck(deck)
      setGenerationComplete(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Deck generation failed'
      setGenerationError(message)
      addToast(message, 'error')
    } finally {
      setFinalizingDeck(false)
    }
  }

  function renderStep() {
    if (wizard.step === 1) {
      return (
        <div className="space-y-6">
          <FileDropzone
            accept=".pdf,.txt,.md,.pptx"
            acceptLabel=".pdf, .txt, .md, and .pptx"
            multiple
            loading={ingesting}
            onFilesSelect={handleFilesSelect}
          />
          {wizard.ingestResults.length > 0 ? (
            <div className="space-y-4">
              <div className="rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-700">
                {wizard.ingestResults.length} source document{wizard.ingestResults.length === 1 ? '' : 's'} ready for planning
              </div>
              {wizard.ingestResults.map((result) => (
                <IngestResultCard key={result.doc_id} result={result} onRemove={() => wizard.removeIngestResult(result.doc_id)} />
              ))}
            </div>
          ) : null}
          <Link to="/templates" className="inline-flex text-sm text-indigo-700">
            Skip - use a template instead
          </Link>
        </div>
      )
    }

    if (wizard.step === 2) {
      return (
        <div className="space-y-8 rounded-3xl border border-slate-200 bg-white p-8 shadow-panel">
          <div className="rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-700">
            {wizard.ingestResults.length} source document{wizard.ingestResults.length === 1 ? '' : 's'} ready:
            <span className="ml-2 font-medium text-slate-950">
              {wizard.ingestResults.map((result) => result.title).join(', ')}
            </span>
          </div>
          <div>
            <h2 className="text-xl font-semibold text-slate-950">Prompt</h2>
            <p className="mt-2 text-sm text-slate-600">
              Describe the deck you want. We&apos;ll infer audience, framing, tone, and slide count from your prompt.
            </p>
            {hasPowerPointSource ? (
              <div className="mt-4 rounded-2xl bg-indigo-50 px-4 py-3 text-sm text-slate-700">
                PowerPoint source detected. We&apos;ll keep the generated deck close to the uploaded slide count and structure unless your prompt says otherwise.
              </div>
            ) : null}
            <textarea
              value={wizard.prompt}
              onChange={(event) => wizard.setPrompt(event.target.value)}
              placeholder="Create a deck for Oracle consultants explaining how AI presentation systems ingest source data, plan slides, and export polished PPTX files."
              className="mt-4 min-h-48 w-full resize-y rounded-3xl border border-slate-200 px-5 py-4 text-base leading-7 text-slate-900 outline-none"
            />
          </div>
        </div>
      )
    }

    if (wizard.step === 3) {
      return (
        <div className="space-y-6">
          <div className="rounded-3xl border border-slate-200 bg-white p-8 shadow-panel">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-semibold text-slate-950">Review outline</h2>
                <p className="mt-2 text-sm text-slate-600">
                  Edit slide titles, reorder, add, or remove slides before generating. The outline drives the final deck.
                </p>
              </div>
              <div className="text-sm text-slate-500">
                {wizard.outline.length} slide{wizard.outline.length === 1 ? '' : 's'}
              </div>
            </div>
            <div className="mt-6 space-y-3">
              {wizard.outline.map((slide, index) => (
                <div
                  key={slide.id}
                  className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
                >
                  <span className="text-xs font-semibold text-slate-400 w-6 text-center">{index + 1}</span>
                  <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] capitalize text-slate-600">
                    {slide.purpose}
                  </span>
                  <input
                    type="text"
                    value={slide.title}
                    onChange={(e) => wizard.updateOutlineTitle(index, e.target.value)}
                    className="flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-400"
                  />
                  <select
                    value={slide.template_id}
                    onChange={(e) => wizard.updateOutlineTemplate(index, e.target.value)}
                    className="rounded-xl border border-slate-200 bg-white px-2 py-2 text-xs text-slate-700"
                  >
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                  <div className="flex gap-1">
                    {index > 0 && (
                      <button
                        type="button"
                        onClick={() => wizard.reorderOutline(index, index - 1)}
                        className="rounded p-1 text-xs text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                        title="Move up"
                      >&#9650;</button>
                    )}
                    {index < wizard.outline.length - 1 && (
                      <button
                        type="button"
                        onClick={() => wizard.reorderOutline(index, index + 1)}
                        className="rounded p-1 text-xs text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                        title="Move down"
                      >&#9660;</button>
                    )}
                    {wizard.outline.length > 1 && (
                      <button
                        type="button"
                        onClick={() => wizard.removeOutlineSlide(index)}
                        className="rounded p-1 text-xs text-slate-400 hover:bg-red-50 hover:text-red-600"
                        title="Remove"
                      >&#10005;</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => wizard.addOutlineSlide()}
              className="mt-4 rounded-xl border border-dashed border-slate-300 px-4 py-2 text-sm text-slate-600 hover:border-slate-400 hover:bg-slate-50"
            >
              + Add slide
            </button>
          </div>
        </div>
      )
    }

    return (
      <GeneratingScreen
        complete={generationComplete}
        error={generationError}
        onComplete={() => {
          if (!wizard.generatedDeckId) {
            addToast('No generated deck is available yet.', 'error')
            return
          }
          navigate(`/editor/${wizard.generatedDeckId}`)
        }}
        onRetry={() => {
          setGenerationError(null)
          setGenerationComplete(false)
          void handleFinalizeDeck()
        }}
      />
    )
  }

  const primaryAction = () => {
    if (wizard.step === 1) {
      if (wizard.ingestResults.length === 0) {
        addToast('Upload at least one document first.', 'error')
        return
      }
      wizard.setStep(2)
      return
    }
    if (wizard.step === 2) {
      handleGenerateOutline()
      return
    }
    if (wizard.step === 3) {
      if (wizard.outline.length === 0) {
        addToast('Outline must have at least one slide.', 'error')
        return
      }
      wizard.setStep(4)
      return
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-7xl px-6 py-10">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <Link to="/" className="text-sm text-slate-500">
              {'<- Back home'}
            </Link>
            <h1 className="mt-3 text-4xl font-semibold text-slate-950">Generation wizard</h1>
          </div>
          {wizard.step > 1 && (
            <button
              type="button"
              onClick={() => {
                wizard.reset()
                setGenerationComplete(false)
                setGenerationError(null)
              }}
              className="rounded-2xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
            >
              Start over
            </button>
          )}
        </div>

        <WizardStepIndicator step={wizard.step} />

        <div className="mt-8">{renderStep()}</div>

        {wizard.step < 4 ? (
          <div className="mt-8 flex items-center justify-between">
            <button
              type="button"
              onClick={wizard.prevStep}
              disabled={wizard.step === 1}
              className="rounded-2xl border border-slate-200 px-5 py-3 text-sm font-medium disabled:opacity-50"
            >
              Back
            </button>
            <button
              type="button"
              onClick={primaryAction}
              disabled={generatingOutline || finalizingDeck}
              className="rounded-2xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:opacity-60"
            >
              {wizard.step === 2 ? 'Plan outline' : wizard.step === 3 ? 'Generate deck' : 'Continue'}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
