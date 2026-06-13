import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { del, get, post, put, usePoll, fmtH, yuan, num2 } from '../../api.js'

const BADGE = {
  WAITING: 'b-wait', QUEUING: 'b-queue', CHARGING: 'b-charging',
  FINISHED: 'b-done', INTERRUPTED: 'b-interrupt', CANCELED: 'b-done',
}

export default function ChargePage() {
  const { carId } = useOutletContext()
  const [mode, setMode] = useState('F')
  const [amount, setAmount] = useState(30)
  const [editing, setEditing] = useState(null)   // null | 'amount'
  const [editVal, setEditVal] = useState('')
  const [msg, setMsg] = useState(null)           // {type, text}

  const { data: meta } = usePoll(() => get('/admin/meta'), 1000)
  const { data: state, refresh } = usePoll(async () => {
    try {
      const s = await get(`/charging/car-state/${carId}`)
      if (s.status === 'CHARGING') {
        const cs = await get(`/charging/charging-state/${carId}`)
        return { ...s, ...cs }
      }
      return s
    } catch (e) {
      if (String(e.message).includes('没有充电请求')) return { none: true }
      throw e
    }
  }, 1000, [carId])

  const act = async (fn, okText) => {
    try {
      await fn()
      setMsg(okText ? { type: 'ok', text: okText } : null)
      setEditing(null)
      refresh()
    } catch (e) { setMsg({ type: 'err', text: e.message }) }
  }

  if (!state) return <div className="sectitle first">加载中…</div>

  const active = !state.none && ['WAITING', 'QUEUING', 'CHARGING'].includes(state.status)
  const power = meta ? (mode === 'F' ? meta.fastPower : meta.tricklePower) : null
  const rule = meta?.rule
  const curPrice = (() => {
    if (!rule || !meta?.clock) return null
    const h = Number(meta.clock.hms.slice(0, 2)) + Number(meta.clock.hms.slice(3, 5)) / 60
    const seg = rule.segments.find(s => s.from <= h && h < s.to)
    return seg || null
  })()

  return (
    <>
      {meta && (
        <div style={{ textAlign: 'center', marginBottom: 6 }}>
          <span className="simclock-chip">
            ⏱ 系统时间 {meta.clock.hms}{meta.clock.speed !== 1 && ` · ×${meta.clock.speed}`}
          </span>
        </div>
      )}
      {msg && <div className={`notice ${msg.type}`} onClick={() => setMsg(null)}>{msg.text}</div>}

      {/* 终态提示 */}
      {!state.none && state.status === 'FINISHED' && (
        <div className="notice ok">上次充电已完成（实充 {state.actualAmount} 度），账单已生成，可在「账单」页查看。</div>
      )}
      {!state.none && state.status === 'INTERRUPTED' && (
        <div className="notice warn">
          上次充电因充电桩故障被中断，已按已充电量（{state.actualAmount} 度）出账。如需继续充电请重新发起申请。
        </div>
      )}

      {/* 发起充电请求 */}
      {!active && (
        <>
          <div className="sectitle first">发起充电请求</div>
          <div className="card-u">
            <div className="seg">
              {[['F', '快充', meta ? `功率 ${meta.fastPower} 度/h · ${meta.fastPileNum} 个桩` : ''],
                ['T', '慢充', meta ? `功率 ${meta.tricklePower} 度/h · ${meta.tricklePileNum} 个桩` : '']]
                .map(([m, lab, sub]) => (
                  <div key={m} className={'opt' + (mode === m ? ' on' : '')} onClick={() => setMode(m)}>
                    <div className="lab">{lab}</div>
                    <div className="sub">{sub}</div>
                  </div>
                ))}
            </div>
            <div className="fieldlab">
              <span className="k">请求充电量</span>
              <span className="v">
                <input type="number" min="1" max="999" value={amount}
                       style={{ width: 72, border: 'none', outline: 'none', textAlign: 'right',
                                font: 'inherit', color: 'inherit', background: 'transparent' }}
                       onChange={e => setAmount(Number(e.target.value))} />
                <small> 度</small>
              </span>
            </div>
            <input type="range" className="slider" min="1" max="120" step="1"
                   value={Math.min(amount, 120)} onChange={e => setAmount(Number(e.target.value))} />
            <div className="scalerow"><span>0</span><span>30</span><span>60</span><span>90</span><span>120</span></div>
            {power && (
              <div className="estimate">
                <span className="e-k">
                  预计充电时长 ≈ {(amount / power).toFixed(2)} h
                  {curPrice && <>　|　预估费用（按{curPrice.label} {curPrice.price} + 服务费 {rule.serviceRate}）</>}
                </span>
                <span className="e-v">
                  {curPrice ? yuan(amount * (curPrice.price + rule.serviceRate)) : '—'}
                </span>
              </div>
            )}
            <button className="btn-primary" style={{ marginTop: 16 }} disabled={!amount || amount <= 0}
                    onClick={() => act(() => post('/charging/request', { carId, mode, amount }), '充电申请已提交')}>
              提交申请
            </button>
          </div>
        </>
      )}

      {/* 排队状态 */}
      {active && state.status !== 'CHARGING' && (
        <>
          <div className="sectitle first">我的排队状态</div>
          <div className="card-u">
            <div className="queue">
              <div className="qnum">{state.queueNumber}</div>
              <div className="qmeta">
                <div className="qrow"><span className="qk">充电模式</span><span className="qv">{state.modeLabel}</span></div>
                <div className="qrow"><span className="qk">请求电量</span><span className="qv mono">{state.requestedAmount} 度</span></div>
                <div className="qrow"><span className="qk">所在位置</span><span className="qv">{state.location}</span></div>
                <div className="qrow"><span className="qk">本车前方</span><span className="qv mono">{state.carsBefore ?? '—'} 辆</span></div>
                <div className="qrow"><span className="qk">预计等待</span><span className="qv mono">≈ {fmtH(state.estimateWait)}</span></div>
                <div className="qrow">
                  <span className="qk">当前状态</span>
                  <span className={`badge ${BADGE[state.status]}`}>{state.statusLabel}</span>
                </div>
              </div>
            </div>
            {editing === 'amount' ? (
              <div className="inline-edit">
                <input type="number" min="1" value={editVal} placeholder="新的充电量（度）"
                       onChange={e => setEditVal(e.target.value)} autoFocus />
                <button onClick={() => act(() => put('/charging/amount', { carId, amount: Number(editVal) }), '充电量已修改')}>确认</button>
                <button className="ghost" onClick={() => setEditing(null)}>取消</button>
              </div>
            ) : (
              <div className="acts">
                <div className="a" onClick={() => { setEditing('amount'); setEditVal(String(state.requestedAmount)) }}>修改电量</div>
                <div className="a" onClick={() => act(
                  () => put('/charging/mode', { carId, mode: state.mode === 'F' ? 'T' : 'F' }),
                  `已改为${state.mode === 'F' ? '慢充' : '快充'}，重新排号`)}>
                  改为{state.mode === 'F' ? '慢充' : '快充'}
                </div>
                <div className="a warn" onClick={() =>
                  window.confirm('确定取消本次充电请求？') &&
                  act(() => del(`/charging/request/${carId}`), '已取消充电请求')}>取消充电</div>
              </div>
            )}
          </div>
        </>
      )}

      {/* 充电状态 */}
      {active && state.status === 'CHARGING' && (
        <>
          <div className="sectitle first">充电进行中</div>
          <div className="card-u">
            <div className="queue">
              <div className="qnum">{state.pileId}</div>
              <div className="qmeta">
                <div className="qrow"><span className="qk">充电模式</span><span className="qv">{state.modeLabel} · {state.power} 度/h</span></div>
                <div className="qrow"><span className="qk">开始时间</span><span className="qv mono">{state.chargingStartTime?.slice(11)}</span></div>
                <div className="qrow">
                  <span className="qk">当前状态</span>
                  <span className="badge b-charging"><span className="dot" style={{ background: 'var(--emerald)' }} />充电中</span>
                </div>
              </div>
            </div>
            <div className="prog">
              <div className="pf" style={{ width: `${Math.min(100, state.chargedAmount / state.requestedAmount * 100)}%` }} />
            </div>
            <div className="qrow"><span className="qk">充电进度</span>
              <span className="qv mono">{num2(state.estimate?.chargedAmount ?? state.chargedAmount)} / {num2(state.requestedAmount)} 度</span></div>
            <div className="qrow"><span className="qk">已充时长</span>
              <span className="qv mono">{fmtH(state.estimate?.duration)}</span></div>
            <div className="qrow"><span className="qk">当前费用（充电费 {yuan(state.estimate?.chargeFee)} + 服务费 {yuan(state.estimate?.serviceFee)}）</span>
              <span className="qv mono">{yuan(state.estimate?.totalFee)}</span></div>
            <div className="qrow"><span className="qk">预计完成</span>
              <span className="qv mono">{state.expectedEndTime}</span></div>
            <div className="acts">
              <div className="a warn" onClick={() =>
                window.confirm('确定提前结束充电？将按已充电量结算。') &&
                act(() => del(`/charging/request/${carId}`), '充电已结束，账单已生成')}>结束充电</div>
            </div>
          </div>
        </>
      )}
    </>
  )
}
