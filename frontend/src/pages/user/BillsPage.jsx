import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { get, usePoll, yuan } from '../../api.js'

const TAG = { peak: 'tag-peak', flat: 'tag-flat', valley: 'tag-valley' }

export default function BillsPage() {
  const { carId } = useOutletContext()
  const [date, setDate] = useState('')
  const [sel, setSel] = useState(null)   // 选中的账单（看详单）

  const { data: bills } = usePoll(
    () => get(`/bill?carId=${encodeURIComponent(carId)}${date ? `&date=${date}` : ''}`),
    2000, [carId, date])

  const selected = sel && bills?.find(b => b.billId === sel)

  return (
    <>
      <div className="sectitle first">账单查询（Request_Bill）</div>
      <div className="card-u" style={{ padding: 12 }}>
        <div className="inline-edit" style={{ marginTop: 0 }}>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} />
          {date && <button className="ghost" onClick={() => setDate('')}>全部日期</button>}
        </div>
      </div>

      {!bills?.length && <div className="notice ok">暂无账单：完成一次充电后将自动生成账单。</div>}

      {bills?.map(b => (
        <div key={b.billId} className={'bill' + (sel === b.billId ? ' sel' : '')}
             onClick={() => setSel(sel === b.billId ? null : b.billId)}>
          <div className="bill-top">
            <div className="bill-date">
              {b.date} · {b.mode === 'F' ? '快充' : '慢充'}
              {b.billType === 'interrupted' && <span className="badge b-interrupt" style={{ marginLeft: 6 }}>故障中断·部分计费</span>}
              <small>账单号 {b.billId} · 桩 {b.pileId}</small>
            </div>
            <div className="bill-fee">{yuan(b.totalFee)}</div>
          </div>
          <div className="bill-grid">
            <div className="c"><div className="ck">充电量</div><div className="cv">{b.chargeAmount} 度</div></div>
            <div className="c"><div className="ck">时长</div><div className="cv">{b.chargeDuration} h</div></div>
            <div className="c"><div className="ck">时段</div><div className="cv">{b.startTime?.slice(11, 16)}–{b.endTime?.slice(11, 16)}</div></div>
          </div>
        </div>
      ))}

      {selected && (
        <>
          <div className="sectitle">
            详单（Request_DetailedList）：{selected.billId}（桩 {selected.pileId} · {selected.chargeAmount} 度）
          </div>
          <div className="bill" style={{ cursor: 'default' }}>
            {selected.segments.map((s, i) => (
              <div className="detail-line" key={i}>
                <span className="dk">
                  <span className={`seg-tag ${TAG[s.kind]}`}>{s.label[0]}</span>
                  {s.from}–{s.to} · {s.kwh} 度 × {s.price}
                </span>
                <span className="dv">{yuan(s.fee)}</span>
              </div>
            ))}
            <div className="detail-line">
              <span className="dk">充电费小计</span><span className="dv">{yuan(selected.totalChargeFee)}</span>
            </div>
            <div className="detail-line">
              <span className="dk">
                服务费　{selected.chargeAmount} 度
                {selected.chargeAmount > 0 &&
                  ` × ${(selected.totalServiceFee / selected.chargeAmount).toFixed(2)}`}
              </span>
              <span className="dv">{yuan(selected.totalServiceFee)}</span>
            </div>
            <div className="detail-total">
              <span className="tk">合计应付</span>
              <span className="tv">{yuan(selected.totalFee)}</span>
            </div>
          </div>
        </>
      )}
    </>
  )
}
