import { useState } from 'react'
import { get, post, put, usePoll } from '../../api.js'

const WS_BADGE = {
  '充电中': 'b-on', '空闲': 'b-idle', '故障': 'b-fault',
  '已关闭': 'b-idle', '已上电': 'b-amber', '关闭中': 'b-amber',
}

export default function OpsPage() {
  const { data: piles, refresh } = usePoll(() => get('/pile/state'), 1000)
  const { data: cfg, refresh: refreshCfg } = usePoll(() => get('/admin/config'), 4000)
  const [toast, setToast] = useState(null)

  const run = async (fn, ok) => {
    try { await fn(); setToast({ text: ok }); refresh(); refreshCfg() }
    catch (e) { setToast({ text: e.message, err: true }) }
    setTimeout(() => setToast(null), 3200)
  }
  const setCfg = (patch, ok) => run(() => put('/admin/config', patch), ok)

  return (
    <>
      <div className="a-top">
        <h1>运维管理<small>充电桩 上电/运行/关闭 · 故障注入与恢复 · 调度策略</small></h1>
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2><span className="bar" />充电桩运维（powerOn / runPile / powerOff）</h2>
          <span className="hint">关闭运行中的桩：排队车回等候区队首；充电车辆充完延迟关闭</span>
        </div>
        <table className="tbl">
          <thead>
            <tr><th>桩号</th><th>类型</th><th>额定功率</th><th>当前状态</th><th>排队/容量</th><th style={{ textAlign: 'right' }}>操作</th></tr>
          </thead>
          <tbody>
            {piles?.map(p => (
              <tr key={p.pileId}>
                <td className="mono">{p.pileId}</td>
                <td>{p.modeLabel}</td>
                <td className="mono">{p.power} 度/h</td>
                <td><span className={`badge ${WS_BADGE[p.workingState] || 'b-idle'}`}>
                  {p.status === 'RUNNING' ? `运行中·${p.workingState}` : p.workingState}</span></td>
                <td className="mono">{p.queueLen} / {p.queueCapacity}</td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                  {p.status === 'OFF' && !p.powered &&
                    <button className="btn-sm btn-ghost" onClick={() => run(() => post(`/pile/${p.pileId}/power-on`), `${p.pileId} 已上电（需“运行”后接客）`)}>上电</button>}
                  {p.status === 'OFF' && p.powered &&
                    <button className="btn-sm btn-run" onClick={() => run(() => post(`/pile/${p.pileId}/run`), `${p.pileId} 已运行，开始接受调度`)}>运行</button>}
                  {p.status === 'RUNNING' && <>
                    <button className="btn-sm btn-ghost" style={{ marginRight: 8 }}
                            onClick={() => run(() => post(`/pile-event/${p.pileId}/fault`, {}), `${p.pileId} 故障已上报，按「${cfg?.faultStrategy === 'time_order' ? '时间顺序' : '优先级'}」再调度`)}>
                      注入故障</button>
                    <button className="btn-sm btn-stop" onClick={() => run(() => post(`/pile/${p.pileId}/power-off`), `${p.pileId} 关闭指令已执行`)}>关闭</button>
                  </>}
                  {p.status === 'FAULT' && <>
                    <button className="btn-sm btn-run" style={{ marginRight: 8 }}
                            onClick={() => run(() => post(`/pile-event/${p.pileId}/recover`), `${p.pileId} 已恢复并整体重排`)}>故障恢复</button>
                    <button className="btn-sm btn-stop" onClick={() => run(() => post(`/pile/${p.pileId}/power-off`), `${p.pileId} 已断电关闭`)}>关闭</button>
                  </>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flexrow">
        <div className="panel" style={{ marginBottom: 0 }}>
          <div className="panel-h">
            <h2><span className="bar" />调度策略（dispatchMode）</h2>
            <span className="hint">含 2 个 Bonus 扩展调度</span>
          </div>
          <div className="opt-group">
            {[
              ['default', '默认按序叫号', '按进入等候区先后叫号，为每辆车分配（等待时长+充电时长）最短的同模式桩。'],
              ['single_optimal', '单次调度总充电时长最短（Bonus）', '同时空出 k 个车位时，对队首 k 辆车枚举全部分配方案，使总充电时长最短。'],
              ['batch_optimal', '批量调度总充电时长最短（Bonus）', '仅当 等候区车数 == 空位总数 时整批调度（跨模式搭配罚∞自动排除）；其余时刻车辆在等候区等待批量时机。'],
            ].map(([v, b, s]) => (
              <label key={v} className={'opt-line' + (cfg?.dispatchMode === v ? ' on' : '')}>
                <input type="radio" name="dm" checked={cfg?.dispatchMode === v}
                       onChange={() => setCfg({ dispatchMode: v }, `调度策略已切换：${b}`)} />
                <span><b>{b}</b><small>{s}</small></span>
              </label>
            ))}
          </div>
        </div>

        <div className="panel" style={{ marginBottom: 0 }}>
          <div className="panel-h">
            <h2><span className="bar" />故障再调度策略（reportFault）</h2>
            <span className="hint">骨架：暂停叫号 → 重排 → 恢复叫号</span>
          </div>
          <div className="opt-group">
            {[
              ['priority', '优先级调度（验收默认）', '暂停等候区叫号，优先把坏桩队列里的车调度到同类型最优桩，安置不下的回等候区队首。'],
              ['time_order', '时间顺序调度', '合并同类型所有桩中未充电的车，按排队号公平重排；正在充电的好桩车辆不动。'],
            ].map(([v, b, s]) => (
              <label key={v} className={'opt-line' + (cfg?.faultStrategy === v ? ' on' : '')}>
                <input type="radio" name="fs" checked={cfg?.faultStrategy === v}
                       onChange={() => setCfg({ faultStrategy: v }, `故障策略已切换：${b}`)} />
                <span><b>{b}</b><small>{s}</small></span>
              </label>
            ))}
            <div className="panel-h" style={{ margin: '8px 0 0' }}>
              <h2 style={{ fontSize: 13 }}>充电中被打断的车辆（interruptPolicy）</h2>
            </div>
            {[
              ['manual', '部分计费 + 置“已中断”，由用户重新申请（概要设计）'],
              ['requeue', '部分计费 + 剩余电量最高优先重新调度'],
            ].map(([v, b]) => (
              <label key={v} className={'opt-line' + (cfg?.interruptPolicy === v ? ' on' : '')}>
                <input type="radio" name="ip" checked={cfg?.interruptPolicy === v}
                       onChange={() => setCfg({ interruptPolicy: v }, '中断车辆策略已更新')} />
                <span><b style={{ display: 'inline' }}>{b}</b></span>
              </label>
            ))}
          </div>
        </div>
      </div>

      {toast && <div className={'toast' + (toast.err ? ' err' : '')}>{toast.text}</div>}
    </>
  )
}
