import type { PresentationSpec } from '../types'

export const mockDecks: PresentationSpec[] = [
  {
    id: 'mock-seed',
    doc_id: 'mock-seed',
    title: 'Seed raise narrative',
    goal: 'Raise seed',
    audience: 'Investors',
    created_at: new Date().toISOString(),
    slides: [
      {
        id: 'seed-1',
        index: 1,
        purpose: 'title',
        title: 'Auto-PPT seed narrative',
        template_id: 'title.hero',
        blocks: [{ id: 'b1', kind: 'text', content: 'A tight opening story for early-stage investors.' }],
      },
      {
        id: 'seed-2',
        index: 2,
        purpose: 'content',
        title: 'Traction signals',
        template_id: 'kpi.3up',
        blocks: [{ id: 'b2', kind: 'kpi_cards', content: '82%|Retention\n3.1x|Pipeline growth\nQ3|Break-even target' }],
      },
    ],
  },
  {
    id: 'mock-board',
    doc_id: 'mock-board',
    title: 'Board update',
    goal: 'Board update',
    audience: 'Board',
    created_at: new Date().toISOString(),
    slides: [
      {
        id: 'board-1',
        index: 1,
        purpose: 'summary',
        title: 'Quarterly operating review',
        template_id: 'content.1col',
        blocks: [{ id: 'b1', kind: 'text', content: 'Margins improved and the next decision window is staffing capacity.' }],
      },
    ],
  },
  {
    id: 'mock-launch',
    doc_id: 'mock-launch',
    title: 'Launch readiness',
    goal: 'Product launch',
    audience: 'Customers',
    created_at: new Date().toISOString(),
    slides: [
      {
        id: 'launch-1',
        index: 1,
        purpose: 'content',
        title: 'Readiness overview',
        template_id: 'content.2col.text_image',
        blocks: [
          { id: 'b1', kind: 'bullets', content: 'Positioning locked\nLaunch comms in review\nEnablement assets in progress' },
          { id: 'b2', kind: 'image', content: 'Hero visual placeholder' },
        ],
      },
    ],
  },
]
