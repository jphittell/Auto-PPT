import { useRef, useState } from 'react'

interface FileDropzoneProps {
  accept: string
  loading?: boolean
  multiple?: boolean
  onFilesSelect: (files: File[]) => void
}

export function FileDropzone({ accept, loading = false, multiple = false, onFilesSelect }: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [status, setStatus] = useState('Drop files here or press Enter to browse.')
  const [selectedNames, setSelectedNames] = useState<string[]>([])

  function handleFiles(files: FileList | File[] | null | undefined) {
    const nextFiles = files ? Array.from(files) : []
    if (nextFiles.length === 0) return
    setSelectedNames(nextFiles.map((file) => `${file.name} (${Math.max(1, Math.round(file.size / 1024))} KB)`))
    setStatus(`Uploading ${nextFiles.length} document${nextFiles.length === 1 ? '' : 's'}`)
    onFilesSelect(nextFiles)
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
        handleFiles(event.dataTransfer.files)
      }}
      className="rounded-3xl border-2 border-dashed border-indigo-300 bg-indigo-50/60 p-10 text-center outline-none transition hover:border-indigo-500 focus:border-indigo-500"
    >
      <input
        ref={inputRef}
        type="file"
        multiple={multiple}
        accept={accept}
        className="hidden"
        onChange={(event) => handleFiles(event.target.files)}
      />
      <div aria-live="polite" className="mx-auto max-w-lg space-y-3">
        <p className="text-lg font-semibold text-slate-900">Drag and drop one or more documents</p>
        <p className="text-sm text-slate-600">Accepts .pdf, .txt, and .md</p>
        {selectedNames.length > 0 ? (
          <div className="space-y-1 text-sm text-slate-800">
            {selectedNames.map((name) => (
              <p key={name}>{name}</p>
            ))}
          </div>
        ) : null}
        <p className="text-xs text-slate-500">{loading ? 'Processing upload...' : status}</p>
      </div>
    </div>
  )
}
