import { useState } from 'react'
import { get, post, put, usePoll, fmtH, yuan, num2 } from '../../api.js'

const PILE_BADGE = {
  '充电中': ['b-on', 'var(--lime)'],
  '空闲': ['b-idle', '#94a3b8'],
  '故障': ['b-fault', 'var(--rose)'],
  '已关闭': ['b-idle', '#64748b'],
  '已上电': ['b-amber', 'var(--amber)'],
  '关闭中': ['b-amber', 'var(--amber)'],
}
const STATE_BADGE = {
  WAITING: 'b-idle', QUEUING: 'b-on', CHARGING: 'b-on',
}

function PileCard({ p }) {
  const [cls, dotColor] = PILE_BADGE[p.workingState] || ['b-idle', '#94a3b8']
  const cardCls = p.workingState === '充电中' ? 'charging'
    : p.status === 'FAULT' ? 'fault'
    : p.status === 'OFF' ? 'off' : ''
  const spots = Array.from({ length: p.queueCapacity }, (_, i) => {
    if (i >= p.queueLen) return ''
    return i === 0 && p.current ? 'charge' : 'busy'
  })
  return (
    <div className={`pile ${cardCls}`}>
      <div className="pile-h">
        <span className="pile-id">{p.pileId}</span>
        <span className={`badge ${cls}`}><span className="dot" style={{ background: dotColor }} />{p.workingState}</span>
      </div>
      <div className="pile-pw">{p.modeLabel} · {p.power} 度/h</div>
      {p.status === 'FAULT'
        ? <div className="cur faulty">⚠ 设备故障 · 已触发再调度</div>
        : p.current
          ? <div className="cur">
              当前：<span className="mono">{p.current.carId}</span> · 进度 {num2(p.current.estimate?.chargedAmount ?? p.current.chargedAmount)}/{num2(p.current.requestedAmount)} 度
              {p.current.estimate && <> · 当前费用 <span className="mono">{yuan(p.current.estimate.totalFee)}</span></>}
            </div>
          : <div className="cur">当前：<span style={{ color: 'var(--muted)' }}>无</span>{p.status === 'RUNNING' ? ' · 等待叫号' : ''}</div>}
      <div className="spots">
        {spots.map((s, i) => <span key={i} className={`sp ${s}`} />)}
      </div>
      <div className="pile-stats">
        <div className="st"><div className="v">{p.totalChargeNum}</div><div className="l">累计次数</div></div>
        <div className="st"><div className="v">{p.totalChargeTime}h</div><div className="l">累计时长</div></div>
        <div className="st"><div className="v">{p.totalCapacity}</div><div className="l">累计度数</div></div>
      </div>
    </div>
  )
}

