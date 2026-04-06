import { create } from 'zustand'

import type { BrandKit, IngestResult, SlideSpec } from '../types'

interface WizardStore {
  step: 1 | 2 | 3 | 4 | 5
  ingestResults: IngestResult[]
  goal: string
  audience: string
  tone: number
  slideCount: number
  outline: SlideSpec[]
  selectedTemplateId: string
  brandKit: BrandKit
  plannedDraftId: string | null
  generatedDeckId: string | null
  nextStep: () => void
  prevStep: () => void
  setStep: (step: WizardStore['step']) => void
  setIngestResults: (results: IngestResult[]) => void
  addIngestResult: (result: IngestResult) => void
  removeIngestResult: (docId: string) => void
  setGoal: (goal: string) => void
  setAudience: (audience: string) => void
  setTone: (tone: number) => void
  setSlideCount: (count: number) => void
  setOutline: (outline: SlideSpec[]) => void
  reorderOutline: (fromIndex: number, toIndex: number) => void
  updateOutlineTitle: (index: number, title: string) => void
  setSelectedTemplateId: (templateId: string) => void
  setBrandKit: (partial: Partial<BrandKit>) => void
  setPlannedDraftId: (draftId: string | null) => void
  setGeneratedDeckId: (deckId: string | null) => void
  reset: () => void
}

const defaultBrandKit: BrandKit = {
  logo: null,
  primary: '#4F46E5',
  accent: '#0F172A',
  fontPair: 'Inter/Inter',
}

export const useWizardStore = create<WizardStore>((set) => ({
  step: 1,
  ingestResults: [],
  goal: 'Raise seed',
  audience: 'Investors',
  tone: 50,
  slideCount: 8,
  outline: [],
  selectedTemplateId: 'content.1col',
  brandKit: defaultBrandKit,
  plannedDraftId: null,
  generatedDeckId: null,
  nextStep: () => set((state) => ({ step: Math.min(5, state.step + 1) as WizardStore['step'] })),
  prevStep: () => set((state) => ({ step: Math.max(1, state.step - 1) as WizardStore['step'] })),
  setStep: (step) => set({ step }),
  setIngestResults: (ingestResults) => set({ ingestResults }),
  addIngestResult: (result) =>
    set((state) => ({
      ingestResults: [...state.ingestResults.filter((item) => item.doc_id !== result.doc_id), result],
    })),
  removeIngestResult: (docId) =>
    set((state) => ({
      ingestResults: state.ingestResults.filter((item) => item.doc_id !== docId),
    })),
  setGoal: (goal) => set({ goal }),
  setAudience: (audience) => set({ audience }),
  setTone: (tone) => set({ tone }),
  setSlideCount: (slideCount) => set({ slideCount }),
  setOutline: (outline) => set({ outline }),
  reorderOutline: (fromIndex, toIndex) =>
    set((state) => {
      const next = [...state.outline]
      const [moved] = next.splice(fromIndex, 1)
      next.splice(toIndex, 0, moved)
      return { outline: next.map((slide, index) => ({ ...slide, index: index + 1 })) }
    }),
  updateOutlineTitle: (index, title) =>
    set((state) => ({
      outline: state.outline.map((slide, slideIndex) => (slideIndex === index ? { ...slide, title } : slide)),
    })),
  setSelectedTemplateId: (selectedTemplateId) => set({ selectedTemplateId }),
  setBrandKit: (partial) => set((state) => ({ brandKit: { ...state.brandKit, ...partial } })),
  setPlannedDraftId: (plannedDraftId) => set({ plannedDraftId }),
  setGeneratedDeckId: (generatedDeckId) => set({ generatedDeckId }),
  reset: () =>
    set({
      step: 1,
      ingestResults: [],
      goal: 'Raise seed',
      audience: 'Investors',
      tone: 50,
      slideCount: 8,
      outline: [],
      selectedTemplateId: 'content.1col',
      brandKit: defaultBrandKit,
      plannedDraftId: null,
      generatedDeckId: null,
    }),
}))
