import { create } from 'zustand'

import { getDeck } from '../api/client'
import { mockDecks } from '../mock/decks'
import type { ContentBlock, PresentationSpec, SlideSpec } from '../types'

interface DeckStore {
  decks: PresentationSpec[]
  currentDeck: PresentationSpec | null
  selectedSlideIndex: number
  loadDeck: (id: string) => Promise<void>
  addDeck: (deck: PresentationSpec) => void
  updateSlide: (index: number, slide: Partial<SlideSpec>) => void
  replaceSlide: (index: number, slide: SlideSpec) => void
  insertSlideAfter: (index: number, slide?: SlideSpec) => void
  addSlide: () => void
  setSelectedSlide: (i: number) => void
}

export const useDeckStore = create<DeckStore>((set, get) => ({
  decks: mockDecks,
  currentDeck: null,
  selectedSlideIndex: 0,
  loadDeck: async (id: string) => {
    const existing = get().decks.find((deck) => deck.id === id)
    if (existing) {
      set({ currentDeck: existing, selectedSlideIndex: 0 })
      return
    }
    const deck = await getDeck(id)
    set((state) => ({
      decks: state.decks.some((item) => item.id === deck.id) ? state.decks : [deck, ...state.decks],
      currentDeck: deck,
      selectedSlideIndex: 0,
    }))
  },
  addDeck: (deck) =>
    set((state) => ({
      decks: [deck, ...state.decks.filter((item) => item.id !== deck.id)],
      currentDeck: deck,
      selectedSlideIndex: 0,
    })),
  updateSlide: (index, slide) =>
    set((state) => {
      if (!state.currentDeck) return {}
      const slides = state.currentDeck.slides.map((current, currentIndex) =>
        currentIndex === index ? { ...current, ...slide } : current,
      )
      return { currentDeck: { ...state.currentDeck, slides } }
    }),
  replaceSlide: (index, slide) =>
    set((state) => {
      if (!state.currentDeck) return {}
      const slides = state.currentDeck.slides.map((current, currentIndex) => (currentIndex === index ? slide : current))
      return { currentDeck: { ...state.currentDeck, slides } }
    }),
  insertSlideAfter: (index, slide) =>
    set((state) => {
      if (!state.currentDeck) return {}
      const nextSlide: SlideSpec =
        slide ?? {
          id: `slide-${Date.now()}`,
          index: index + 2,
          purpose: 'content',
          title: 'New content slide',
          template_id: 'headline.evidence',
          blocks: [{ id: `block-${Date.now()}`, kind: 'text', content: 'Add content here.' }],
      }
      const slides = [...state.currentDeck.slides]
      slides.splice(index + 1, 0, nextSlide)
      return {
        currentDeck: {
          ...state.currentDeck,
          slides: slides.map((item, position) => ({ ...item, index: position + 1 })),
        },
      }
    }),
  addSlide: () =>
    set((state) => {
      if (!state.currentDeck) return {}
      const blocks: ContentBlock[] = [{ id: `block-${Date.now()}`, kind: 'text', content: 'Start writing here.' }]
      const nextSlide: SlideSpec = {
        id: `slide-${Date.now()}`,
        index: state.currentDeck.slides.length + 1,
        purpose: 'content',
        title: 'Blank content slide',
        template_id: 'headline.evidence',
        blocks,
      }
      const slides = [
        ...state.currentDeck.slides,
        nextSlide,
      ]
      return { currentDeck: { ...state.currentDeck, slides } }
    }),
  setSelectedSlide: (selectedSlideIndex) => set({ selectedSlideIndex }),
}))
