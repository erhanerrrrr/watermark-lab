import { useEffect, useState } from 'react'
import { Download, RefreshCw } from 'lucide-react'
import { geometryEvidenceExportUrl } from '../services/api'
import { useGeometryEvidence } from '../services/useGeometryEvidence'
import { StatusBadge } from './Layout'

const percent = (value: number) => `${(value * 100).toFixed(2)}%`
const signed = (value: number) => `${value > 0 ? '+' : ''}${value.toFixed(2)}`
const interval = (value: [number, number]) => `[${signed(value[0])}, ${signed(value[1])}]`
const methods: Record<string, string> = {
  wam_fixed: 'B0 · WAM 固定嵌入',
  adaptive_identity: 'B1 · 自适应嵌入 + 原图解码',
  legacy_am: '原 AM-WAM · 边框门控',
  full_best: 'B2 · 完整搜索 + 最佳分支',
  full_soft: 'B3 · 完整搜索 + 融合',
  budget_wam: 'B4 · Budget-WAM',
}
const families: Record<string, string> = {
  control: '无攻击', non_geometry: '非几何攻击', median: '中值填充', black: '黑色填充',
  reflect: '反射填充', crop_resize: '裁边缩放', compound: '旋转 + JPEG', perspective: '透视',
}
const datasets: Record<string, string> = {
  coco: 'COCO', div2k: 'DIV2K', diffusiondb: 'DiffusionDB', w_bench: 'W-Bench',
}
const stops: Record<string, string> = {
  insufficient_watermark_evidence: '水印证据不足', reliable_identity: '原图证据可靠',
  reliable_correction: '校正证据可靠', candidate_budget_exhausted: '达到预算',
  all_candidates_evaluated: '全部候选已评估',
}

