import type { ChatGenerateResponse, ExportResult, GenerateParams, IngestResult, PlanParams, PlannedDeck, PresentationSpec, Template } from '../types'

const BASE = '/api'

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.text()
    throw new Error(payload || `Request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function ingestDocument(file: File): Promise<IngestResult> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(`${BASE}/ingest`, {
    method: 'POST',
    body: formData,
  })
  return parseJson<IngestResult>(response)
}

export async function planDeck(params: PlanParams): Promise<PlannedDeck> {
  const response = await fetch(`${BASE}/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  return parseJson<PlannedDeck>(response)
}

export async function generateDeck(params: GenerateParams): Promise<PresentationSpec> {
  const response = await fetch(`${BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      draft_id: params.draft_id,
      outline: params.outline,
      selected_template_id: params.selected_template_id,
      brand_kit: {
        logo_data_url: params.brand_kit.logo,
        primary_color: params.brand_kit.primary,
        accent_color: params.brand_kit.accent,
        font_pair: params.brand_kit.fontPair,
      },
    }),
  })
  return parseJson<PresentationSpec>(response)
}

export async function getTemplates(): Promise<Template[]> {
  const response = await fetch(`${BASE}/templates`)
  return parseJson<Template[]>(response)
}

export async function getDeck(deckId: string): Promise<PresentationSpec> {
  const response = await fetch(`${BASE}/deck/${deckId}`)
  return parseJson<PresentationSpec>(response)
}

export async function exportDeck(deckId: string, format: 'pdf' | 'pptx'): Promise<ExportResult> {
  const response = await fetch(`${BASE}/export/${deckId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ format }),
  })
  if (!response.ok) {
    const payload = await response.text()
    throw new Error(payload || `Export failed: ${response.status}`)
  }
  return { type: format, blob: await response.blob() }
}

export async function chatGenerateDeck(file: File, prompt: string): Promise<ChatGenerateResponse> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('prompt', prompt)
  const response = await fetch(`${BASE}/chat/generate`, {
    method: 'POST',
    body: formData,
  })
  return parseJson<ChatGenerateResponse>(response)
}
