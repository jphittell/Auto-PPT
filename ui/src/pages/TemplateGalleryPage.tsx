import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { getTemplates } from '../api/client'
import { TemplateCard } from '../components/TemplateCard'
import { featuredTemplates, mergeTemplates } from '../mock/templates'
import type { Template } from '../types'

export function TemplateGalleryPage() {
  const [templates, setTemplates] = useState<Template[]>(featuredTemplates)
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    getTemplates()
      .then((results) => setTemplates(results.length > 0 ? mergeTemplates(results) : featuredTemplates))
      .catch(() => setTemplates(featuredTemplates))
  }, [])

  const filtered = useMemo(
    () =>
      templates.filter((template) =>
        [template.name, template.alias].some((value) => value.toLowerCase().includes(query.toLowerCase())),
      ),
    [query, templates],
  )

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-7xl px-6 py-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <Link to="/" className="text-sm text-slate-500">
              {'<- Back home'}
            </Link>
            <h1 className="mt-3 text-4xl font-semibold text-slate-950">Template gallery</h1>
          </div>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search templates"
            className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white px-4 py-3 outline-none"
          />
        </div>
        <div className="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((template) => (
            <TemplateCard key={template.id} template={template} onSelect={() => navigate(`/new?template=${template.id}`)} />
          ))}
        </div>
        {filtered.length === 0 ? (
          <div className="mt-8 rounded-3xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
            No templates matched your search.
          </div>
        ) : null}
      </div>
    </div>
  )
}
