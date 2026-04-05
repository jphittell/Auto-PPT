import { useRef, useState } from 'react'

interface FileDropzoneProps {
  accept: string
  loading?: boolean
  onFileSelect: (file: File) => void
}

export function FileDropzone({ accept, loading = false, onFileSelect }: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [status, setStatus] = useState('Drop a file here or press Enter to browse.')
  const [selectedName, setSelectedName] = useState<string | null>(null)

  function handleFile(file: File | null) {
    if (!file) return
    setSelectedName(`${file.name} (${Math.max(1, Math.round(file.size / 1024))} KB)`)
    setStatus(`Uploading ${file.name}`)
    onFileSelect(file)
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          inputRef.current?.click()
        }
      }}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault()
        handleFile(event.dataTransfer.files?.[0] ?? null)
      }}
      className="rounded-3xl border-2 border-dashed border-indigo-300 bg-indigo-50/60 p-10 text-center outline-none transition hover:border-indigo-500 focus:border-indigo-500"
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
      />
      <div aria-live="polite" className="mx-auto max-w-lg space-y-3">
        <p className="text-lg font-semibold text-slate-900">Drag and drop a document</p>
        <p className="text-sm text-slate-600">Accepts .pdf, .txt, and .md</p>
        {selectedName ? <p className="text-sm text-slate-800">{selectedName}</p> : null}
        <p className="text-xs text-slate-500">{loading ? 'Processing upload…' : status}</p>
      </div>
    </div>
  )
}
