import { Activity, ArrowUpRight, Beaker, CheckCircle2, Database, FileBarChart, Layers3, ShieldCheck, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ApiRequired, MetricCard, PageHeader, StatusBadge } from '../components/Layout'
import { GeometrySummary } from '../components/GeometrySummary'
import { useApi } from '../services/ApiContext'

const percent = (value: number) => `${(value * 100).toFixed(2)}%`

export function DashboardPage() {
  const { catalog, experiments } = useApi()
  if (!catalog) return <ApiRequired />

  const formalRows = catalog.models
    .filter((model) => model.formal_metrics)
    .map((model) => ({
      ...model,
      accuracy: (model.formal_metrics?.bit_accuracy ?? 0) * 100,
      recovery: (model.formal_metrics?.complete_recovery ?? 0) * 100,
    }))
  const best = formalRows.reduce((current, row) => row.recovery > current.recovery ? row : current)
  const source = catalog.formal.data_source === 'local_formal_results' ? '本地正式 CSV' : '版本化正式快照'

  return <>
    <PageHeader eyebrow={`研究控制台 · ${catalog.updated_at}`} title="实验总览" description="所有数字由本地 FastAPI 从冻结配置、manifest 与正式结果读取。" action={<Link className="primary-button" to="/experiment"><Beaker size={16} /> 新建实验</Link>} />
    <section className="metric-grid">
      <MetricCard label="当前可运行模型" value={String(catalog.models.filter((model) => model.available).length)} hint={`共接入 ${catalog.models.length} 个模型`} icon={Layers3} accent="blue" />
      <MetricCard label="本地数据资产" value={`${catalog.datasets.filter((dataset) => dataset.ready).length}/${catalog.datasets.length}`} hint={`${catalog.datasets.reduce((sum, item) => sum + item.found_images, 0)} 张已找到`} icon={Database} accent="violet" />
      <MetricCard label="正式实验记录" value={catalog.formal.records.toLocaleString()} hint={`${catalog.formal.test_images} test · ${catalog.formal.attack_cases} 条攻击`} icon={FileBarChart} accent="green" />
      <MetricCard label="formal-v1 最佳完整恢复率" value={`${best.recovery.toFixed(2)}%`} hint={`${best.display_name} · ${source}`} icon={Sparkles} accent="amber" />
    </section>
    <GeometrySummary />
    <section className="dashboard-grid">
      <div className="panel chart-panel">
        <div className="panel-heading"><div><span className="panel-kicker">冻结正式结果</span><h2>四种方法恢复性能</h2></div><span className="panel-meta">{source}</span></div>
        <div className="chart-wrap"><ResponsiveContainer width="100%" height={260}><BarChart data={formalRows} margin={{ top: 10, right: 10, left: -12, bottom: 0 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} /><XAxis dataKey="display_name" tickLine={false} axisLine={false} /><YAxis domain={[0, 105]} tickLine={false} axisLine={false} tickFormatter={(value) => `${value}%`} /><Tooltip formatter={(value) => `${Number(value).toFixed(2)}%`} /><Legend /><Bar dataKey="accuracy" name="Bit Accuracy" fill="#2563eb" radius={[4, 4, 0, 0]} isAnimationActive={false} /><Bar dataKey="recovery" name="完整恢复率" fill="#10b981" radius={[4, 4, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer></div>
      </div>
      <div className="panel activity-panel">
        <div className="panel-heading"><div><span className="panel-kicker">持久化记录</span><h2>最近实验</h2></div><Activity size={18} className="muted" /></div>
        <div className="activity-list">{experiments.length ? experiments.slice(0, 5).map((item) => <div className="activity-item" key={item.id}><div className="activity-icon"><CheckCircle2 size={16} /></div><div><strong>{catalog.models.find((model) => model.id === item.model)?.display_name ?? item.model} · {item.attack}</strong><span>{item.image_name} · {new Date(item.created_at).toLocaleString()}</span></div><StatusBadge tone={item.complete_recovery ? 'green' : 'amber'}>{percent(item.bit_accuracy)}</StatusBadge></div>) : <div className="empty-state compact">尚无交互实验记录。运行一次单图实验后会永久保存在本机。</div>}</div>
        <Link className="text-button" to="/results">查看全部结果 <ArrowUpRight size={14} /></Link>
      </div>
    </section>
    <section className="panel">
      <div className="panel-heading"><div><span className="panel-kicker">公平对比</span><h2>{catalog.formal.suite_id} 关键指标</h2></div><StatusBadge tone={catalog.formal.complete ? 'green' : 'amber'}>{catalog.formal.complete ? '完整性已通过' : '结果不完整'}</StatusBadge></div>
      <div className="table-scroll"><table><thead><tr><th>模型</th><th>检测率</th><th>Bit Accuracy</th><th>完整恢复率</th><th>嵌入 PSNR</th><th>运行设备说明</th></tr></thead><tbody>{formalRows.map((row) => <tr key={row.id}><td><div className="model-cell"><span className="model-dot" style={{ background: row.accent }} />{row.display_name}</div></td><td>{percent(row.formal_metrics!.detected)}</td><td><strong>{percent(row.formal_metrics!.bit_accuracy)}</strong></td><td>{percent(row.formal_metrics!.complete_recovery)}</td><td>{row.formal_metrics!.embed_psnr_db.toFixed(3)} dB</td><td>{row.id === 'wam' || row.id === 'am_wam' ? 'RTX 4070 Laptop' : 'CPU'}</td></tr>)}</tbody></table></div>
    </section>
    <section className="dashboard-bottom">
      <div className="panel mini-panel"><div className="panel-heading"><div><span className="panel-kicker">数据准备</span><h2>manifest 对应文件状态</h2></div><Database size={18} className="muted" /></div>{catalog.datasets.map((dataset) => <div className="progress-row" key={dataset.id}><div><span>{dataset.display_name}</span><small>{dataset.found_images} / {dataset.expected_images} 张</small></div><div className="progress"><span style={{ width: `${dataset.progress}%` }} /></div><em>{dataset.progress}%</em></div>)}</div>
      <div className="panel mini-panel highlight-panel"><div className="highlight-icon"><ShieldCheck size={22} /></div><div><span className="panel-kicker">冻结实验协议</span><h2>{catalog.protocol.id}</h2><p>固定随机种子 {catalog.protocol.seed} · {catalog.protocol.cases.length} 条攻击 · calibration/test 严格隔离。</p><Link className="text-button" to="/attacks">查看全部攻击 <ArrowUpRight size={14} /></Link></div></div>
    </section>
  </>
}
