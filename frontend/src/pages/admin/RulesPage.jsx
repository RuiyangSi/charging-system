import { useEffect, useState } from 'react'
import { get, put } from '../../api.js'

const DEFAULTS = { peak: 1.0, flat: 0.7, valley: 0.4, serviceRate: 0.8 }

/** 把同类时段聚合成 "10–15 · 18–21 时" 的展示串 */
const segText = (segments, kind) =>
  segments.filter(s => s.kind === kind).map(s => `${s.from}–${s.to}`).join(' · ') + ' 时'

export default function RulesPage() {
  const [rule, setRule] = useState(null)
  const [form, setForm] = useState(DEFAULTS)
  const [toast, setToast] = useState(null)

  const load = async () => {
    const r = await get('/pile/parameters')
    setRule(r)
    setForm({ peak: r.peak, flat: r.flat, valley: r.valley, serviceRate: r.serviceRate })
  }
  useEffect(() => { load() }, [])

  const save = async (data) => {
    try {
      await put('/pile/parameters', data)
      await load()
      setToast({ text: '计费规则已保存，对后续计费生效（setParameters）' })
    } catch (e) { setToast({ text: e.message, err: true }) }
    setTimeout(() => setToast(null), 3200)
  }

  if (!rule) return <div className="empty">加载中…</div>

  return (
    <>
      <div className="a-top">
        <h1>分时计费规则<small>setParameters：三时段电价 + 服务费 · 总费用 = 充电费 + 服务费</small></h1>
        <div className="right">
          <div className="live">规则生效时间 {rule.effectiveTime || '系统默认'}</div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2><span className="bar" />三时段电价（元/度）</h2>
          <span className="hint">充电费 = Σ(时段充入度数 × 时段电价)</span>
        </div>
        <div className="rules">
          {[['peak', '● 峰时'], ['flat', '● 平时'], ['valley', '● 谷时']].map(([k, name]) => (
            <div key={k} className={`rule ${k}`}>
              <div className="r-name">{name}</div>
              <div className="r-time">{segText(rule.segments, k)}</div>
              <div className="r-price">
                <input type="number" step="0.1" min="0" value={form[k]}
                       onChange={e => setForm({ ...form, [k]: e.target.value })} />
                <small>元/度</small>
              </div>
            </div>
          ))}
        </div>
        <div className="form-grid" style={{ marginTop: 16, maxWidth: 320 }}>
          <div className="field">
            <label>服务费单价（元/度）</label>
            <input type="number" step="0.1" min="0" value={form.serviceRate}
                   onChange={e => setForm({ ...form, serviceRate: e.target.value })} />
          </div>
        </div>
        <div className="actions-row">
          <button className="btn-sm btn-ghost" onClick={() => save(DEFAULTS)}>恢复默认</button>
          <button className="btn-sm btn-run" onClick={() => save({
            peak: Number(form.peak), flat: Number(form.flat),
            valley: Number(form.valley), serviceRate: Number(form.serviceRate),
          })}>保存规则</button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-h"><h2><span className="bar" />当前时段划分</h2>
          <span className="hint">设计假设：峰 10–15/18–21 · 平 7–10/15–18/21–23 · 谷 23–次日7</span></div>
        <table className="tbl">
          <thead><tr><th>时段</th><th>区间</th><th>电价</th></tr></thead>
          <tbody>
            {rule.segments.map((s, i) => (
              <tr key={i}>
                <td>{s.label}</td>
                <td className="mono">{String(s.from).padStart(2, '0')}:00 – {String(s.to).padStart(2, '0')}:00</td>
                <td className="mono">{s.price} 元/度</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {toast && <div className={'toast' + (toast.err ? ' err' : '')}>{toast.text}</div>}
    </>
  )
}
