import { Cpu, ExternalLink, Layers3 } from 'lucide-react'
import { models } from '../mock/data'
import { PageHeader, StatusBadge } from '../components/Layout'

export function ModelsPage() {
  return <><PageHeader eyebrow="模型注册表" title="模型库" description="所有模型遵循统一的 encode / decode / metrics 接口，便于公平比较。" action={<StatusBadge tone="blue">5 个已接入</StatusBadge>} /><section className="model-grid">{models.map((model) => <article className="panel model-card" key={model.id}><div className="model-card-head"><div className="model-badge" style={{ background: `${model.accent}18`, color: model.accent }}><Layers3 size={19} /></div><StatusBadge tone={model.status === 'ready' ? 'green' : model.status === 'adapter' ? 'blue' : 'slate'}>{model.status === 'ready' ? '可运行' : model.status === 'adapter' ? '适配器' : '计划中'}</StatusBadge></div><div className="model-title"><h2>{model.name}</h2><span>{model.milestone}</span></div><span className="model-family">{model.family}</span><p>{model.description}</p><div className="model-detail"><Cpu size={15} /> {model.detail}</div><div className="model-footer"><span><small>嵌入 PSNR</small><strong>{model.psnr}</strong></span><span><small>鲁棒性</small><strong>{model.robustness}</strong></span><button className="icon-button" aria-label="查看模型详情"><ExternalLink size={15} /></button></div></article>)}</section></>
}
