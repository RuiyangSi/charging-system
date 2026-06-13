import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { post } from '../api.js'

export default function Login() {
  const nav = useNavigate()
  const [carId, setCarId] = useState(localStorage.getItem('carId') || '')
  const [capacity, setCapacity] = useState('60')
  const [err, setErr] = useState('')

  const userLogin = async () => {
    const id = carId.trim()
    if (!id) { setErr('请输入车牌号 / 车辆编号'); return }
    try {
      await post('/user/login', { carId: id, capacity: Number(capacity) || 60 })
      localStorage.setItem('carId', id)
      nav('/user/charge')
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="login-wrap">
      <div className="login-brand">
        <div className="logo">⚡</div>
        <div>
          <b>智充 ChargeHub</b>
          <span>智能充电桩调度计费系统 · 波普特大学</span>
        </div>
      </div>
      <div className="login-cards">
        <div className="login-card">
          <h3>用户客户端</h3>
          <p>提交充电请求 · 查看排队/充电状态 · 账单详单</p>
          {err && <div className="login-err">{err}</div>}
          <div className="field">
            <label>车牌号 / 车辆编号（如 V1）</label>
            <input value={carId} placeholder="V1"
                   onChange={e => setCarId(e.target.value)}
                   onKeyDown={e => e.key === 'Enter' && userLogin()} />
          </div>
          <div className="field">
            <label>电池总容量（度，可选）</label>
            <input type="number" value={capacity} min="1"
                   onChange={e => setCapacity(e.target.value)} />
          </div>
          <button className="btn-primary" onClick={userLogin}>进入用户端</button>
        </div>
        <div className="login-card admin">
          <h3>管理员控制台</h3>
          <p style={{ color: '#94a3b8' }}>监控大屏 · 运维管理 · 计费规则 · 统计报表 · 故障调度</p>
          <button className="btn-dark" onClick={() => nav('/admin/monitor')}>进入管理员端</button>
        </div>
      </div>
    </div>
  )
}
