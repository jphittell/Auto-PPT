import { Link } from 'react-router-dom'

import { DeckCard } from '../components/DeckCard'
import { featuredTemplates } from '../mock/templates'
import { useDeckStore } from '../store/deckStore'

function TemplateIllustration({ templateId }: { templateId: string }) {
  const accent = '#6366F1'
  const accentSoft = '#C7D2FE'
  const accentMid = '#A5B4FC'
  const ink = '#334155'

  if (templateId === 'title.hero') {
    return (
      <svg viewBox="0 0 240 112" className="h-24 w-full rounded-xl">
        <defs>
          <linearGradient id="release-bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#E0E7FF" />
            <stop offset="100%" stopColor="#F8FAFC" />
          </linearGradient>
        </defs>
        <rect width="240" height="112" rx="16" fill="url(#release-bg)" />
        <rect x="18" y="18" width="204" height="76" rx="14" fill="#EEF2FF" />
        <text x="120" y="64" textAnchor="middle" fontSize="42" fontWeight="700" fill={accent}>
          26B
        </text>
        <rect x="82" y="72" width="76" height="6" rx="3" fill={accentSoft} />
      </svg>
    )
  }

  if (templateId === 'agenda.list') {
    return (
      <svg viewBox="0 0 240 112" className="h-24 w-full rounded-xl">
        <defs>
          <linearGradient id="meeting-bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#E0E7FF" />
            <stop offset="100%" stopColor="#F8FAFC" />
          </linearGradient>
        </defs>
        <rect width="240" height="112" rx="16" fill="url(#meeting-bg)" />
        <rect x="72" y="48" width="96" height="20" rx="10" fill="#C7D2FE" />
        <ellipse cx="88" cy="38" rx="10" ry="10" fill={accentMid} />
        <ellipse cx="120" cy="32" rx="10" ry="10" fill={accentMid} />
        <ellipse cx="152" cy="38" rx="10" ry="10" fill={accentMid} />
        <ellipse cx="64" cy="56" rx="10" ry="10" fill={accentSoft} />
        <ellipse cx="176" cy="56" rx="10" ry="10" fill={accentSoft} />
        <rect x="82" y="46" width="4" height="24" rx="2" fill={ink} opacity="0.35" />
        <rect x="118" y="40" width="4" height="28" rx="2" fill={ink} opacity="0.35" />
        <rect x="154" y="46" width="4" height="24" rx="2" fill={ink} opacity="0.35" />
        <rect x="58" y="58" width="4" height="20" rx="2" fill={ink} opacity="0.35" />
        <rect x="178" y="58" width="4" height="20" rx="2" fill={ink} opacity="0.35" />
      </svg>
    )
  }

  if (templateId === 'content.2col.text_image') {
    return (
      <svg viewBox="0 0 240 112" className="h-24 w-full rounded-xl">
        <defs>
          <linearGradient id="design-bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#E0E7FF" />
            <stop offset="100%" stopColor="#F8FAFC" />
          </linearGradient>
        </defs>
        <rect width="240" height="112" rx="16" fill="url(#design-bg)" />
        <rect x="20" y="24" width="54" height="22" rx="11" fill="#C7D2FE" />
        <rect x="92" y="24" width="54" height="22" rx="11" fill="#C7D2FE" />
        <rect x="164" y="24" width="54" height="22" rx="11" fill="#C7D2FE" />
        <rect x="56" y="67" width="54" height="22" rx="11" fill="#A5B4FC" />
        <rect x="128" y="67" width="54" height="22" rx="11" fill="#A5B4FC" />
        <path d="M74 35h18m54 0h18M47 46v10c0 6 4 11 10 11h0m125-21v10c0 6-4 11-10 11h0M110 78h18" stroke={ink} strokeWidth="3" strokeLinecap="round" opacity="0.4" />
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 240 112" className="h-24 w-full rounded-xl">
      <defs>
        <linearGradient id="status-bg" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#E0E7FF" />
          <stop offset="100%" stopColor="#F8FAFC" />
        </linearGradient>
      </defs>
      <rect width="240" height="112" rx="16" fill="url(#status-bg)" />
      <path d="M54 26v58M54 84h142" stroke="#94A3B8" strokeWidth="3" strokeLinecap="round" opacity="0.5" />
      <rect x="68" y="34" width="54" height="10" rx="5" fill="#A5B4FC" />
      <rect x="96" y="50" width="70" height="10" rx="5" fill="#818CF8" />
      <rect x="82" y="66" width="92" height="10" rx="5" fill="#C7D2FE" />
      <circle cx="68" cy="39" r="4" fill="#6366F1" />
      <circle cx="96" cy="55" r="4" fill="#4F46E5" />
      <circle cx="82" cy="71" r="4" fill="#818CF8" />
    </svg>
  )
}

export function HomePage() {
  const decks = useDeckStore((state) => state.decks)
  const recentDecks = decks.slice(0, 4)

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6">
        <Link to="/" className="text-xl font-semibold text-slate-950">
          Auto-PPT
        </Link>
      </header>

      <main className="mx-auto max-w-7xl px-6 pb-16 pt-10">
        <section className="grid gap-10 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
          <div>
            <p className="text-sm font-medium uppercase tracking-[0.24em] text-indigo-700">Structured presentation generation</p>
            <h1 className="mt-4 max-w-2xl text-5xl font-semibold leading-tight text-slate-950">
              Generate Slides the Smart Way
            </h1>
            <p className="mt-5 max-w-2xl text-lg text-slate-600">
              Upload a PDF or paste a brief. Get a structured PPTX in minutes.
            </p>
            <div className="mt-8 flex flex-wrap gap-4">
              <Link to="/new" className="rounded-2xl bg-indigo-600 px-5 py-3 font-medium text-white">
                Generate from document
              </Link>
              <Link to="/chat" className="rounded-2xl bg-slate-950 px-5 py-3 font-medium text-white">
                Generate in chat
              </Link>
              <Link to="/templates" className="rounded-2xl border border-slate-300 px-5 py-3 font-medium text-slate-800">
                Browse templates
              </Link>
            </div>
            <div className="mt-8 flex flex-wrap gap-4 text-sm text-slate-500">
              <span>Real document parsing</span>
              <span>|</span>
              <span>12 layout templates</span>
              <span>|</span>
              <span>Editable PPTX</span>
              <span>|</span>
              <span>Brand-safe</span>
            </div>
          </div>
          <div className="rounded-[32px] border border-indigo-100 bg-white/80 p-6 shadow-panel backdrop-blur">
            <div className="grid gap-4 md:grid-cols-2">
              {featuredTemplates.map((template) => (
                <Link
                  key={template.id}
                  to={`/new?template=${encodeURIComponent(template.id)}`}
                  className="rounded-2xl border border-slate-200 bg-slate-50 p-4 transition hover:border-indigo-300 hover:shadow-sm"
                >
                  <TemplateIllustration templateId={template.id} />
                  <div className="mt-3 text-sm font-medium text-slate-900">{template.name}</div>
                </Link>
              ))}
            </div>
          </div>
        </section>

        <section className="mt-16">
          <div className="mb-6 flex items-center justify-between">
            <h2 className="text-2xl font-semibold text-slate-950">Recent decks</h2>
          </div>
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            {recentDecks.map((deck) => (
              <DeckCard key={deck.id} deck={deck} />
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}
