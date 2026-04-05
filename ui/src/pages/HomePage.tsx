import { Link } from 'react-router-dom'

import { DeckCard } from '../components/DeckCard'
import { useDeckStore } from '../store/deckStore'

export function HomePage() {
  const decks = useDeckStore((state) => state.decks.slice(0, 3))

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(79,70,229,0.12),_transparent_35%),linear-gradient(180deg,_#f8fafc,_#eef2ff)]">
      <header className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6">
        <Link to="/" className="text-xl font-semibold text-slate-950">
          Auto-PPT
        </Link>
        <nav className="flex items-center gap-4">
          <Link to="/templates" className="text-sm text-slate-700">
            Templates
          </Link>
          <Link to="/new" className="rounded-full bg-indigo-600 px-4 py-2 text-sm font-medium text-white">
            Start free
          </Link>
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-6 pb-16 pt-10">
        <section className="grid gap-10 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
          <div>
            <p className="text-sm font-medium uppercase tracking-[0.24em] text-indigo-700">Structured presentation generation</p>
            <h1 className="mt-4 max-w-2xl text-5xl font-semibold leading-tight text-slate-950">
              Turn documents into investor-ready decks.
            </h1>
            <p className="mt-5 max-w-2xl text-lg text-slate-600">
              Upload a PDF or paste a brief. Get a structured PPTX in minutes.
            </p>
            <div className="mt-8 flex flex-wrap gap-4">
              <Link to="/new" className="rounded-2xl bg-indigo-600 px-5 py-3 font-medium text-white">
                Generate from document
              </Link>
              <Link to="/templates" className="rounded-2xl border border-slate-300 px-5 py-3 font-medium text-slate-800">
                Browse templates
              </Link>
            </div>
            <div className="mt-8 flex flex-wrap gap-4 text-sm text-slate-500">
              <span>Real document parsing</span>
              <span>·</span>
              <span>10 layout templates</span>
              <span>·</span>
              <span>Editable PPTX</span>
              <span>·</span>
              <span>Brand-safe</span>
            </div>
          </div>
          <div className="rounded-[32px] border border-indigo-100 bg-white/80 p-6 shadow-panel backdrop-blur">
            <div className="grid gap-4 md:grid-cols-2">
              {['title.hero', 'content.2col.text_image', 'kpi.3up', 'table.full'].map((label) => (
                <div key={label} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="h-24 rounded-xl bg-gradient-to-b from-indigo-200 to-white" />
                  <div className="mt-3 text-sm font-medium text-slate-900">{label}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="mt-16">
          <div className="mb-6 flex items-center justify-between">
            <h2 className="text-2xl font-semibold text-slate-950">Recent decks</h2>
          </div>
          <div className="grid gap-5 md:grid-cols-3">
            {decks.map((deck) => (
              <DeckCard key={deck.id} deck={deck} />
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}
