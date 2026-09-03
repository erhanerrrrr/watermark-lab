import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { AttacksPage } from './pages/AttacksPage'
import { DashboardPage } from './pages/DashboardPage'
import { DatasetsPage } from './pages/DatasetsPage'
import { ExperimentPage } from './pages/ExperimentPage'
import { ModelsPage } from './pages/ModelsPage'
import { ResultsPage } from './pages/ResultsPage'

export default function App() {
  return <BrowserRouter><Routes><Route element={<Layout />}><Route path="/" element={<DashboardPage />} /><Route path="/experiment" element={<ExperimentPage />} /><Route path="/results" element={<ResultsPage />} /><Route path="/datasets" element={<DatasetsPage />} /><Route path="/models" element={<ModelsPage />} /><Route path="/attacks" element={<AttacksPage />} /></Route></Routes></BrowserRouter>
}
