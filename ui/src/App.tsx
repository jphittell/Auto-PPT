import { Route, Routes } from 'react-router-dom'

import { ToastStack } from './components/Toast'
import { EditorPage } from './pages/EditorPage'
import { GenerationWizardPage } from './pages/GenerationWizardPage'
import { HomePage } from './pages/HomePage'
import { TemplateGalleryPage } from './pages/TemplateGalleryPage'

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/new" element={<GenerationWizardPage />} />
        <Route path="/templates" element={<TemplateGalleryPage />} />
        <Route path="/editor/:deckId" element={<EditorPage />} />
      </Routes>
      <ToastStack />
    </>
  )
}
