import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  BarChart3,
  Beaker,
  Database,
  Gauge,
  Github,
  Menu,
  Network,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react'
import { useApi } from '../services/ApiContext'

const navItems = [
  { to: '/', label: '总览 Dashboard', icon: Gauge, end: true },
  { to: '/experiment', label: '水印实验', icon: Beaker },
  { to: '/results', label: '实验结果', icon: BarChart3 },
  { to: '/datasets', label: '数据集', icon: Database },
  { to: '/models', label: '模型库', icon: Network },
  { to: '/attacks', label: '攻击协议', icon: ShieldCheck },
]

const connectionCopy = {
  checking: '正在检查本地服务',
  connected: '真实 API 已连接',
  offline: '本地 API 未连接',
}

export function Layout() {
  const [open, setOpen] = useState(false)
  const { pathname, hash } = useLocation()
  const { connection, health, refresh, lastSyncedAt } = useApi()
  useEffect(() => {
    if (!hash) window.scrollTo({ top: 0, left: 0, behavior: 'instant' })
  }, [pathname, hash])
  return (
    <div className="app-shell">
      <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}>
        <div className="brand"><div className="brand-mark"><Sparkles size={18} /></div><div><strong>Watermark Lab</strong><span>数字水印实验平台</span></div></div>
        <nav className="nav-list">{navItems.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><Icon size={18} /><span>{label}</span></NavLink>)}</nav>
        <div className="sidebar-bottom">
          <div className="status-line"><span className={`status-dot ${connection}`} />{connectionCopy[connection]}</div>
          <a href="https://github.com/erhanerrrrr/watermark-lab" target="_blank" rel="noreferrer"><Github size={16} /> GitHub 仓库</a>
          <small>v{health?.version ?? '0.2'} · Local Showcase</small>
        </div>
      </aside>
      {open && <button className="overlay" aria-label="关闭菜单" onClick={() => setOpen(false)} />}
      <main className="main-area">
        <header className="topbar">
          <button className="menu-button" onClick={() => setOpen(!open)} aria-label="打开菜单">{open ? <X size={20} /> : <Menu size={20} />}</button>
          <div className="breadcrumbs"><span>Watermark Lab</span><span className="crumb-separator">/</span><strong>研究控制台</strong></div>
          <div className="topbar-actions">
            <button className={`connection-state ${connection}`} onClick={() => void refresh()} aria-label="刷新服务状态与模型目录" title={lastSyncedAt ? `目录同步于 ${lastSyncedAt.toLocaleTimeString()}，点击重新同步` : '重新同步服务状态与模型目录'}><span className={`status-dot ${connection}`} />{connectionCopy[connection]}<RefreshCw size={12} /></button>
            <div className="avatar">研</div>
          </div>
        </header>
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

export function ApiRequired() {
  const { connection, error, refresh } = useApi()
  if (connection === 'checking') return <div className="page-state"><span className="status-dot checking" />正在读取本地研究数据…</div>
  return <div className="page-state error-panel"><strong>本地 API 未连接</strong><span>{error || '请运行 Windows 展示启动脚本。'}</span><button className="secondary-button" onClick={() => void refresh()}><RefreshCw size={15} />重新连接</button></div>
}
