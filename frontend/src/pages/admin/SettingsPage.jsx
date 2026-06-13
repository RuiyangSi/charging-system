import { useEffect, useState } from 'react'
import { get, post, put } from '../../api.js'

const FIELDS = [
  ['FastChargingPileNum', '快充桩数量', '验收参数名 FastChargingPileNum'],
  ['TrickleChargingPileNum', '慢充桩数量', 'TrickleChargingPileNum'],
  ['ChargingQueueLen', '充电桩队列长度 M（含充电位）', 'ChargingQueueLen'],
  ['WaitingAreaSize', '等候区最大容量 N', 'WaitingAreaSize'],
  ['FastPower', '快充功率（度/小时）', '默认 30'],
  ['TricklePower', '慢充功率（度/小时）', '验收为 10（概要设计假设 7）'],
]

export default function SettingsPage() {
  const [form, setForm] = useState(null)
  const [orig, setOrig] = useState(null)   // 上次保存/加载的基准值，用于只提交真正变更的字段
  const [toast, setToast] = useState(null)

  useEffect(() => { get('/admin/config').then(c => { setForm(c); setOrig(c) }) }, [])

  const show = (text, err) => { setToast({ text, err }); setTimeout(() => setToast(null), 4000) }

  const save = async () => {
    try {
      // 只提交确有变更的字段：未改结构参数时不会触发"需要重置系统"确认弹窗，避免误清空数据
      const patch = {}
      for (const [k] of FIELDS) {
        if (Number(form[k]) !== Number(orig[k])) patch[k] = Number(form[k])
      }
      if (String(form.clockStart) !== String(orig.clockStart)) patch.clockStart = form.clockStart
      if (Number(form.clockSpeed) !== Number(orig.clockSpeed)) patch.clockSpeed = Number(form.clockSpeed)
      if (Object.keys(patch).length === 0) { show('参数未变更'); return }
      const res = await put('/admin/config', patch)
      setForm(res.config); setOrig(res.config)
      if (res.requiresReset) {
        if (window.confirm('站点结构参数已修改，需要重置系统后生效。\n现在重置吗？（清空请求/账单/故障记录，时钟归位）')) {
          await post('/admin/reset', { wipeHistory: true })
          show('参数已保存并完成系统重置')
        } else {
          show('参数已保存：将在下次「重置系统」后生效')
        }
      } else {
        show('参数已保存')
      }
    } catch (e) { show(e.message, true) }
  }

  if (!form) return <div className="empty">加载中…</div>

  return (
    <>
      <div className="a-top">
        <h1>参数设置<small>验收时可变更的系统参数（与《作业验收用例》参数名一致）</small></h1>
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2><span className="bar" />站点结构参数</h2>
          <span className="hint">修改后需重置系统（重建充电站）才生效</span>
        </div>
        <div className="form-grid">
          {FIELDS.map(([k, label, hint]) => (
            <div className="field" key={k}>
              <label>{label}<br /><span style={{ fontWeight: 400, color: 'var(--muted)' }}>{hint}</span></label>
              <input type="number" min="0.1" step={k.includes('Power') ? '0.5' : '1'}
                     value={form[k]} onChange={e => setForm({ ...form, [k]: e.target.value })} />
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2><span className="bar" />虚拟时钟（验收比例尺）</h2>
          <span className="hint">验收 1:10 —— 现实 30s = 系统 5min；起始 06:00</span>
        </div>
        <div className="form-grid" style={{ maxWidth: 460 }}>
          <div className="field">
            <label>起始时刻（重置后生效）</label>
            <input value={form.clockStart}
                   onChange={e => setForm({ ...form, clockStart: e.target.value })} />
          </div>
          <div className="field">
            <label>默认倍速</label>
            <input type="number" min="0" step="1" value={form.clockSpeed}
                   onChange={e => setForm({ ...form, clockSpeed: e.target.value })} />
          </div>
        </div>
        <div className="actions-row">
          <button className="btn-sm btn-stop"
                  onClick={async () => {
                    if (window.confirm('立即重置系统？清空请求/账单/故障记录，时钟归位到起始时刻。')) {
                      await post('/admin/reset', { wipeHistory: true })
                      show('系统已重置')
                    }
                  }}>立即重置系统</button>
          <button className="btn-sm btn-run" onClick={save}>保存参数</button>
        </div>
      </div>

      {toast && <div className={'toast' + (toast.err ? ' err' : '')}>{toast.text}</div>}
    </>
  )
}
