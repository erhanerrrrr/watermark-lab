import { useEffect, useMemo, useState } from 'react'
import { Download, RefreshCw, TrendingUp } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ApiRequired, PageHeader, StatusBadge } from '../components/Layout'
import { experimentExportUrl, getExperiment } from '../services/api'
import { useApi } from '../services/ApiContext'
import type { ApiExperimentDetail } from '../types'

export function ResultsPage() {
  const location = useLocation()
  const requestedId = (location.state as { experimentId?: string } | null)?.experimentId
  const { catalog, experiments, refreshExperiments } = useApi()
  const [detail, setDetail] = useState<ApiExperimentDetail | null>(null)
  const [selectedId, setSelectedId] = useState(requestedId ?? '')
  const [modelFilter, setModelFilter] = useState('')
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!selectedId && experiments.length) setSelectedId(experiments[0].id)
  }, [experiments, selectedId])
  useEffect(() => {
    if (!selectedId) { setDetail(null); return }
    setLoadingDetail(true); setError('')
    getExperiment(selectedId)
      .then(setDetail)
      .catch((caught) => setError(caught instanceof Error ? caught.message : '无法读取实验详情。'))
      .finally(() => setLoadingDetail(false))
  }, [selectedId])

  const visibleExperiments = useMemo(() => experiments.filter((item) => !modelFilter || item.model === modelFilter), [experiments, modelFilter])
  if (!catalog) return <ApiRequired />
  const formalRows = catalog.models.filter((model) => model.formal_metrics).map((model) => ({ name: model.display_name, bitAccuracy: model.formal_metrics!.bit_accuracy * 100, recovery: model.formal_metrics!.complete_recovery * 100 }))
  const best = catalog.formal.models.am_wam
  const source = catalog.formal.data_source === 'local_formal_results' ? '本地 formal-v1 CSV' : '版本化正式结果快照'

  return <>
    <PageHeader eyebrow="结果分析" title="实验结果与正式对比" description="交互实验来自持久化数据库；总体对比只读取冻结 formal-v1 数据源。" action={<a className={`secondary-button ${experiments.length ? '' : 'disabled'}`} href={experiments.length ? experimentExportUrl() : undefined} aria-disabled={!experiments.length}><Download size={16} /> 导出交互实验 CSV</a>} />
    {error && <div className="form-message error">{error}</div>}
    {loadingDetail && <div className="page-state inline"><span className="status-dot checking" />正在读取实验产物…</div>}
    {detail && !loadingDetail && <section className="panel real-result"><div className="panel-heading"><div><span className="panel-kicker">持久化真实实验</span><h2>{detail.id} · {catalog.models.find((model) => model.id === detail.model)?.display_name ?? detail.model}</h2></div><StatusBadge tone={detail.complete_recovery ? 'green' : 'amber'}>{detail.complete_recovery ? '消息完整恢复' : '消息未完整恢复'}</StatusBadge></div><div className="real-kpis"><div><span>嵌入 PSNR</span><strong>{detail.embed_psnr_db?.toFixed(2) ?? '∞'} dB</strong></div><div><span>嵌入 SSIM</span><strong>{detail.embed_ssim.toFixed(4)}</strong></div><div><span>Bit Accuracy</span><strong>{(detail.bit_accuracy * 100).toFixed(2)}%</strong></div><div><span>BER</span><strong>{(detail.ber * 100).toFixed(2)}%</strong></div><div><span>检测置信度</span><strong>{(detail.detection_confidence * 100).toFixed(2)}%</strong></div></div><div className="image-compare"><figure><img src={detail.artifacts.original} alt="原始图片" /><figcaption>原始图像</figcaption></figure><figure><img src={detail.artifacts.embedded} alt="嵌入水印图片" /><figcaption>嵌入水印 · {detail.encode_ms.toFixed(1)} ms</figcaption></figure><figure><img src={detail.artifacts.attacked} alt="攻击后图片" /><figcaption>攻击后 · {detail.attack} · 解码 {detail.decode_ms.toFixed(1)} ms</figcaption></figure></div><div className="message-compare"><span>预期消息 <code>{detail.expected_message}</code></span><span>提取消息 <code>{detail.decoded_message}</code></span><span>攻击参数 <code>{JSON.stringify(detail.attack_parameters)}</code></span></div></section>}
    {!detail && !loadingDetail && <div className="panel empty-state">尚无真实交互实验。请在“水印实验”页面上传图片并运行。</div>}
    <section className="result-kpis"><div><span>AM-WAM Bit Accuracy</span><strong>{(best.bit_accuracy * 100).toFixed(2)}%</strong><small className="positive">{source}</small></div><div><span>平均嵌入 PSNR</span><strong>{best.embed_psnr_db.toFixed(3)} dB</strong><small>目标质量约 {catalog.formal.target_psnr_db} dB</small></div><div><span>完整恢复率</span><strong>{(best.complete_recovery * 100).toFixed(2)}%</strong><small>相对 WAM +{catalog.formal.innovation.complete_recovery_gain_pp.toFixed(3)} pp</small></div><div><span>完整记录</span><strong>{catalog.formal.records.toLocaleString()}</strong><small>{catalog.formal.test_images} 图 × {catalog.formal.attack_cases} 攻击 × 4 模型</small></div></section>
    <section className="results-grid"><div className="panel chart-panel"><div className="panel-heading"><div><span className="panel-kicker">模型对比 · 冻结结果</span><h2>恢复率与准确率</h2></div><TrendingUp size={18} className="muted" /></div><div className="chart-wrap"><ResponsiveContainer width="100%" height={300}><BarChart data={formalRows} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} /><XAxis dataKey="name" tickLine={false} axisLine={false} /><YAxis domain={[0, 105]} tickLine={false} axisLine={false} tickFormatter={(value) => `${value}%`} /><Tooltip formatter={(value) => `${Number(value).toFixed(2)}%`} /><Legend /><Bar dataKey="bitAccuracy" name="Bit Accuracy" fill="#2563eb" radius={[4, 4, 0, 0]} isAnimationActive={false} /><Bar dataKey="recovery" name="完整恢复率" fill="#10b981" radius={[4, 4, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer></div></div><div className="panel insight-panel"><span className="panel-kicker">创新收益与边界</span><h2>AM-WAM 改善几何失配</h2><p>10° 旋转完整恢复率提高 {catalog.formal.innovation.rotation_10_gain_pp.toFixed(2)} 个百分点，重透视提高 {catalog.formal.innovation.perspective_heavy_gain_pp.toFixed(2)} 个百分点；平均解码额外增加约 {catalog.formal.innovation.decode_overhead_ms.toFixed(0)} ms。</p><div className="insight-stat"><strong>+{catalog.formal.innovation.rotation_10_gain_pp.toFixed(2)} pp</strong><span>10° 旋转完整恢复率提升</span></div><StatusBadge tone="amber">强模糊仍未改善</StatusBadge></div></section>
    <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">SQLite history</span><h2>交互实验记录</h2></div><div className="table-actions"><select aria-label="按模型筛选" value={modelFilter} onChange={(event) => setModelFilter(event.target.value)}><option value="">全部模型</option>{catalog.models.map((model) => <option key={model.id} value={model.id}>{model.display_name}</option>)}</select><button className="icon-button" onClick={() => void refreshExperiments()} aria-label="刷新记录" title="刷新"><RefreshCw size={16} /></button></div></div><div className="table-scroll"><table><thead><tr><th>实验 ID</th><th>模型 / 图片</th><th>攻击</th><th>PSNR</th><th>SSIM</th><th>BER</th><th>检测置信度</th><th>状态</th></tr></thead><tbody>{visibleExperiments.map((item) => <tr key={item.id} className={selectedId === item.id ? 'selected-row' : ''}><td><button className="table-link" onClick={() => setSelectedId(item.id)}>{item.id}</button><small>{new Date(item.created_at).toLocaleString()}</small></td><td><strong>{catalog.models.find((model) => model.id === item.model)?.display_name ?? item.model}</strong><small>{item.image_name}</small></td><td>{item.attack}</td><td>{item.embed_psnr_db?.toFixed(2) ?? '∞'} dB</td><td>{item.embed_ssim.toFixed(3)}</td><td>{(item.ber * 100).toFixed(2)}%</td><td>{(item.detection_confidence * 100).toFixed(2)}%</td><td><StatusBadge tone={item.complete_recovery ? 'green' : 'amber'}>{item.complete_recovery ? '完整恢复' : '部分恢复'}</StatusBadge></td></tr>)}</tbody></table>{!visibleExperiments.length && <div className="empty-state compact">当前筛选条件下没有记录。</div>}</div></section>
  </>
}