export default function MonitorPage() {
  const { data: ov, error, refresh } = usePoll(() => get('/admin/overview'), 1000)
  const [timeInput, setTimeInput] = useState('')
  const [toast, setToast] = useState(null)
  const flash = (text, err) => { setToast({ text, err }); setTimeout(() => setToast(null), 3200) }

  if (!ov) return <div className="empty">连接后端中…（请确认 uvicorn 已启动）</div>

  const { kpis, clock, schedule } = ov
  const setSpeed = async (v) => {
    try { await put('/admin/clock', { speed: Number(v) }); refresh() }
    catch (e) { flash(e.message, true) }
  }
  const setTime = async () => {
    if (!timeInput) return
    try { await put('/admin/clock', { time: timeInput }); setTimeInput(''); refresh(); flash('系统时间已设置') }
    catch (e) { flash(e.message, true) }
  }
  const resetSystem = async () => {
    if (window.confirm('重置系统？将清空所有请求/账单/故障记录，计费规则回到默认值，时钟归位到起始时刻（验收开跑前使用）。')) {
      try { await post('/admin/reset', { wipeHistory: true }); refresh(); flash('系统已重置') }
      catch (e) { flash(e.message, true) }
    }
  }

  const dispatchLabel = { default: '默认按序叫号', single_optimal: '单次调度·总时长最短(Bonus)', batch_optimal: '批量调度·总时长最短(Bonus)' }[schedule.dispatchMode]

  return (
    <>
      <div className="a-top">
        <h1>充电桩监控大屏<small>实时显示全部充电桩工作状态与排队情况 · 每秒自动刷新</small></h1>
        <div className="right">
          <div className={'live' + (clock.paused ? ' paused' : '')}>
            <span className="pulse" />
            {clock.simTime}{clock.paused ? ' · 已暂停' : ` · ×${clock.speed}`}
          </div>
          <div className="clockbar">
            <select value={clock.speed} onChange={e => setSpeed(e.target.value)}>
              {[0, 1, 5, 10, 30, 60].map(v => (
                <option key={v} value={v}>{v === 0 ? '⏸ 暂停' : `×${v} 倍速`}</option>
              ))}
            </select>
            <input placeholder="06:00:00" value={timeInput}
                   onChange={e => setTimeInput(e.target.value)}
                   onKeyDown={e => e.key === 'Enter' && setTime()} />
            <button className="btn-sm btn-ghost" onClick={setTime}>设置时间</button>
            <button className="btn-sm btn-stop" onClick={resetSystem}>重置系统</button>
          </div>
        </div>
      </div>

      {error && (
        <div className="panel" style={{ borderColor: 'rgba(244,63,94,.5)', color: 'var(--rose)' }}>
          ⚠ 与后端连接中断，下方为最后一次成功获取的数据（请确认 uvicorn 仍在运行）。错误：{error}
        </div>
      )}

      {schedule.paused && (
        <div className="panel" style={{ borderColor: 'rgba(251,191,36,.4)', color: 'var(--amber)' }}>
          ⚠ 等候区叫号已暂停（故障再调度处理中）：暂停 → 重排 → 恢复
        </div>
      )}

      <div className="kpis">
        <div className="kpi teal">
          <div className="k-ic">🔌</div><div className="k-lab">在线充电桩</div>
          <div className="k-val">{kpis.onlinePiles}<small> / {kpis.totalPiles}</small></div>
          <div className="k-sub">运行中（含充电）</div>
        </div>
        <div className="kpi lime">
          <div className="k-ic">⚡</div><div className="k-lab">充电中</div>
          <div className="k-val">{kpis.chargingCount}</div>
          <div className="k-sub">{kpis.chargingPiles.join(' · ') || '—'}</div>
        </div>
        <div className="kpi">
          <div className="k-ic">🚗</div><div className="k-lab">排队车辆</div>
          <div className="k-val">{kpis.queueCount}</div>
          <div className="k-sub warn">等候区 {kpis.waitingCount}/{ov.waitingArea.capacity} · 桩位 {kpis.pileQueueCount}</div>
        </div>
        <div className="kpi">
          <div className="k-ic">📦</div><div className="k-lab">本场累计充电量</div>
          <div className="k-val">{kpis.todayCapacity}<small> 度</small></div>
          <div className="k-sub">累计收入 ¥ {kpis.todayRevenue}（{kpis.todayNum} 单）</div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2><span className="bar" />充电桩实时状态（车位：■充电 ■排队 □空闲）</h2>
          <span className="hint">调度策略：{dispatchLabel}</span>
        </div>
        <div className="piles">
          {ov.piles.map(p => <PileCard key={p.pileId} p={p} />)}
        </div>
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2><span className="bar" />等候区 / 充电桩排队队列</h2>
          <span className="hint">按进入先后顺序叫号 · 排队号 F=快充 T=慢充</span>
        </div>
        {ov.queueTable.length === 0
          ? <div className="empty">当前没有排队车辆</div>
          : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>排队号</th><th>车牌</th><th>电池容量</th><th>请求电量</th>
                  <th>模式</th><th>所在队列</th><th>排队时长</th><th>预计等待</th><th>状态</th>
                </tr>
              </thead>
              <tbody>
                {ov.queueTable.map((r, i) => (
                  <tr key={i}>
                    <td className="mono">{r.queueNumber}</td>
                    <td className="mono">{r.carId}</td>
                    <td className="mono">{num2(r.capacity)} 度</td>
                    <td className="mono">{num2(r.requestedAmount)} 度</td>
                    <td>{r.modeLabel}</td>
                    <td>{r.location}</td>
                    <td className="mono">{fmtH(r.waitTime)}</td>
                    <td className="mono">{r.status === 'CHARGING' ? '充电中' : `≈ ${fmtH(r.estimateWait)}`}</td>
                    <td><span className={`badge ${STATE_BADGE[r.status] || 'b-idle'}`}>{r.statusLabel}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>

      {toast && <div className={'toast' + (toast.err ? ' err' : '')}>{toast.text}</div>}
    </>
  )
}
