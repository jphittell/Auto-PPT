export type SlidePurpose = 'title' | 'agenda' | 'section' | 'content' | 'summary' | 'appendix'
export type BlockKind = 'text' | 'bullets' | 'image' | 'table' | 'chart' | 'kpi_cards' | 'quote' | 'callout'

export interface ContentBlock {
  id: string
  kind: BlockKind
  content: string
  citation?: string | null
}

export interface SlideSpec {
  id: string
  index: number
  purpose: SlidePurpose
  title: string
  blocks: ContentBlock[]
  template_id: string
  speaker_notes?: string | null
}

export interface PresentationSpec {
  id: string
  doc_id: string
  title: string
  goal: string
  audience: string
  slides: SlideSpec[]
  created_at: string
}

export interface Template {
  id: string
  name: string
  alias: string
  columns: number
  description: string
}

export interface IngestResult {
  doc_id: string
  chunk_count: number
  title: string
  element_types: Record<string, number>
}

export interface GenerateParams {
  doc_id: string
  goal: string
  audience: string
  tone: number
  slide_count: number
}

export type ExportResult =
  | { type: 'pdf'; blob: Blob }
  | { type: 'pptx'; status: 'upgrade_required'; tier: 'pro' }

export interface BrandKit {
  logo: string | null
  primary: string
  accent: string
  fontPair: string
}
