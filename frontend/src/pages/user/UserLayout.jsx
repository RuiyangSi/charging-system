import { useEffect } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

export default function UserLayout() {
  const nav = useNavigate()
  const carId = localStorage.getItem('carId')

  useEffect(() => { if (!carId) nav('/') }, [carId, nav])
  if (!carId) return null

  const logout = () => { localStorage.removeItem('carId'); nav('/') }

  return (
    <div className="app-user">
      <div className="phone">
        <div className="u-head">
          <div className="u-brand">
            <div className="u-logo">⚡</div>
            <div>
              <b>智充 ChargeHub</b>
              <span>用户客户端</span>
            </div>
          </div>
          <div className="u-avatar">
            <span>{carId}</span>
            <div className="av">{carId.slice(-1)}</div>
            <button className="logout" onClick={logout}>退出</button>
          </div>
        </div>
        <div className="u-body">
          <Outlet context={{ carId }} />
        </div>
        <div className="navbar">
          <NavLink to="/user/charge" className={({ isActive }) => 'nv' + (isActive ? ' on' : '')}>
            <span className="ic">⚡</span>充电
          </NavLink>
          <NavLink to="/user/bills" className={({ isActive }) => 'nv' + (isActive ? ' on' : '')}>
            <span className="ic">🧾</span>账单
          </NavLink>
        </div>
      </div>
    </div>
  )
}
