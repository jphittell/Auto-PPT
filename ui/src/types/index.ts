export type SlidePurpose = 'title' | 'agenda' | 'section' | 'content' | 'summary' | 'appendix' | 'closing'
export type BlockKind = 'text' | 'bullets' | 'image' | 'table' | 'chart' | 'kpi_cards' | 'quote' | 'callout'

export interface ContentBlock {
  id: string
  kind: BlockKind
  content: string
  data?: Record<string, unknown> | null
  citation?: string | null
}

export interface SlideSpec {
  id: string
  index: number
  purpose: SlidePurpose
  archetype?: string | null
  title: string
  blocks: ContentBlock[]
  template_id: string
  speaker_notes?: string | null
}

export interface PresentationSpec {
  id: string
  doc_id: string
  doc_ids: string[]
  title: string
  goal: string
  audience: string
  slides: SlideSpec[]
  created_at: string
  theme?: ThemeSummary | null
}

export interface PlannedDeck {
  draft_id: string
  doc_id: string
  doc_ids: string[]
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
  deck_default_allowed: boolean
}

export interface IngestResult {
  doc_id: string
  chunk_count: number
  title: string
  element_types: Record<string, number>
  source_format: string
  slide_count?: number | null
  slide_types: Record<string, number>
  summary: string
}

export interface PlanParams {
  doc_ids: string[]
  goal: string
  audience: string
  tone: number
  slide_count: number
}

export interface PlanPromptParams {
  doc_ids: string[]
  prompt: string
}

export interface BrandKit {
  logo: string | null
  primary: string
  accent: string
  fontPair: string
}

export interface GenerateParams {
  draft_id: string
  outline: Array<Pick<SlideSpec, 'id' | 'index' | 'purpose' | 'title' | 'template_id'>>
  selected_template_id: string
  theme_name?: string
  brand_kit: BrandKit
}

export interface SlidePreviewParams {
  slide_id: string
  title: string
  purpose: SlidePurpose
  template_id: string
  content: string
  audience: string
  goal: string
}

export type ExportResult =
  | { type: 'pdf'; blob: Blob }
  | { type: 'pptx'; blob: Blob }

export interface ThemeSummary {
  name: string
  primary_color: string
  accent_color: string
  heading_font: string
  body_font: string
  logo_present: boolean
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatGenerateResponse {
  session_id: string
  prompt: string
  inferred_goal: string
  inferred_audience: string
  inferred_slide_count: number
  messages: ChatMessage[]
  deck: PresentationSpec
}
