import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Layers, ShieldAlert, SlidersHorizontal } from 'lucide-react'
import { ApiRequired, PageHeader, StatusBadge } from '../components/Layout'
import { useApi } from '../services/ApiContext'
import type { AttackCaseInfo } from '../types'

type CategoryFilter = 'all' | AttackCaseInfo['category']

const categoryName = { control: '控制', single: '单项攻击', compound: '组合攻击' }

function formatStep(step: AttackCaseInfo['pipeline'][number]): string {
  const parameters = Object.entries(step.parameters)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(', ')
  return parameters ? `${step.name} (${parameters})` : step.name
}

export function AttacksPage() {
  const { catalog } = useApi()
  const [filter, setFilter] = useState<CategoryFilter>('all')
  const cases = useMemo(() => catalog?.protocol.cases.filter((item) => filter === 'all' || item.category === filter) ?? [], [catalog, filter])
  if (!catalog) return <ApiRequired />

  const counts = Object.fromEntries(['control', 'single', 'compound'].map((category) => [category, catalog.protocol.cases.filter((item) => item.category === category).length]))
  return <>
    <PageHeader eyebrow="鲁棒性评估 · formal-v1" title="冻结攻击协议" description={`以下 ${catalog.protocol.cases.length} 条流水线用于 formal-v1 四种方法的总体比较。`} action={<StatusBadge tone="blue">{catalog.protocol.id} v{catalog.protocol.version} · seed {catalog.protocol.seed}</StatusBadge>} />
    <p className="research-scope-note">Budget-WAM 通过 geometry-v3 单独验证几何恢复与搜索成本。<Link className="text-button" to="/results#geometry-v3">查看几何攻击家族与六种对照 →</Link></p>
    <section className="attack-banner"><div className="attack-banner-icon"><ShieldAlert size={24} /></div><div><strong>正式协议已锁定</strong><p>共 {catalog.protocol.cases.length} 条：{counts.control} 条控制、{counts.single} 条单项、{counts.compound} 条组合；正式 test 结果不可回调参数。</p></div><div className="protocol-count"><strong>{catalog.protocol.cases.length}</strong><span>cases</span></div></section>
    <div className="filter-bar" aria-label="攻击类别筛选">{(['all', 'control', 'single', 'compound'] as const).map((category) => <button key={category} className={`filter-button ${filter === category ? 'active' : ''}`} onClick={() => setFilter(category)}>{category === 'all' ? '全部' : categoryName[category]}{category !== 'all' && ` ${counts[category]}`}</button>)}</div>
    <section className="attack-grid">{cases.map((attack, index) => <article className="panel attack-card" key={attack.id}><div className="attack-number">{String(index + 1).padStart(2, '0')}</div><div className="attack-card-icon"><SlidersHorizontal size={18} /></div><div className="attack-card-copy"><div><h2>{attack.id}</h2><StatusBadge tone={attack.category === 'compound' ? 'amber' : attack.category === 'control' ? 'blue' : 'slate'}>{categoryName[attack.category]}</StatusBadge></div><p>{attack.pipeline.map(formatStep).join(' → ')}</p><span className="attack-strength">流水线长度：{attack.pipeline.length}</span></div></article>)}</section>
    <section className="panel protocol-panel"><div className="panel-heading"><div><span className="panel-kicker">执行顺序</span><h2>统一评估流水线</h2></div><Layers size={18} className="muted" /></div><div className="flow-row"><span>固定 manifest</span><ArrowRight size={16} /><span>公平 PSNR 校准</span><ArrowRight size={16} /><span className="flow-active">冻结攻击</span><ArrowRight size={16} /><span>盲提取与统计</span></div></section>
  </>
}
