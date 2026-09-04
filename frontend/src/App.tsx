import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ApiProvider } from './services/ApiContext'

const DashboardPage = lazy(() => import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })))
const ExperimentPage = lazy(() => import('./pages/ExperimentPage').then((module) => ({ default: module.ExperimentPage })))
const ResultsPage = lazy(() => import('./pages/ResultsPage').then((module) => ({ default: module.ResultsPage })))
const DatasetsPage = lazy(() => import('./pages/DatasetsPage').then((module) => ({ default: module.DatasetsPage })))
const ModelsPage = lazy(() => import('./pages/ModelsPage').then((module) => ({ default: module.ModelsPage })))
const AttacksPage = lazy(() => import('./pages/AttacksPage').then((module) => ({ default: module.AttacksPage })))

function LoadingPage() {
  return <div className="page-state"><span className="status-dot checking" />正在加载页面…</div>
}

export default function App() {
  return (
    <BrowserRouter>
      <ApiProvider>
        <Suspense fallback={<LoadingPage />}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/experiment" element={<ExperimentPage />} />
              <Route path="/results" element={<ResultsPage />} />
              <Route path="/datasets" element={<DatasetsPage />} />
              <Route path="/models" element={<ModelsPage />} />
              <Route path="/attacks" element={<AttacksPage />} />
              <Route path="*" element={<DashboardPage />} />
            </Route>
          </Routes>
        </Suspense>
      </ApiProvider>
    </BrowserRouter>
  )
}
