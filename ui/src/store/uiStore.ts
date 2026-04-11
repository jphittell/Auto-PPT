import { create } from 'zustand'

type ToastType = 'info' | 'success' | 'error'

export interface ToastMessage {
  id: string
  message: string
  type: ToastType
}

interface UIStore {
  toasts: ToastMessage[]
  addToast: (message: string, type?: ToastType) => void
  dismissToast: (id: string) => void
}

export const useUIStore = create<UIStore>((set) => ({
  toasts: [],
  addToast: (message, type = 'info') =>
    set((state) => ({
      toasts: [...state.toasts, { id: `${Date.now()}-${Math.random()}`, message, type }],
    })),
  dismissToast: (id) => set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
}))
