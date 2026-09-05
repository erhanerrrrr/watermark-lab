const reasons: Record<string, string> = {
  insufficient_watermark_evidence: '水印证据不足，结束搜索',
  reliable_identity: '原图证据可靠，直接返回',
  reliable_correction: '校正分支达到可靠性条件',
  candidate_budget_exhausted: '达到候选预算，返回当前最佳结果',
  all_candidates_evaluated: '全部候选已评估',
}

interface Trace {
  budget_wam: boolean
  candidate_count: number
  candidate_budget: number
  selected_transform: string
  stop_reason: string
  detection_fraction_threshold: number
  geometry_branches: { name: string; score: number; selected_fraction: number; minimum_margin: number }[]
}

export function GeometryDecision({ metadata }: { metadata: Record<string, unknown> }) {
  const value = metadata.decode
  if (!value || typeof value !== 'object' || !('budget_wam' in value)) return null
  const trace = value as Trace
  if (!Array.isArray(trace.geometry_branches)) return null
  return <section className="panel research-evidence">
    <div className="panel-heading"><div><span className="panel-kicker">本次推理过程</span><h2>Budget-WAM 如何做出选择</h2></div><strong>{trace.candidate_count} / {trace.candidate_budget} 次候选调用</strong></div>
    <p className="evidence-intro">{reasons[trace.stop_reason] ?? trace.stop_reason}。选中 <code>{trace.selected_transform}</code>；候选预算限制模型调用次数。</p>
    <div className="table-scroll"><table className="evidence-model-table"><thead><tr><th>执行顺序 / 候选</th><th>分支评分</th><th>检测区域占比</th><th>最弱 bit 间隔</th></tr></thead><tbody>{trace.geometry_branches.map((branch, index) => <tr key={branch.name} className={branch.name === trace.selected_transform ? 'selected-row' : ''}><th scope="row">{index + 1}. {branch.name}</th><td>{branch.score.toFixed(4)}</td><td>{(branch.selected_fraction * 100).toFixed(2)}%</td><td>{branch.minimum_margin.toFixed(3)}</td></tr>)}</tbody></table></div>
    <p className="evidence-note">检测采用 geometry-v3 校准集冻结的区域占比阈值 {(trace.detection_fraction_threshold * 100).toFixed(2)}%。评分和 bit 间隔用于搜索决策，不是消息正确概率。研究验证使用最长边 ≤ 1024、嵌入 PSNR 约 40 dB 的图像；误报结果对应所列测试条件。</p>
  </section>
}
