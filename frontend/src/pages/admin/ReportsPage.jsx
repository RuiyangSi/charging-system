import { useState } from 'react'
import { get, usePoll } from '../../api.js'

export default function ReportsPage() {
  const [period, setPeriod] = useState('day')
  const [date, setDate] = useState('')

  const { data: rep } = usePoll(
    () => get(`/admin/report?period=${period}${date ? `&date=${date}` : ''}`),
    2000, [period, date])

  const maxCap = Math.max(1, ...(rep?.daily.map(d => d.capacity) ?? [1]))

  return (
    <>
      <div className="a-top">
        <h1>统计报表<small>时间(日/周/月) × 充电桩 → 次数 · 时长 · 电量 · 充电费 · 服务费 · 总费用</small></h1>
        <div className="right">
          <div className="clockbar">
            <select value={period} onChange={e => setPeriod(e.target.value)}>
              <option value="day">按日</option>
              <option value="week">按周（近7日）</option>
              <option value="month">按月</option>
            </select>
            <input type="date" value={date} onChange={e => setDate(e.target.value)}
                   style={{ width: 140 }} />
            {date && <button className="btn-sm btn-ghost" onClick={() => setDate('')}>今天</button>}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2><span className="bar" />充电桩运营报表</h2>
          <span className="hint">{rep ? `统计区间 ${rep.dateFrom} ~ ${rep.dateTo}` : ''}</span>
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th>充电桩编号</th><th>累计充电次数</th><th>累计充电时长(h)</th>
              <th>累计充电电量(度)</th><th>累计充电费用(元)</th><th>累计服务费用(元)</th><th>累计总费用(元)</th>
            </tr>
          </thead>
          <tbody>
            {rep?.table.map(r => (
              <tr key={r.pileId}>
                <td className="mono">{r.pileId}</td>
                <td className="mono">{r.chargeNum}</td>
                <td className="mono">{r.chargeTime}</td>
                <td className="mono">{r.capacity}</td>
                <td className="mono">{r.chargeFee}</td>
                <td className="mono">{r.serviceFee}</td>
                <td className="mono">{r.totalFee}</td>
              </tr>
            ))}
            {rep && (
              <tr className="total">
                <td>合计</td>
                <td className="mono">{rep.totals.chargeNum}</td>
                <td className="mono">{rep.totals.chargeTime}</td>
                <td className="mono">{rep.totals.capacity}</td>
                <td className="mono">{rep.totals.chargeFee}</td>
                <td className="mono">{rep.totals.serviceFee}</td>
                <td className="mono">{rep.totals.totalFee}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2><span className="bar" />近 7 日充电量（度）</h2>
          <span className="hint">本期合计 {rep?.daily.reduce((a, d) => a + d.capacity, 0).toFixed(1) ?? 0} 度</span>
        </div>
        {rep?.daily.length
          ? (
            <div className="chart">
              {rep.daily.map((d, i) => (
                <div className="col" key={d.date}>
                  <div className="cv">{d.capacity}</div>
                  <div className={'bar' + (i === rep.daily.length - 1 ? ' hi' : '')}
                       style={{ height: `${Math.max(4, d.capacity / maxCap * 100)}%` }} />
                  <div className="cl">{d.date.slice(5)}</div>
                </div>
              ))}
            </div>
          )
          : <div className="empty">暂无订单数据：完成充电后此处出现统计</div>}
      </div>
    </>
  )
}
