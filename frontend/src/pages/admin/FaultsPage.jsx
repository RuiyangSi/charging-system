import { get, usePoll } from '../../api.js'

export default function FaultsPage() {
  const { data: faults } = usePoll(() => get('/admin/faults'), 2000)

  return (
    <>
      <div className="a-top">
        <h1>故障记录<small>reportFault / recoverPile：中断车辆 · 受影响排队车辆 · 重排方案</small></h1>
      </div>
      <div className="panel">
        <div className="panel-h">
          <h2><span className="bar" />FaultRecord 档案</h2>
          <span className="hint">中断车=部分计费；排队车=按策略重排</span>
        </div>
        {!faults?.length
          ? <div className="empty">暂无故障记录（可在「运维管理」对运行中的桩注入故障）</div>
          : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>故障时间</th><th>桩</th><th>类型</th><th>调度策略</th>
                  <th>中断车辆</th><th>受影响排队</th><th>重排方案</th><th>恢复时间</th>
                </tr>
              </thead>
              <tbody>
                {faults.map(f => (
                  <tr key={f.faultId}>
                    <td className="mono">{f.faultTime}</td>
                    <td className="mono">{f.pileId}</td>
                    <td>{f.faultType}</td>
                    <td>{f.strategyLabel}</td>
                    <td className="mono">{f.interrupted.join(', ') || '—'}</td>
                    <td className="mono">{f.queued.join(', ') || '—'}</td>
                    <td>
                      <div className="plan-chips">
                        {f.plan.length
                          ? f.plan.map((p, i) => <span key={i}>{p.carId}: {p.from}→{p.to}</span>)
                          : '—'}
                      </div>
                    </td>
                    <td className="mono">{f.recoverTime
                      ? f.recoverTime
                      : <span className="badge b-fault">未恢复</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </>
  )
}
