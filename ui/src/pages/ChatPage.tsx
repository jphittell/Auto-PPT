import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { chatGenerateDeck } from '../api/client'
import { useDeckStore } from '../store/deckStore'
import { useUIStore } from '../store/uiStore'
import type { ChatMessage } from '../types'

export function ChatPage() {
  const [file, setFile] = useState<File | null>(null)
  const [prompt, setPrompt] = useState('Create a polished executive deck from this document for Oracle consultants. Keep it to 6 slides and focus on architecture, workflow, and key implementation takeaways.')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const addDeck = useDeckStore((state) => state.addDeck)
  const addToast = useUIStore((state) => state.addToast)
  const navigate = useNavigate()

  async function handleGenerate() {
    if (!file) {
      addToast('Attach a document first.', 'error')
      return
    }
    if (!prompt.trim()) {
      addToast('Enter a request for the deck.', 'error')
      return
    }
    try {
      setLoading(true)
      setMessages((current) => [...current, { role: 'user', content: prompt }])
      const response = await chatGenerateDeck(file, prompt)
      setMessages(response.messages)
      addDeck(response.deck)
      addToast('Deck generated from chat.', 'success')
      navigate(`/editor/${response.deck.id}`)
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Chat generation failed', 'error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-5xl px-6 py-10">
        <div className="mb-8">
          <Link to="/" className="text-sm text-slate-500">
            {'<- Back home'}
          </Link>
          <h1 className="mt-3 text-4xl font-semibold text-slate-950">Chat generation</h1>
          <p className="mt-3 max-w-3xl text-lg text-slate-600">
            Drop in a document, describe the deck you want, and run the same planning and generation pipeline through a chat-style flow.
          </p>
        </div>

        <div className="grid gap-8 lg:grid-cols-[1.05fr_0.95fr]">
          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-panel">
            <div className="space-y-5">
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">Document</span>
                <input
                  type="file"
                  accept=".pdf,.txt,.md,.pptx"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                  className="block w-full rounded-2xl border border-slate-200 px-4 py-3"
                />
              </label>
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">Prompt</span>
                <textarea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  className="h-40 w-full resize-none rounded-3xl border border-slate-200 px-4 py-4 outline-none"
                />
              </label>
              <button
                type="button"
                onClick={() => void handleGenerate()}
                disabled={loading}
                className="rounded-2xl bg-slate-950 px-5 py-3 text-sm font-medium text-white disabled:opacity-60"
              >
                {loading ? 'Generating deck...' : 'Generate in chat mode'}
              </button>
            </div>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-panel">
            <h2 className="text-xl font-semibold text-slate-950">Conversation</h2>
            <div className="mt-5 space-y-4">
              {messages.length === 0 ? (
                <div className="rounded-2xl bg-slate-100 p-4 text-sm text-slate-600">
                  The assistant will summarize the inferred brief and open the generated deck in the editor.
                </div>
              ) : (
                messages.map((message, index) => (
                  <div
                    key={`${message.role}-${index}`}
                    className={`rounded-2xl px-4 py-3 text-sm ${
                      message.role === 'user' ? 'ml-10 bg-indigo-50 text-slate-900' : 'mr-10 bg-slate-100 text-slate-700'
                    }`}
                  >
                    <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{message.role}</div>
                    <div>{message.content}</div>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
