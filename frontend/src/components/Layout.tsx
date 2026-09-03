import { NavLink, Outlet } from 'react-router-dom'
import { BarChart3, Beaker, Database, Gauge, Github, Menu, Network, ShieldCheck, Sparkles, X } from 'lucide-react'
import { useState } from 'react'

const navItems = [
  { to: '/', label: '总览 Dashboard', icon: Gauge, end: true },
  { to: '/experiment', label: '水印实验', icon: Beaker },
  { to: '/results', label: '实验结果', icon: BarChart3 },
  { to: '/datasets', label: '数据集', icon: Database },
  { to: '/models', label: '模型库', icon: Network },
  { to: '/attacks', label: '攻击协议', icon: ShieldCheck },
]

export function Layout() {
  const [open, setOpen] = useState(false)
  return (
    <div className="app-shell">
      <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}>
        <div className="brand"><div className="brand-mark"><Sparkles size={18} /></div><div><strong>Watermark Lab</strong><span>数字水印实验平台</span></div></div>
        <nav className="nav-list">{navItems.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><Icon size={18} /><span>{label}</span></NavLink>)}</nav>
        <div className="sidebar-bottom"><div className="status-line"><span className="status-dot" />实验环境正常</div><a href="https://github.com/erhanerrrrr/watermark-lab" target="_blank" rel="noreferrer"><Github size={16} /> GitHub 仓库</a><small>v0.1 · Research Preview</small></div>
      </aside>
      {open && <button className="overlay" aria-label="关闭菜单" onClick={() => setOpen(false)} />}
      <main className="main-area">
        <header className="topbar"><button className="menu-button" onClick={() => setOpen(!open)} aria-label="打开菜单">{open ? <X size={20} /> : <Menu size={20} />}</button><div className="breadcrumbs"><span>Watermark Lab</span><span className="crumb-separator">/</span><strong>研究控制台</strong></div><div className="topbar-actions"><div className="run-state"><span className="status-dot" />本地 Mock 模式</div><div className="avatar">研</div></div></header>
        <div className="page-content"><Outlet /></div>
      </main>
    </div>
  )
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) {
  return <div className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>
}

export function StatusBadge({ children, tone = 'green' }: { children: React.ReactNode; tone?: 'green' | 'amber' | 'slate' | 'blue' }) {
  return <span className={`badge badge-${tone}`}><span className="badge-dot" />{children}</span>
}

export function MetricCard({ label, value, hint, icon: Icon, accent = 'blue' }: { label: string; value: string; hint: string; icon: React.ElementType; accent?: string }) {
  return <div className="metric-card"><div className={`metric-icon ${accent}`}><Icon size={18} /></div><div className="metric-copy"><span>{label}</span><strong>{value}</strong><small>{hint}</small></div></div>
}
