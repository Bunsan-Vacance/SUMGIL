import { useState } from 'react'
import type { CongestionHeatmap as CongestionHeatmapData } from './types'
import { heatmapCellTone, type HeatmapTone } from './useOpsData'

/** 슬롯 번호(30분 단위)를 HH:MM으로 바꾼다. 슬롯 s는 s/2시 (s%2 ? 30 : 00)분이다. */
export function slotLabel(slot: number) {
  return `${String(Math.floor(slot / 2)).padStart(2, '0')}:${slot % 2 ? '30' : '00'}`
}

function percent(value: number | null) {
  return value === null ? '알 수 없음' : `${value}%`
}

function count(value: number | null) {
  return value === null ? '알 수 없음' : String(value)
}

const LEGEND: { tone: HeatmapTone; label: string }[] = [
  { tone: 'tone-1', label: '60% 미만' },
  { tone: 'tone-2', label: '60~90%' },
  { tone: 'tone-3', label: '90~120%' },
  { tone: 'tone-4', label: '120~150%' },
  { tone: 'tone-5', label: '150% 이상' },
  { tone: 'none', label: '값 없음' },
]

export default function CongestionHeatmap({ data }: { data: CongestionHeatmapData }) {
  const [selected, setSelected] = useState<string | null>(null)
  const slots: number[] = []
  for (let slot = data.slotFrom; slot <= data.slotTo; slot += 1) slots.push(slot)
  const columns = `minmax(56px, auto) repeat(${slots.length}, minmax(0, 1fr))`

  return (
    <div className="ops-heat-wrap">
      <div
        className="ops-heat"
        role="group"
        aria-label="호선별 시간대 혼잡도"
        style={{ gridTemplateColumns: columns }}
      >
        <span className="ops-heat-corner" />
        {slots.map((slot, index) => (
          <span key={slot} className="ops-heat-head">
            {index % 2 === 0 ? slotLabel(slot) : ''}
          </span>
        ))}
        {data.lines.map((line) => {
          const bySlot = new Map(line.cells.map((cell) => [cell.timeSlot, cell]))
          return [
            <span key={`${line.lineId}-name`} className="ops-heat-line">
              {line.lineName}
            </span>,
            ...slots.map((slot) => {
              const cell = bySlot.get(slot)
              const level = cell?.level ?? null
              const tone = heatmapCellTone(level)
              const detail = `${line.lineName} ${slotLabel(slot)} · 혼잡도 ${percent(level)} · 링크 ${count(cell?.nLinks ?? null)} (보정 폴백 ${count(cell?.nFallback ?? null)}) · 최대 ${percent(cell?.maxLevel ?? null)}`
              const key = `${line.lineId}-${slot}`
              return (
                <button
                  key={key}
                  type="button"
                  className={`ops-heat-cell ${tone === 'none' ? 'ops-heat-none' : `ops-heat-${tone}`}${selected === detail ? ' selected' : ''}`}
                  title={detail}
                  aria-label={detail}
                  onClick={() => setSelected(detail)}
                >
                  {level === null ? '–' : ''}
                </button>
              )
            }),
          ]
        })}
      </div>
      <ul className="ops-heat-legend" aria-label="범례">
        {LEGEND.map((item) => (
          <li key={item.tone}>
            <i className={item.tone === 'none' ? 'ops-heat-none' : `ops-heat-${item.tone}`} />
            {item.label}
          </li>
        ))}
      </ul>
      <p role="status" className="ops-heat-detail">
        {selected ?? '셀을 선택하면 상세가 표시됩니다.'}
      </p>
    </div>
  )
}
