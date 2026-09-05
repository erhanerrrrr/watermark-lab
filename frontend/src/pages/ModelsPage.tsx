import { ArrowUpRight, Cpu, Layers3, RefreshCw, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiRequired, PageHeader, StatusBadge } from '../components/Layout'
import { useApi } from '../services/ApiContext'
import { useGeometryEvidence } from '../services/useGeometryEvidence'

export function ModelsPage() {
  const { catalog } = useApi()
  const { evidence, loading, error, reload } = useGeometryEvidence()
  if (!catalog) return <ApiRequired />
  const available = catalog.models.filter((model) => model.available).length
  const models = [...catalog.models].sort((a, b) => Number(b.id === 'budget_wam') - Number(a.id === 'budget_wam'))
  const budget = evidence?.methods.find((row) => row.method === 'budget_wam')
  return <>
    <PageHeader
      eyebrow="模型注册表"
      title="模型库"
      description="运行状态随当前服务同步；四种方法使用 formal-v1 指标，Budget-WAM 使用独立 geometry-v3 验证。"
      action={<StatusBadge tone={available === models.length ? 'green' : 'amber'}>{available}/{models.length} 当前服务可运行</StatusBadge>}
    />
    <section className="model-grid">{models.map((model) => {
      const isBudget = model.id === 'budget_wam'
      const psnr = isBudget ? budget?.mean_psnr_db : model.formal_metrics?.embed_psnr_db
      const accuracy = isBudget ? budget?.bit_accuracy : model.formal_metrics?.bit_accuracy
      const recovery = isBudget ? budget?.complete_recovery : model.formal_metrics?.complete_recovery
      return <article className="panel model-card" key={model.id} style={{ '--accent': model.accent } as React.CSSProperties}>
        <div className="model-card-head">
          <div className="model-badge" style={{ background: `${model.accent}18`, color: model.accent }}><Layers3 size={19} /></div>
          <StatusBadge tone={model.available ? 'green' : 'amber'}>{model.available ? '当前可运行' : '暂不可用'}</StatusBadge>
        </div>
        <div className="model-card-copy">
          <div className="model-title"><h2>{model.display_name}</h2><span>{model.stage}</span></div>
          <span className="model-family">{model.family} · {model.role}</span>
          <p>{model.description}</p>
          <div className="model-detail"><Cpu size={15} /><span>{model.detail}</span></div>
          <div className="model-runtime"><Cpu size={14} /><span>{model.runtime_label || '当前服务'}</span></div>
          {model.reason && <div className="model-runtime warning"><TriangleAlert size={14} />{model.reason}</div>}
        </div>
        <div className="model-footer">
          <span><small>默认展示强度</small><strong>{model.default_strength}</strong></span>
          <span><small>鲁棒性定位</small><strong>{model.robustness}</strong></span>
          <span><small>嵌入 PSNR</small><strong>{psnr !== undefined ? `${psnr.toFixed(3)} dB` : isBudget ? '待读取证据' : '仅自检'}</strong></span>
        </div>
        <div className="model-evaluation">
          <span className="model-evaluation-source">{isBudget ? 'geometry-v3 · 独立测试' : model.formal_metrics ? 'formal-v1 · 正式测试' : '管线自检'}</span>
          {accuracy !== undefined && recovery !== undefined && <div className="model-metrics">
            <span>Bit Accuracy <strong>{(accuracy * 100).toFixed(2)}%</strong></span>
            <span>完整恢复 <strong>{(recovery * 100).toFixed(2)}%</strong></span>
          </div>}
          {isBudget && loading && <span className="model-evaluation-note" role="status">正在读取独立验证指标…</span>}
          {isBudget && error && <div className="model-runtime warning" role="alert"><span>{error}</span><button className="icon-button" onClick={reload} aria-label="重新读取模型证据"><RefreshCw size={14} /></button></div>}
          {isBudget && budget && evidence && <span className="model-evaluation-note">平均 {budget.mean_candidates.toFixed(2)} 次候选，上限 {evidence.policy.max_candidates} 次；误报图像 {budget.false_positive_images}/{budget.negative_images}。</span>}
          {!isBudget && !model.formal_metrics && <span className="model-evaluation-note">用于检查嵌入与提取流程。</span>}
          {isBudget && <Link className="text-button" to="/results#geometry-v3">查看六种对照、置信区间与适用边界 <ArrowUpRight size={14} /></Link>}
        </div>
      </article>
    })}</section>
    <p className="evidence-note">两套实验使用不同图像与攻击协议，恢复率应在各自协议内比较。</p>
  </>
}