export function GeometryEvidence() {
  const { evidence, error, loading, reload } = useGeometryEvidence()
  const [baseline, setBaseline] = useState('legacy_am')
  const [dimension, setDimension] = useState<'family' | 'dataset'>('family')
  useEffect(() => {
    if (!loading && evidence && window.location.hash === '#geometry-v3') {
      document.getElementById('geometry-v3')?.scrollIntoView({ block: 'start' })
    }
  }, [evidence, loading])

  const budget = evidence?.methods.find((row) => row.method === 'budget_wam')
  const primary = evidence?.paired.find((row) => row.baseline === 'full_best')
  const rows = (dimension === 'family'
    ? evidence?.by_family.map((row) => ({ ...row, label: families[row.family] ?? row.family }))
    : evidence?.by_dataset.map((row) => ({ ...row, label: datasets[row.dataset] ?? row.dataset }))
  )?.filter((row) => row.baseline === baseline) ?? []

  return <section className="panel research-evidence geometry-evidence" id="geometry-v3" aria-labelledby="geometry-v3-title">
    <div className="panel-heading">
      <div><span className="panel-kicker">geometry-v3 · 新图像独立验证</span><h2 id="geometry-v3-title">几何校正的恢复收益与搜索成本</h2></div>
      {evidence && <a className="secondary-button" href={geometryEvidenceExportUrl()}><Download size={15} />下载 v3 证据</a>}
    </div>
    {loading && <div className="page-state inline" role="status">正在读取 geometry-v3 冻结证据…</div>}
    {error && <div className="evidence-error" role="alert"><p>{error}</p><button className="secondary-button" onClick={reload}><RefreshCw size={14} />重新读取</button></div>}
    {evidence && budget && primary && !loading && <>
      <p className="evidence-intro">先用 {evidence.calibration_images} 张新图校准并冻结策略，再测试 {evidence.test_images} 张新图 × {evidence.attack_cases} 项攻击。六种对照覆盖嵌入、校正、融合与预算策略；B1–B4 和原 AM 门控共享同一嵌入及攻击图。图像最长边为 {evidence.max_input_side}，本轮采用独立协议。</p>
      <div className="geometry-kpis">
        <div><span>Budget-WAM 完整恢复</span><strong>{percent(budget.complete_recovery)}</strong><small>{evidence.positive_records_per_method.toLocaleString()} 条正样本记录</small></div>
        <div><span>平均候选调用 / 完整搜索</span><strong>{budget.mean_candidates.toFixed(2)} / 10</strong><small>单次预算上限 {evidence.policy.max_candidates}</small></div>
        <div><span>相对完整搜索 · 最佳分支</span><strong>{signed(primary.recovery_gain_pp)} pp</strong><small>图像级 95% CI {interval(primary.ci95_pp)} pp</small></div>
        <div><span>误报图像 / 负样本图像</span><strong>{budget.false_positive_images} / {budget.negative_images}</strong><small>95% CI {percent(budget.false_positive_image_ci95[0])}–{percent(budget.false_positive_image_ci95[1])}</small></div>
      </div>
      <div className="geometry-criteria">
        <StatusBadge tone={evidence.test_criteria.recovery_point_target_met ? 'green' : 'amber'}>恢复下降 ≤ {evidence.test_criteria.recovery_tolerance_pp} pp：{evidence.test_criteria.recovery_point_target_met ? '点估计达标' : '点估计未达标'}</StatusBadge>
        <StatusBadge tone={evidence.test_criteria.candidate_target_met ? 'green' : 'amber'}>平均调用 ≤ 7：{evidence.test_criteria.candidate_target_met ? '达标' : '未达标'}</StatusBadge>
        <StatusBadge tone={evidence.test_criteria.noninferiority_ci_supported ? 'green' : 'amber'}>{evidence.test_criteria.noninferiority_ci_supported ? '置信区间支持预设非劣界限' : '置信区间尚不支持统计非劣'}</StatusBadge>
      </div>
      <div className="table-scroll"><table className="evidence-model-table">
        <caption>六种方法 · 相同测试图像与攻击协议</caption>
        <thead><tr><th>方法</th><th>完整恢复</th><th>Bit Accuracy</th><th>嵌入 PSNR</th><th>平均调用</th><th>检测 TPR</th><th>误报图像 / 95% CI</th></tr></thead>
        <tbody>{evidence.methods.map((row) => <tr key={row.method} className={row.method === 'budget_wam' ? 'selected-row' : ''}>
          <th scope="row">{methods[row.method] ?? row.label}</th><td>{percent(row.complete_recovery)}</td><td>{percent(row.bit_accuracy)}</td><td>{row.mean_psnr_db.toFixed(2)} dB</td><td>{row.mean_candidates.toFixed(2)}</td><td>{percent(row.tpr)}</td><td>{row.false_positive_images}/{row.negative_images}<small>{percent(row.false_positive_image_ci95[0])}–{percent(row.false_positive_image_ci95[1])}</small></td>
        </tr>)}</tbody>
      </table></div>
      <p className="evidence-note">完整恢复率独立于检测判定。检测 TPR 使用各方法在校准负样本上冻结的阈值；每张负图在 {evidence.negative_attack_cases} 项条件中任一误报只计一次。{evidence.test_images} 张负图不足以验证 0.1% 误报率。</p>
      <div className="evidence-controls">
        <label className="field-label">对比维度<select value={dimension} onChange={(event) => setDimension(event.target.value as 'family' | 'dataset')}><option value="family">攻击家族 · 合并四个数据集</option><option value="dataset">数据集 · 合并全部攻击</option></select></label>
        <label className="field-label">Budget-WAM 对比基线<select value={baseline} onChange={(event) => setBaseline(event.target.value)}>{['legacy_am', 'full_best', 'full_soft'].map((name) => <option key={name} value={name}>{methods[name]}</option>)}</select></label>
      </div>
      <div className="table-scroll" aria-live="polite"><table className="evidence-model-table">
        <caption>Budget-WAM − {methods[baseline]} · 完整恢复率差值（百分点）</caption>
        <thead><tr><th>{dimension === 'family' ? '攻击家族' : '数据集'}</th><th>Budget-WAM</th><th>所选基线</th><th>恢复率差值</th><th>图像级 95% CI</th><th>救回 / 退化</th><th>图像 / 配对记录</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.label}><th scope="row">{row.label}</th><td>{percent(row.budget_recovery)}</td><td>{percent(row.baseline_recovery)}</td><td className={row.recovery_gain_pp < 0 ? 'geometry-loss' : 'geometry-gain'}>{signed(row.recovery_gain_pp)} pp</td><td>{interval(row.ci95_pp)} pp</td><td>{row.rescued} / {row.regressed}</td><td>{row.image_units} / {row.paired_records}</td></tr>)}</tbody>
      </table></div>
      <div className="evidence-sensitivity">
        <details className="evidence-provenance"><summary>提前停止发生在哪里？</summary><p>按正样本的实际停止原因分组。救回与退化均对比完整搜索最佳分支，各组难度不同，组内恢复率不能解释为停止原因的因果作用。</p><div className="table-scroll"><table className="evidence-model-table"><thead><tr><th>停止原因</th><th>记录数</th><th>平均调用</th><th>组内恢复率</th><th>救回 / 退化</th></tr></thead><tbody>{evidence.decision_audit.map((row) => <tr key={row.stop_reason}><th scope="row">{stops[row.stop_reason] ?? row.stop_reason}</th><td>{row.records}</td><td>{row.mean_candidates.toFixed(2)}</td><td>{percent(row.complete_recovery)}</td><td>{row.rescued_vs_full_best} / {row.regressed_vs_full_best}</td></tr>)}</tbody></table></div></details>
        <h3>在线推理计时</h3>
        <p className="evidence-note">{evidence.timing.device} · 预定 {evidence.timing.image_units} 张 test 图 × {evidence.timing.measured_conditions / evidence.timing.image_units} 项攻击 × {evidence.timing.repetitions} 轮。各方法交替运行、GPU 同步，并逐位核验在线输出与轨迹重放一致。此子集与上方全测试集的条件分布不同。</p>
        <div className="table-scroll"><table className="evidence-model-table"><thead><tr><th>方法</th><th>均值</th><th>p50</th><th>p95</th><th>平均候选调用</th><th>显存峰值</th></tr></thead><tbody>{evidence.timing.methods.map((row) => <tr key={row.method} className={row.method === 'budget_wam' ? 'selected-row' : ''}><th scope="row">{methods[row.method]}</th><td>{row.mean_ms.toFixed(1)} ms</td><td>{row.p50_ms.toFixed(1)} ms</td><td>{row.p95_ms.toFixed(1)} ms</td><td>{row.mean_candidates.toFixed(2)}</td><td>{row.peak_cuda_allocated_mb.toFixed(0)} MB</td></tr>)}</tbody></table></div>
      </div>
      <details className="evidence-provenance"><summary>实验协议、来源与结论适用范围</summary><ul>{evidence.notes.map((note) => <li key={note}>{note}</li>)}</ul><p>校准目标：{evidence.calibration_targets_met ? '满足' : '未全部满足'}。生成时间：{new Date(evidence.generated_at).toLocaleString()}。</p><dl>{evidence.provenance.map((source) => <div key={source.path}><dt>{source.path}</dt><dd>SHA-256 <code>{source.sha256}</code></dd></div>)}</dl></details>
    </>}
  </section>
}
