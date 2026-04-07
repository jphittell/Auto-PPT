import type { Template } from '../types'

export const featuredTemplates: Template[] = [
  {
    id: 'title.cover',
    name: 'Title / Cover',
    alias: 'title',
    columns: 1,
    description: 'Opening slide with title, subtitle, and presenter info.',
    deck_default_allowed: false,
  },
  {
    id: 'section.divider',
    name: 'Section Divider',
    alias: 'section',
    columns: 1,
    description: 'Section break with large headline and tagline.',
    deck_default_allowed: false,
  },
  {
    id: 'exec.summary',
    name: 'Executive Summary',
    alias: 'executive',
    columns: 2,
    description: 'Key points, insight callout, and summary cards.',
    deck_default_allowed: false,
  },
  {
    id: 'headline.evidence',
    name: 'Headline + Evidence',
    alias: 'evidence',
    columns: 1,
    description: 'Headline with supporting evidence and takeaway.',
    deck_default_allowed: true,
  },
  {
    id: 'kpi.big',
    name: 'Big Number / KPI',
    alias: 'kpi',
    columns: 3,
    description: 'Three prominent metrics or KPI callouts.',
    deck_default_allowed: true,
  },
  {
    id: 'compare.2col',
    name: 'Two-Column Comparison',
    alias: 'compare',
    columns: 2,
    description: 'Side-by-side comparison of two perspectives.',
    deck_default_allowed: true,
  },
  {
    id: 'chart.takeaway',
    name: 'Chart + Takeaway',
    alias: 'chart',
    columns: 1,
    description: 'Full chart with insight sidebar.',
    deck_default_allowed: false,
  },
  {
    id: 'closing.actions',
    name: 'Next Steps / Closing',
    alias: 'closing',
    columns: 1,
    description: 'Action items and closing statement.',
    deck_default_allowed: false,
  },
]

export function mergeTemplates(apiTemplates: Template[]): Template[] {
  const apiById = new Map(apiTemplates.map((template) => [template.id, template]))
  const featured = featuredTemplates.map((template) => {
    const apiTemplate = apiById.get(template.id)
    return apiTemplate ? { ...apiTemplate, ...template } : template
  })

  const remaining = apiTemplates.filter((template) => !featured.some((item) => item.id === template.id))
  return [...featured, ...remaining]
}
