import { useEffect, useMemo, useState } from 'react'
import { Download, RefreshCw } from 'lucide-react'
import { getResearchEvidence, researchEvidenceExportUrl } from '../services/api'
import { useApi } from '../services/ApiContext'
import type { ResearchEvidence as Evidence, ResearchEvidenceRow } from '../types'
import { StatusBadge } from './Layout'

const percent = (value: number) => `${(value * 100).toFixed(2)}%`
const signed = (value: number) => `${value > 0 ? '+' : ''}${value.toFixed(2)}`
const interval = (values: [number, number]) => `[${signed(values[0])}, ${signed(values[1])}]`
const categoryLabels: Record<string, string> = { all: '全部攻击', control: '无攻击对照', single: '单项攻击', compound: '组合攻击' }

interface IntervalItem {
  label: string
  mean: number
  bounds: [number, number]
}

function IntervalPlot({ items }: { items: IntervalItem[] }) {
  const values = items.flatMap((item) => [...item.bounds, item.mean])
  const minimum = Math.min(0, ...values)
  const maximum = Math.max(0, ...values)
  const padding = Math.max((maximum - minimum) * 0.12, 0.5)
  const lower = minimum - padding
  const upper = maximum + padding
  const x = (value: number) => 165 + ((value - lower) / (upper - lower)) * 330
  const height = 58 + items.length * 48
  return <svg className="evidence-interval-plot" viewBox={`0 0 620 ${height}`} role="img" aria-label={items.map((item) => `${item.label}：完整恢复率收益 ${signed(item.mean)} 个百分点，95% 置信区间 ${interval(item.bounds)}`).join('；')}>
    <title>AM-WAM 相对 WAM 的完整恢复率收益与 95% 置信区间</title>
    <line x1={x(0)} x2={x(0)} y1={10} y2={height - 34} className="evidence-zero" />
    {items.map((item, index) => {
      const y = 27 + index * 48
      return <g key={item.label}>
        <text x={0} y={y + 4} className="evidence-plot-label">{item.label}</text>
        <line x1={x(item.bounds[0])} x2={x(item.bounds[1])} y1={y} y2={y} className="evidence-ci" />
        {item.bounds.map((bound, edge) => <line key={edge} x1={x(bound)} x2={x(bound)} y1={y - 6} y2={y + 6} className="evidence-ci-cap" />)}
        <circle cx={x(item.mean)} cy={y} r={5} className="evidence-ci-point" />
        <text x={510} y={y + 4} className="evidence-plot-value">{signed(item.mean)} pp</text>
      </g>
    })}
    <line x1={165} x2={495} y1={height - 31} y2={height - 31} className="evidence-axis" />
    {[lower, 0, upper].map((tick, index) => <text key={index} x={x(tick)} y={height - 12} textAnchor="middle" className="evidence-tick">{tick.toFixed(1)}</text>)}
    <text x={510} y={height - 12} className="evidence-tick">百分点（pp）</text>
  </svg>
}

function PairedOutcomes({ row }: { row: ResearchEvidenceRow }) {
  const outcomes = [
    { label: '两者完整恢复', value: row.comparison.both_recovered, className: 'both' },
    { label: '仅 AM-WAM 恢复', value: row.comparison.rescued, className: 'rescued' },
    { label: '仅 WAM 恢复', value: row.comparison.regressed, className: 'regressed' },
    { label: '两者均未完整恢复', value: row.comparison.both_failed, className: 'failed' },
  ]
  return <div className="evidence-outcomes">
    <div className="evidence-outcome-bar" role="img" aria-label={outcomes.map((item) => `${item.label} ${item.value.toLocaleString()} 条`).join('；')}>
      {outcomes.map((item) => <span key={item.className} className={item.className} style={{ width: `${row.paired_records ? item.value / row.paired_records * 100 : 0}%` }} title={`${item.label}：${item.value.toLocaleString()}`} />)}
    </div>
    <div className="evidence-outcome-legend">{outcomes.map((item) => <div key={item.className}><i className={item.className} /><span>{item.label}</span><strong>{item.value.toLocaleString()}</strong></div>)}</div>
    <p className="evidence-note">计数单位为同一图像、消息和攻击条件下的配对记录；同一图像在多种攻击下会出现多次。</p>
  </div>
}

