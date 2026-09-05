import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Database, Download, FileCheck2, LoaderCircle, XCircle } from 'lucide-react'
import { ApiRequired, PageHeader, StatusBadge } from '../components/Layout'
import { manifestUrl, verifyDatasets } from '../services/api'
import { useApi } from '../services/ApiContext'
import type { DatasetVerification } from '../types'

export function DatasetsPage() {
  const { catalog } = useApi()
  const [verifying, setVerifying] = useState(false)
  const [reports, setReports] = useState<DatasetVerification[]>([])
  const [error, setError] = useState('')
  if (!catalog) return <ApiRequired />

  const verify = async () => {
    setVerifying(true); setError('')
    try { setReports(await verifyDatasets()) }
    catch (caught) { setError(caught instanceof Error ? caught.message : '数据校验失败。') }
    finally { setVerifying(false) }
  }
  const found = catalog.datasets.reduce((sum, dataset) => sum + dataset.found_images, 0)
  const expected = catalog.datasets.reduce((sum, dataset) => sum + dataset.expected_images, 0)
  return <>
    <PageHeader eyebrow="数据资产 · Debug / formal-v1" title="数据集与固定清单" description="本页管理 Debug 与 formal-v1 数据清单，检查文件状态并按需校验 SHA-256。" action={<button className="secondary-button" disabled={verifying} onClick={() => void verify()}>{verifying ? <LoaderCircle className="spin" size={16} /> : <FileCheck2 size={16} />} {verifying ? '正在校验…' : '校验本页清单 SHA-256'}</button>} />
    <p className="research-scope-note">Budget-WAM 使用 geometry-v3 独立图像划分，本页计数与校验范围为 Debug / formal-v1。<Link className="text-button" to="/results#geometry-v3">查看新方法的数据规模与跨数据集结果 →</Link></p>
    {error && <div className="form-message error">{error}</div>}
    {reports.length > 0 && <div className={`verification-banner ${reports.every((report) => report.valid) ? 'valid' : 'invalid'}`}>{reports.every((report) => report.valid) ? <CheckCircle2 size={18} /> : <XCircle size={18} />}<span>{reports.every((report) => report.valid) ? `完整性通过：${reports.reduce((sum, report) => sum + report.verified, 0)} 个文件 SHA-256 全部匹配。` : '发现缺失或摘要不匹配文件，请查看各数据集状态。'}</span></div>}
    <section className="dataset-summary"><div><span>来源数量</span><strong>{catalog.datasets.length}</strong><small>公开研究数据集</small></div><div><span>Debug10 样本</span><strong>{catalog.datasets.reduce((sum, item) => sum + item.counts.debug.expected, 0)}</strong><small>固定调试集合</small></div><div><span>Formal-v1</span><strong>{catalog.formal.test_images} + {catalog.formal.calibration_images}</strong><small>test + calibration</small></div><div><span>本地文件</span><strong>{found}/{expected}</strong><small>按相对路径检查</small></div></section>
    <section className="dataset-grid">{catalog.datasets.map((dataset) => {
      const report = reports.find((item) => item.id === dataset.id)
      const valid = report?.valid
      return <article className="panel dataset-card" key={dataset.id}><div className="dataset-card-top"><div className="dataset-icon"><Database size={20} /></div><StatusBadge tone={valid === false ? 'amber' : dataset.ready ? 'green' : 'slate'}>{valid === true ? 'SHA-256 通过' : valid === false ? '校验异常' : dataset.ready ? '文件已就绪' : '文件不完整'}</StatusBadge></div><h2>{dataset.display_name}</h2><p>{dataset.source}</p><div className="dataset-meta three"><span>Debug<strong>{dataset.counts.debug.found}/{dataset.counts.debug.expected}</strong></span><span>Calibration<strong>{dataset.counts.calibration.found}/{dataset.counts.calibration.expected}</strong></span><span>Test<strong>{dataset.counts.test.found}/{dataset.counts.test.expected}</strong></span></div><div className="progress large"><span style={{ width: `${dataset.progress}%` }} /></div>{report && !report.valid && <div className="dataset-warning">缺失 {report.missing.length}，摘要不匹配 {report.mismatched.length}</div>}<div className="dataset-footer"><small>许可：{dataset.license}</small><div className="manifest-links"><a className="text-button" href={manifestUrl(dataset.id, 'debug')}><Download size={12} /> Debug</a><a className="text-button" href={manifestUrl(dataset.id, 'calibration')}><Download size={12} /> Cal</a><a className="text-button" href={manifestUrl(dataset.id, 'test')}><Download size={12} /> Test</a></div></div></article>
    })}</section>
  </>
}
