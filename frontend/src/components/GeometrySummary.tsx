import { ArrowUpRight, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useGeometryEvidence } from '../services/useGeometryEvidence'

export function GeometrySummary() {
  const { evidence, loading, error, reload } = useGeometryEvidence()
  const budget = evidence?.methods.find((row) => row.method === 'budget_wam')
  const pair = evidence?.paired.find((row) => row.baseline === 'legacy_am')

  return <section className="panel research-evidence geometry-evidence">
    <div className="panel-heading">
      <div><span className="panel-kicker">geometry-v3 · 最新研究</span><h2>Budget-WAM：依据解码证据控制几何搜索</h2></div>
      <Link className="text-button" to="/results#geometry-v3">查看独立验证 <ArrowUpRight size={14} /></Link>
    </div>
    {loading && <p className="evidence-note" role="status">正在读取冻结研究证据…</p>}
    {error && <div className="evidence-error" role="alert"><p>{error}</p><button className="secondary-button" onClick={reload}><RefreshCw size={14} />重新读取</button></div>}
    {evidence && budget && pair && <>
      <div className="geometry-kpis">
        <div><span>完整恢复率</span><strong>{(budget.complete_recovery * 100).toFixed(2)}%</strong><small>{evidence.test_images} 张 test · {evidence.attack_cases} 项攻击</small></div>
        <div><span>相对同协议旧 AM 门控</span><strong>{pair.recovery_gain_pp > 0 ? '+' : ''}{pair.recovery_gain_pp.toFixed(2)} pp</strong><small>{evidence.calibration_images} 张 calibration 冻结策略</small></div>
        <div><span>平均候选调用</span><strong>{budget.mean_candidates.toFixed(2)} 次</strong><small>单次上限 {evidence.policy.max_candidates} 次</small></div>
        <div><span>误报图像</span><strong>{budget.false_positive_images}/{budget.negative_images}</strong><small>负样本图像级统计</small></div>
      </div>
      <p className="evidence-note">geometry-v3 独立于下方 formal-v1 总体比较；{evidence.test_criteria.noninferiority_ci_supported ? '置信区间支持预设非劣界限。' : '相对完整搜索的置信区间尚不支持预设统计非劣。'}</p>
    </>}
  </section>
}
