import { NavLink, Outlet } from 'react-router-dom'
import { get, usePoll } from '../../api.js'

const NAV = [
  ['monitor', '📊', '监控大屏'],
  ['ops', '🛠️', '运维管理'],
  ['rules', '💴', '计费规则'],
  ['reports', '📈', '统计报表'],
  ['faults', '⚠️', '故障记录'],
  ['settings', '⚙️', '参数设置'],
]

export default function AdminLayout() {
  const { data: meta } = usePoll(() => get('/admin/meta'), 5000)

  return (
    <div className="app-admin">
      <aside className="sidebar">
        <div className="s-brand">
          <div className="s-logo">⚡</div>
          <div>
            <b>智充控制台</b>
            <span>ADMIN CONSOLE</span>
          </div>
        </div>
        <nav className="s-nav">
          {NAV.map(([to, ic, label]) => (
            <NavLink key={to} to={`/admin/${to}`}
                     className={({ isActive }) => 'item' + (isActive ? ' on' : '')}>
              <span className="ic">{ic}</span>{label}
            </NavLink>
          ))}
          <NavLink to="/" className="item" style={{ marginTop: 10 }}>
            <span className="ic">↩︎</span>返回入口
          </NavLink>
        </nav>
        <div className="s-foot">
          充电站 · 波普特大学东区<br />
          {meta
            ? <><b>{meta.fastPileNum} 快充 + {meta.tricklePileNum} 慢充</b> · 每桩 {meta.queueLen} 车位<br />
                等候区容量 {meta.waitingAreaSize}</>
            : '加载中…'}
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