export function ResearchEvidence() {
  const { catalog } = useApi()
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [dataset, setDataset] = useState('all')
  const [attack, setAttack] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    getResearchEvidence()
      .then((result) => { if (active) setEvidence(result) })
      .catch((caught) => {
        if (active) {
          setEvidence(null)
          setError(caught instanceof Error ? caught.message : '研究证据读取失败。')
        }
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [revision])

  const attackOptions = useMemo(() => {
    const options = new Map<string, string>()
    for (const row of evidence?.rows ?? []) {
      if (row.dataset === dataset && row.attack !== 'all') options.set(row.attack, row.category)
    }
    return [...options].sort(([left], [right]) => left.localeCompare(right))
  }, [evidence, dataset])
  const row = evidence?.rows.find((item) => item.dataset === dataset && item.attack === attack)
  const overall = evidence?.rows.find((item) => item.dataset === 'all' && item.attack === 'all')
  const exclusion = evidence?.sensitivity.find((item) => item.excluded_attack === 'rotation_10')
  const datasetLabel = dataset === 'all' ? '全部数据集' : evidence?.datasets.find((item) => item.id === dataset)?.label ?? dataset

  return <section className="panel research-evidence" aria-labelledby="research-evidence-title">
    <div className="panel-heading">
      <div><span className="panel-kicker">研究证据 · 数据集 × 攻击 × 方法</span><h2 id="research-evidence-title">提升是否跨数据集成立？</h2></div>
      {evidence && <a className="secondary-button" href={researchEvidenceExportUrl()}><Download size={15} /> 下载证据 JSON</a>}
    </div>
    {loading && <div className="page-state inline" role="status"><span className="status-dot checking" />正在读取研究证据…</div>}
    {error && <div className="evidence-error" role="alert"><p>{error}</p><button className="secondary-button" onClick={() => setRevision((value) => value + 1)}><RefreshCw size={14} />重新读取证据</button></div>}
    {evidence && !loading && <>
      <p className="evidence-intro">{evidence.images.toLocaleString()} 张 test 图像、{evidence.attacks} 条冻结攻击、{evidence.records.toLocaleString()} 条四方法记录。按相同样本比较恢复收益，置信区间以图像为重采样单位。</p>
      <div className="evidence-controls">
        <label className="field-label">数据集<select value={dataset} onChange={(event) => {
          const nextDataset = event.target.value
          setDataset(nextDataset)
          if (!evidence.rows.some((item) => item.dataset === nextDataset && item.attack === attack)) setAttack('all')
        }}><option value="all">全部数据集 · {evidence.images} 张</option>{evidence.datasets.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.images} 张</option>)}</select></label>
        <label className="field-label">攻击条件<select value={attack} onChange={(event) => setAttack(event.target.value)}><option value="all">全部冻结攻击</option>{attackOptions.map(([id, category]) => <option key={id} value={id}>{categoryLabels[category] ?? category} · {id}</option>)}</select></label>
      </div>
      {row ? <div aria-live="polite">
        <div className="evidence-selection"><strong>{datasetLabel} · {attack === 'all' ? '全部冻结攻击' : attack}</strong><StatusBadge tone="blue">{row.images.toLocaleString()} 张图像 · {row.paired_records.toLocaleString()} 对记录</StatusBadge></div>
        <div className="table-scroll"><table className="evidence-model-table"><caption>当前条件下四种方法的恢复表现与代价</caption><thead><tr><th scope="col">方法</th><th scope="col">完整恢复率</th><th scope="col">Bit Accuracy</th><th scope="col">嵌入 PSNR</th><th scope="col">解码时间 / 设备</th></tr></thead><tbody>{row.models.map((model) => <tr key={model.id} className={model.id === 'am_wam' ? 'selected-row' : ''}><th scope="row">{catalog?.models.find((item) => item.id === model.id)?.display_name ?? model.id}</th><td><div className="evidence-recovery"><strong>{percent(model.complete_recovery)}</strong><span className="evidence-recovery-track"><span style={{ width: `${model.complete_recovery * 100}%` }} /></span></div></td><td>{percent(model.bit_accuracy)}</td><td>{model.embed_psnr_db.toFixed(2)} dB</td><td>{model.decode_ms.toFixed(1)} ms<small>{model.id === 'wam' || model.id === 'am_wam' ? 'GPU · RTX 4070 Laptop' : 'CPU'}</small></td></tr>)}</tbody></table></div>
        <p className="evidence-note">CPU 与 GPU 的耗时对应各自正式实验环境，不能据此作统一速度排名；PSNR 为攻击前的嵌入图像质量。</p>
        <div className="evidence-comparison">
          <div className="evidence-gain"><span>AM-WAM − WAM · 完整恢复率</span><strong className={row.comparison.recovery_gain_pp < 0 ? 'negative' : ''}>{signed(row.comparison.recovery_gain_pp)} <small>pp</small></strong><p>95% CI {interval(row.comparison.recovery_ci95_pp)} pp</p><p>Bit Accuracy {signed(row.comparison.bit_accuracy_gain_pp)} pp · 解码耗时 {signed(row.comparison.decode_overhead_ms)} ms</p></div>
          <PairedOutcomes row={row} />
        </div>
      </div> : <div className="empty-state">该组合暂无冻结证据，请选择其他数据集或攻击。</div>}
      <div className="evidence-sensitivity">
        <div><span className="panel-kicker">敏感性分析 · 固定全部数据集</span><h3>去掉 10° 旋转后，收益还在吗？</h3><p className="evidence-note">比较全部攻击与移除 rotation_10 后的平均收益，检查结论对单项攻击的依赖。横线表示图像级 bootstrap 95% 置信区间，虚线为零收益。</p></div>
        {overall && exclusion ? <>
          <IntervalPlot items={[
            { label: '全部冻结攻击', mean: overall.comparison.recovery_gain_pp, bounds: overall.comparison.recovery_ci95_pp },
            { label: '移除 rotation_10', mean: exclusion.recovery_gain_pp, bounds: exclusion.recovery_ci95_pp },
          ]} />
          <p className="evidence-note">移除后：{exclusion.images.toLocaleString()} 张图像、{exclusion.paired_records.toLocaleString()} 对记录；完整恢复率收益 {signed(exclusion.recovery_gain_pp)} pp，95% CI {interval(exclusion.recovery_ci95_pp)} pp。本分析保持全部数据集，不随上方筛选变化。</p>
        </> : <p className="evidence-note">尚无移除 rotation_10 的冻结敏感性结果。</p>}
      </div>
      <details className="evidence-provenance"><summary>证据来源、重采样方法与结论边界</summary><p>{evidence.suite_id} · 图像级 bootstrap {evidence.bootstrap_iterations.toLocaleString()} 次 · 生成时间 {new Date(evidence.generated_at).toLocaleString()}</p><ul>{evidence.notes.map((note, index) => <li key={index}>{note}</li>)}</ul><p>以下摘要对应生成此证据快照时的输入文件，可在下载的 JSON 中核对。</p><dl>{evidence.provenance.map((item) => <div key={item.path}><dt>{item.path}</dt><dd>SHA-256 <code>{item.sha256}</code></dd></div>)}</dl></details>
    </>}
  </section>
}
