import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { generateDeck, getTemplates, ingestDocument } from '../api/client'
import { FileDropzone } from '../components/FileDropzone'
import { GeneratingScreen } from '../components/GeneratingScreen'
import { IngestResultCard } from '../components/IngestResultCard'
import { OutlineTreeEditor } from '../components/OutlineTreeEditor'
import { PillChipGroup } from '../components/PillChipGroup'
import { TemplateCard } from '../components/TemplateCard'
import { ToneSlider } from '../components/ToneSlider'
import { WizardStepIndicator } from '../components/WizardStepIndicator'
import { useDeckStore } from '../store/deckStore'
import { useUIStore } from '../store/uiStore'
import { useWizardStore } from '../store/wizardStore'
import type { Template } from '../types'

const goalOptions = ['Raise seed', 'Close a deal', 'Board update', 'Internal training', 'Product launch']
const audienceOptions = ['Investors', 'Customers', 'Board', 'All-hands', 'New hires']
const fontPairs = ['Inter/Inter', 'Lato/Merriweather', 'DM Sans/DM Serif Display']

export function GenerationWizardPage() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [ingesting, setIngesting] = useState(false)
  const [generatingOutline, setGeneratingOutline] = useState(false)
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const addDeck = useDeckStore((state) => state.addDeck)
  const addToast = useUIStore((state) => state.addToast)
  const wizard = useWizardStore()

  useEffect(() => {
    getTemplates().then(setTemplates).catch(() => setTemplates([]))
  }, [])

  useEffect(() => {
    const template = searchParams.get('template')
    if (template) wizard.setSelectedTemplateId(template)
  }, [searchParams])

  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === wizard.selectedTemplateId) ?? null,
    [templates, wizard.selectedTemplateId],
  )

  async function handleFileSelect(file: File) {
    try {
      setIngesting(true)
      const result = await ingestDocument(file)
      wizard.setIngestResult(result)
      addToast(`Ingested ${result.title}`, 'success')
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Upload failed', 'error')
    } finally {
      setIngesting(false)
    }
  }

  async function handleGenerateOutline() {
    if (!wizard.ingestResult) {
      addToast('Upload a document first.', 'error')
      return
    }
    try {
      setGeneratingOutline(true)
      const deck = await generateDeck({
        doc_id: wizard.ingestResult.doc_id,
        goal: wizard.goal,
        audience: wizard.audience,
        tone: wizard.tone,
        slide_count: wizard.slideCount,
      })
      wizard.setOutline(deck.slides)
      wizard.setGeneratedDeckId(deck.id)
      addDeck(deck)
      wizard.setStep(3)
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Deck generation failed', 'error')
    } finally {
      setGeneratingOutline(false)
    }
  }

  function renderStep() {
    if (wizard.step === 1) {
      return (
        <div className="space-y-6">
          <FileDropzone accept=".pdf,.txt,.md" loading={ingesting} onFileSelect={handleFileSelect} />
          {wizard.ingestResult ? <IngestResultCard result={wizard.ingestResult} /> : null}
          <Link to="/templates" className="inline-flex text-sm text-indigo-700">
            Skip — use a template instead
          </Link>
        </div>
      )
    }

    if (wizard.step === 2) {
      return (
        <div className="space-y-8 rounded-3xl border border-slate-200 bg-white p-8 shadow-panel">
          <div>
            <h2 className="text-xl font-semibold text-slate-950">Goal</h2>
            <div className="mt-4">
              <PillChipGroup options={goalOptions} value={wizard.goal} onChange={wizard.setGoal} />
            </div>
          </div>
          <div>
            <h2 className="text-xl font-semibold text-slate-950">Audience</h2>
            <div className="mt-4">
              <PillChipGroup options={audienceOptions} value={wizard.audience} onChange={wizard.setAudience} />
            </div>
          </div>
          <div>
            <h2 className="text-xl font-semibold text-slate-950">Tone</h2>
            <div className="mt-4">
              <ToneSlider value={wizard.tone} onChange={wizard.setTone} />
            </div>
          </div>
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-slate-700">Slide count</span>
            <input
              type="number"
              min={6}
              max={20}
              value={wizard.slideCount}
              onChange={(event) => wizard.setSlideCount(Number(event.target.value))}
              className="w-32 rounded-xl border border-slate-200 px-4 py-3 outline-none"
            />
          </label>
        </div>
      )
    }

    if (wizard.step === 3) {
      return (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-semibold text-slate-950">Outline preview</h2>
              <p className="text-sm text-slate-600">Review and reorder the planned slides.</p>
            </div>
            <button
              type="button"
              onClick={handleGenerateOutline}
              disabled={generatingOutline}
              className="rounded-2xl bg-slate-950 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {generatingOutline ? 'Planning your deck…' : 'Regenerate outline'}
            </button>
          </div>
          {generatingOutline && wizard.outline.length === 0 ? (
            <div className="rounded-3xl border border-slate-200 bg-white p-10 text-center shadow-panel">
              <div className="text-lg font-medium text-slate-900">Planning your deck…</div>
            </div>
          ) : (
            <OutlineTreeEditor
              slides={wizard.outline}
              onReorder={wizard.reorderOutline}
              onTitleChange={wizard.updateOutlineTitle}
            />
          )}
        </div>
      )
    }

    if (wizard.step === 4) {
      return (
        <div className="space-y-8">
          <div>
            <h2 className="text-2xl font-semibold text-slate-950">Style</h2>
            <div className="mt-5 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {templates.map((template) => (
                <TemplateCard
                  key={template.id}
                  template={template}
                  selected={template.id === wizard.selectedTemplateId}
                  onSelect={() => wizard.setSelectedTemplateId(template.id)}
                />
              ))}
            </div>
          </div>
          <details className="rounded-3xl border border-slate-200 bg-white p-6 shadow-panel">
            <summary className="cursor-pointer text-lg font-semibold text-slate-950">Brand kit (optional)</summary>
            <div className="mt-6 grid gap-5 md:grid-cols-2">
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">Logo upload</span>
                <input
                  type="file"
                  accept="image/*"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (!file) return
                    const reader = new FileReader()
                    reader.onload = () => wizard.setBrandKit({ logo: typeof reader.result === 'string' ? reader.result : null })
                    reader.readAsDataURL(file)
                  }}
                  className="block w-full rounded-xl border border-slate-200 px-4 py-3"
                />
              </label>
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">Primary color</span>
                <div className="flex items-center gap-3">
                  <input type="color" value={wizard.brandKit.primary} onChange={(event) => wizard.setBrandKit({ primary: event.target.value })} />
                  <input
                    value={wizard.brandKit.primary}
                    onChange={(event) => wizard.setBrandKit({ primary: event.target.value })}
                    className="w-full rounded-xl border border-slate-200 px-4 py-3"
                  />
                </div>
              </label>
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">Accent color</span>
                <div className="flex items-center gap-3">
                  <input type="color" value={wizard.brandKit.accent} onChange={(event) => wizard.setBrandKit({ accent: event.target.value })} />
                  <input
                    value={wizard.brandKit.accent}
                    onChange={(event) => wizard.setBrandKit({ accent: event.target.value })}
                    className="w-full rounded-xl border border-slate-200 px-4 py-3"
                  />
                </div>
              </label>
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">Font pairing</span>
                <select
                  value={wizard.brandKit.fontPair}
                  onChange={(event) => wizard.setBrandKit({ fontPair: event.target.value })}
                  className="w-full rounded-xl border border-slate-200 px-4 py-3"
                >
                  {fontPairs.map((pair) => (
                    <option key={pair} value={pair}>
                      {pair}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </details>
          {selectedTemplate ? (
            <div className="rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-700">
              Selected template: <span className="font-medium text-slate-950">{selectedTemplate.name}</span>
            </div>
          ) : null}
        </div>
      )
    }

    return (
      <GeneratingScreen
        onComplete={() => {
          if (!wizard.generatedDeckId) {
            addToast('No generated deck is available yet.', 'error')
            return
          }
          navigate(`/editor/${wizard.generatedDeckId}`)
        }}
      />
    )
  }

  const primaryAction = () => {
    if (wizard.step === 1) {
      wizard.setStep(2)
      return
    }
    if (wizard.step === 2) {
      handleGenerateOutline()
      return
    }
    if (wizard.step === 3) {
      wizard.setStep(4)
      return
    }
    if (wizard.step === 4) {
      wizard.setStep(5)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-7xl px-6 py-10">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <Link to="/" className="text-sm text-slate-500">
              ← Back home
            </Link>
            <h1 className="mt-3 text-4xl font-semibold text-slate-950">Generation wizard</h1>
          </div>
        </div>

        <WizardStepIndicator step={wizard.step} />

        <div className="mt-8">{renderStep()}</div>

        {wizard.step < 5 ? (
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
              disabled={generatingOutline}
              className="rounded-2xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:opacity-60"
            >
              {wizard.step === 2 ? 'Plan outline' : wizard.step === 4 ? 'Generate deck' : 'Continue'}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
