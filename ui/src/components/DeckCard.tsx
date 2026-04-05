import { Link } from 'react-router-dom'

import type { PresentationSpec } from '../types'

export function DeckCard({ deck }: { deck: PresentationSpec }) {
  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">{deck.goal}</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-950">{deck.title}</h3>
        </div>
        <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
          {deck.slides.length} slides
        </span>
      </div>
      <div className="mt-5">
        <Link
          to={`/editor/${deck.id}`}
          className="inline-flex rounded-xl bg-slate-950 px-4 py-2 text-sm font-medium text-white"
        >
          Open
        </Link>
      </div>
    </div>
  )
}
