import type { Template } from '../types'

export const featuredTemplates: Template[] = [
  {
    id: 'title.hero',
    name: 'Release Notes',
    alias: 'release-note',
    columns: 1,
    description: 'A concise release communication deck for launches, enhancements, and rollout messaging.',
    deck_default_allowed: false,
  },
  {
    id: 'agenda.list',
    name: 'Team Meetings',
    alias: 'team-meeting',
    columns: 1,
    description: 'A recurring meeting structure for agendas, decisions, owners, and next steps.',
    deck_default_allowed: false,
  },
  {
    id: 'content.2col.text_image',
    name: 'Solution Design',
    alias: 'solution-design',
    columns: 2,
    description: 'A design-review layout for architecture, tradeoffs, workflows, and supporting visuals.',
    deck_default_allowed: false,
  },
  {
    id: 'kpi.3up',
    name: 'Project / Workstream Status',
    alias: 'project-status',
    columns: 3,
    description: 'A status readout template for progress, risks, blockers, and milestone tracking.',
    deck_default_allowed: true,
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
