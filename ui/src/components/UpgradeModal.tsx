import { ModalFrame } from './ModalFrame'

interface UpgradeModalProps {
  open: boolean
  onClose: () => void
  onExportPdf: () => void
}

export function UpgradeModal({ open, onClose, onExportPdf }: UpgradeModalProps) {
  return (
    <ModalFrame open={open} onClose={onClose} title="PPTX export is a Pro feature">
      <div className="space-y-4 text-sm text-slate-700">
        <p>Your deck is ready. Upgrade to download a fully editable PowerPoint file.</p>
        <ul className="list-disc space-y-2 pl-5">
          <li>Native text boxes and shapes</li>
          <li>Fonts and colors preserved</li>
          <li>Opens in PowerPoint and Google Slides</li>
        </ul>
        <div className="flex flex-col gap-3 pt-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl bg-indigo-600 px-4 py-2 font-medium text-white"
          >
            Upgrade to Pro — $29/mo
          </button>
          <button type="button" onClick={onExportPdf} className="rounded-xl border border-slate-200 px-4 py-2">
            Export as PDF instead
          </button>
        </div>
      </div>
    </ModalFrame>
  )
}
