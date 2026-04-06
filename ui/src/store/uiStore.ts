import { create } from 'zustand'

type ToastType = 'info' | 'success' | 'error'

export interface ToastMessage {
  id: string
  message: string
  type: ToastType
}

interface UIStore {
  preflightModalOpen: boolean
  toasts: ToastMessage[]
  setPreflightModalOpen: (open: boolean) => void
  addToast: (message: string, type?: ToastType) => void
  dismissToast: (id: string) => void
}

export const useUIStore = create<UIStore>((set) => ({
  preflightModalOpen: false,
  toasts: [],
  setPreflightModalOpen: (preflightModalOpen) => set({ preflightModalOpen }),
  addToast: (message, type = 'info') =>
    set((state) => ({
      toasts: [...state.toasts, { id: `${Date.now()}-${Math.random()}`, message, type }],
    })),
  dismissToast: (id) => set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
}))
