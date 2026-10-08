import { useState } from 'react'
import type { CongestionHeatmap as CongestionHeatmapData } from './types'
import {
  SEGMENT_CONGESTION_LEVELS,
  SEGMENT_CONGESTION_THRESHOLDS,
  segmentCongestionPresentation,
} from '../route/segmentCongestion'
import { heatmapCellTone } from './useOpsData'

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

/** 등급별 구간 문구. 경계값은 `SEGMENT_CONGESTION_THRESHOLDS`에서 가져온다. */
export function gradeRangeLabel(index: number) {
  const last = SEGMENT_CONGESTION_THRESHOLDS.length
  if (index === 0) return `${SEGMENT_CONGESTION_THRESHOLDS[0]}% 미만`
  if (index === last) return `${SEGMENT_CONGESTION_THRESHOLDS[last - 1]}% 이상`
  return `${SEGMENT_CONGESTION_THRESHOLDS[index - 1]}~${SEGMENT_CONGESTION_THRESHOLDS[index]}%`
}

const LEGEND = [
  ...SEGMENT_CONGESTION_LEVELS.map((level, index) => ({
    key: level.grade,
    label: `${level.label} ${gradeRangeLabel(index)}`,
    // 사용자 지도와 같은 등급 색을 그대로 쓴다(채도가 높아도 4단계라 구분이 우선).
    color: level.color as string | undefined,
  })),
  { key: 'none', label: '값 없음', color: undefined },
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
              const presentation = tone === 'none' ? undefined : segmentCongestionPresentation(tone)
              const gradeText = presentation ? ` (${presentation.label})` : ''
              const detail = `${line.lineName} ${slotLabel(slot)} · 혼잡도 ${percent(level)}${gradeText} · 링크 ${count(cell?.nLinks ?? null)} (보정 폴백 ${count(cell?.nFallback ?? null)}) · 최대 ${percent(cell?.maxLevel ?? null)}`
              const key = `${line.lineId}-${slot}`
              return (
                <button
                  key={key}
                  type="button"
                  className={`ops-heat-cell${tone === 'none' ? ' ops-heat-none' : ''}${selected === detail ? ' selected' : ''}`}
                  style={presentation ? { background: presentation.color } : undefined}
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
          <li key={item.key}>
            <i
              className={item.color ? undefined : 'ops-heat-none'}
              style={item.color ? { background: item.color } : undefined}
            />
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
