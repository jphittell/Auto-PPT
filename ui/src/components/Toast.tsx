import { useEffect } from 'react'

import { useUIStore, type ToastMessage } from '../store/uiStore'

export function Toast({ toast }: { toast: ToastMessage }) {
  const dismissToast = useUIStore((state) => state.dismissToast)

  useEffect(() => {
    const timer = window.setTimeout(() => dismissToast(toast.id), 3000)
    return () => window.clearTimeout(timer)
  }, [dismissToast, toast.id])

  const tone =
    toast.type === 'success'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
      : toast.type === 'error'
        ? 'border-rose-200 bg-rose-50 text-rose-900'
        : 'border-slate-200 bg-white text-slate-900'

  return (
    <div className={`rounded-xl border px-4 py-3 shadow-panel ${tone}`} role="status">
      {toast.message}
    </div>
  )
}

export function ToastStack() {
  const toasts = useUIStore((state) => state.toasts)
  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-3">
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} />
      ))}
    </div>
  )
}
