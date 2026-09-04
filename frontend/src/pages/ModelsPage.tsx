import { Cpu, Layers3, TriangleAlert } from 'lucide-react'
import { ApiRequired, PageHeader, StatusBadge } from '../components/Layout'
import { useApi } from '../services/ApiContext'

export function ModelsPage() {
  const { catalog } = useApi()
  if (!catalog) return <ApiRequired />
  const available = catalog.models.filter((model) => model.available).length
  return <>
    <PageHeader eyebrow="模型注册表" title="模型库" description="运行能力来自当前 Python 环境；正式指标来自冻结 formal-v1 结果。" action={<StatusBadge tone={available === catalog.models.length ? 'green' : 'amber'}>{available}/{catalog.models.length} 当前环境可运行</StatusBadge>} />
    <section className="model-grid">{catalog.models.map((model) => <article className="panel model-card" key={model.id} style={{ '--accent': model.accent } as React.CSSProperties}><div className="model-card-head"><div className="model-badge" style={{ background: `${model.accent}18`, color: model.accent }}><Layers3 size={19} /></div><StatusBadge tone={model.available ? 'green' : 'amber'}>{model.available ? '当前可运行' : '当前环境不可用'}</StatusBadge></div><div className="model-title"><h2>{model.display_name}</h2><span>{model.stage}</span></div><span className="model-family">{model.family} · {model.role}</span><p>{model.description}</p><div className="model-detail"><Cpu size={15} /> {model.detail}</div>{model.reason && <div className="model-runtime warning"><TriangleAlert size={14} />{model.reason}</div>}<div className="model-footer"><span><small>默认展示强度</small><strong>{model.default_strength}</strong></span><span><small>鲁棒性定位</small><strong>{model.robustness}</strong></span><span><small>正式 PSNR</small><strong>{model.formal_metrics ? `${model.formal_metrics.embed_psnr_db.toFixed(3)} dB` : '仅自检'}</strong></span></div>{model.formal_metrics && <div className="model-metrics"><span>Bit Accuracy <strong>{(model.formal_metrics.bit_accuracy * 100).toFixed(2)}%</strong></span><span>完整恢复 <strong>{(model.formal_metrics.complete_recovery * 100).toFixed(2)}%</strong></span></div>}</article>)}</section>
  </>
}
