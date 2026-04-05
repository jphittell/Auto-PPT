import type { Template } from '../types'

interface AISidepaneProps {
  activeTab: 'ai' | 'design' | 'data'
  onTabChange: (tab: 'ai' | 'design' | 'data') => void
  sidepaneOpen: boolean
  onToggle: () => void
  slideTitle: string
  slidePurpose: string
  templates: Template[]
  selectedTemplateId: string
  onTemplateSelect: (templateId: string) => void
  brandKit: { primary: string; accent: string; fontPair: string }
  onAction: (action: string) => void
  actionLoading: string | null
  history: string[]
}

const actions = ['Rewrite for investors', 'Make more concise', 'Convert to bullet list', 'Regenerate layout', 'Add slide after this']

export function AISidepane(props: AISidepaneProps) {
  if (!props.sidepaneOpen) {
    return (
      <button
        type="button"
        onClick={props.onToggle}
        className="border-l border-slate-200 bg-white px-3 py-4 text-sm text-slate-600"
        aria-label="Open sidepane"
      >
        Open
      </button>
    )
  }

  return (
    <aside className="w-80 border-l border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div className="flex gap-2">
          {(['ai', 'design', 'data'] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => props.onTabChange(tab)}
              className={`rounded-full px-3 py-1 text-sm ${
                props.activeTab === tab ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600'
              }`}
            >
              {tab.toUpperCase()}
            </button>
          ))}
        </div>
        <button type="button" onClick={props.onToggle} className="text-sm text-slate-500" aria-label="Close sidepane">
          Close
        </button>
      </div>
      <div className="h-[calc(100vh-64px)] overflow-y-auto p-4">
        {props.activeTab === 'ai' ? (
          <div className="space-y-5">
            <div className="rounded-2xl bg-slate-50 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500">Selected slide</div>
              <div className="mt-2 font-semibold text-slate-900">{props.slideTitle}</div>
              <div className="mt-1 text-sm capitalize text-slate-600">{props.slidePurpose}</div>
            </div>
            <div className="space-y-2">
              {actions.map((action) => (
                <button
                  key={action}
                  type="button"
                  onClick={() => props.onAction(action)}
                  disabled={props.actionLoading !== null}
                  className="w-full rounded-xl border border-slate-200 px-4 py-3 text-left text-sm text-slate-800 disabled:opacity-60"
                >
                  {props.actionLoading === action ? 'Working…' : action}
                </button>
              ))}
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">Generation history</div>
              <div className="mt-3 flex flex-wrap gap-2">
                {props.history.slice(0, 3).map((entry) => (
                  <span key={entry} className="rounded-full bg-indigo-50 px-3 py-1 text-xs text-indigo-700">
                    {entry}
                  </span>
                ))}
              </div>
            </div>
          </div>
        ) : null}

        {props.activeTab === 'design' ? (
          <div className="space-y-5">
            <div>
              <div className="mb-3 text-xs uppercase tracking-wide text-slate-500">Template</div>
              <div className="grid gap-3">
                {props.templates.map((template) => (
                  <button
                    key={template.id}
                    type="button"
                    onClick={() => props.onTemplateSelect(template.id)}
                    className={`rounded-2xl border p-3 text-left ${
                      props.selectedTemplateId === template.id ? 'border-indigo-500 bg-indigo-50' : 'border-slate-200'
                    }`}
                  >
                    <div className="font-medium text-slate-900">{template.name}</div>
                    <div className="text-sm text-slate-500">{template.alias}</div>
                  </button>
                ))}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500">Brand kit</div>
              <div className="mt-4 space-y-3 text-sm">
                <div className="flex items-center justify-between">
                  <span>Primary</span>
                  <div className="flex items-center gap-3">
                    <span>{props.brandKit.primary}</span>
                    <span className="h-5 w-5 rounded-full ring-1 ring-slate-200" style={{ backgroundColor: props.brandKit.primary }} />
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span>Accent</span>
                  <div className="flex items-center gap-3">
                    <span>{props.brandKit.accent}</span>
                    <span className="h-5 w-5 rounded-full ring-1 ring-slate-200" style={{ backgroundColor: props.brandKit.accent }} />
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span>Fonts</span>
                  <span>{props.brandKit.fontPair}</span>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {props.activeTab === 'data' ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
            Connect a data source
          </div>
        ) : null}
      </div>
    </aside>
  )
}
