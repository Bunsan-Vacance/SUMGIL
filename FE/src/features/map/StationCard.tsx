import { useState } from 'react'
import type { ReactNode } from 'react'
import { Star, X } from 'lucide-react'
import type { GuidanceRepository } from '../../api/guidance'
import type { CongestionBatchRepository } from '../../api/congestion'
import { lineColorById } from '../route/lineColor'
import { segmentCongestionPresentation } from '../route/segmentCongestion'
import type { Place, SegmentCongestionGrade } from '../route/types'
import { congestionAdvice } from './congestionAdvice'
import { formatClock } from './stationArrivals'
import { nearbyStationToPlace, stationDisplayName, walkMinutes } from './stations'
import { useStationArrivals } from './useStationArrivals'
import { useStationHourlyCongestion, HOURLY_NOW_INDEX } from './useStationHourlyCongestion'
import type { StationCongestion } from './useNearbyStationCongestion'

interface Props {
  station: StationCongestion
  favorite: boolean
  onToggleFavorite: () => void
  onClose: () => void
  onSetOrigin: (place: Place) => void
  onSetDestination: (place: Place) => void
  /** 테스트에서 저장소·시각을 바꿔 끼우기 위한 주입 지점. */
  arrivalsRepository?: Pick<GuidanceRepository, 'arrivals'> | null
  batchRepository?: CongestionBatchRepository | null
  now?: () => Date
}

const gradeLabel = (grade: SegmentCongestionGrade | null) =>
  (grade && segmentCongestionPresentation(grade)?.label) || '정보 없음'
const gradeColor = (grade: SegmentCongestionGrade | null) =>
  (grade && segmentCongestionPresentation(grade)?.color) || '#82909b'

function lineBadgeText(lineId: string, lineName: string | null) {
  const name = lineName || lineId
  const match = /^(\d+)호선$/.exec(name)
  return match ? match[1] : name.slice(0, 1)
}

export default function StationCard({
  station,
  favorite,
  onToggleFavorite,
  onClose,
  onSetOrigin,
  onSetDestination,
  arrivalsRepository,
  batchRepository,
  now,
}: Props) {
  const [lineId, setLineId] = useState<string | null>(station.lines[0]?.lineId ?? null)
  const selectedLine = station.lines.find((line) => line.lineId === lineId)
  // 인자를 생략하면 훅의 기본 저장소·시각을 쓴다.
  const arrivals = useStationArrivals(
    station.stationId,
    lineId,
    station.stationName,
    selectedLine?.lineName ?? null,
    arrivalsRepository,
    30_000,
    now,
  )
  const hourly = useStationHourlyCongestion(station.stationId, batchRepository, now)
  const place = nearbyStationToPlace(station)
  const lineNames = station.lines.map((line) => line.lineName || line.lineId)
  const lineSummary = lineNames.length
    ? `${lineNames.join(' · ')}${lineNames.length > 1 ? ' 환승역' : ''}`
    : '지하철역'
  const displayName = stationDisplayName(station.stationName)

  const nowGrade = station.grade ?? hourly.bars[HOURLY_NOW_INDEX]?.grade ?? null
  const advice = congestionAdvice(hourly.bars)
  const arrivalResult = arrivals.result
  const clock = formatClock(arrivalResult?.updatedAt ?? arrivals.fetchedAt, true)
  const hasDirections = arrivals.directions.length > 0

  const arrivalList = (
    <div className="station-card-directions">
      {arrivals.directions.map((direction) => (
        <div key={direction.direction} className="station-card-direction">
          <small>{direction.direction}</small>
          {direction.trains.map((train) => (
            <strong key={train.arrivalTime}>{train.etaLabel}</strong>
          ))}
        </div>
      ))}
    </div>
  )

  let arrivalBody: ReactNode
  if (arrivals.status === 'unsupported') {
    arrivalBody = <p>노선 정보가 없어 도착 정보를 볼 수 없어요</p>
  } else if (arrivals.status === 'loading' && !arrivalResult) {
    arrivalBody = <p role="status">확인하고 있어요…</p>
  } else if (arrivals.status === 'error') {
    arrivalBody = (
      <>
        <p role="alert">도착 정보를 불러오지 못했어요</p>
        <button type="button" className="secondary" onClick={arrivals.retry}>
          다시 시도
        </button>
        {arrivalResult && hasDirections && arrivalList}
      </>
    )
  } else if (arrivalResult?.status === 'NO_INFO') {
    arrivalBody = <p>도착 정보가 없어요</p>
  } else if (arrivalResult?.status === 'OUTSIDE_WINDOW') {
    arrivalBody = <p>운행 시간이 아니에요</p>
  } else if (arrivalResult) {
    arrivalBody = hasDirections ? (
      <>
        {arrivalList}
        {arrivalResult.status === 'STALE' && (
          <small>마지막 갱신 {formatClock(arrivalResult.updatedAt, false)}</small>
        )}
      </>
    ) : (
      <p>도착 예정 열차가 없어요</p>
    )
  } else {
    arrivalBody = <p role="status">확인하고 있어요…</p>
  }

  const barsLabel = hourly.bars
    .map(
      (bar, index) => `${index === HOURLY_NOW_INDEX ? '지금' : bar.label} ${gradeLabel(bar.grade)}`,
    )
    .join(', ')

  return (
    <section className="station-card" aria-label="선택한 역" aria-live="polite">
      <header className="bike-station-card-header">
        <div className="bike-station-card-title">
          <h2>{displayName}</h2>
          <small>
            {Math.round(station.distanceMeters)}m · 도보 {walkMinutes(station.distanceMeters)}분
          </small>
          <small>{lineSummary}</small>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label={favorite ? '즐겨찾기 해제' : '즐겨찾기 추가'}
          aria-pressed={favorite}
          onClick={onToggleFavorite}
        >
          <Star size={18} fill={favorite ? 'currentColor' : 'none'} />
        </button>
        <button type="button" className="icon-button" aria-label="역 정보 닫기" onClick={onClose}>
          <X size={18} />
        </button>
      </header>

      {station.lines.length > 1 && (
        <div className="station-card-lines" role="group" aria-label="노선 선택">
          {station.lines.map((line) => {
            const color = lineColorById(line.lineId, line.lineName)
            return (
              <button
                key={line.lineId}
                type="button"
                aria-pressed={line.lineId === lineId}
                onClick={() => setLineId(line.lineId)}
              >
                <span
                  className="station-card-line-badge"
                  style={{
                    background: color?.background ?? '#82909b',
                    color: color?.text ?? '#fff',
                  }}
                >
                  {lineBadgeText(line.lineId, line.lineName)}
                </span>
                {line.lineName || line.lineId}
              </button>
            )
          })}
        </div>
      )}

      <div className="station-card-arrivals">
        <div className="station-card-block-head">
          <h3>실시간 도착</h3>
          {clock && <small>{clock} 기준</small>}
        </div>
        {arrivalBody}
      </div>

      <div className="station-card-hourly">
        <div className="station-card-block-head">
          <h3>시간대별 혼잡도</h3>
          <small>역 전체 기준</small>
        </div>
        <div className="station-card-now">
          <span className="station-card-pill" style={{ background: gradeColor(nowGrade) }}>
            {nowGrade ? `지금 ${gradeLabel(nowGrade)}` : '지금 정보 없음'}
          </span>
          {advice && <span>{advice}</span>}
        </div>
        {hourly.status === 'loading' && <p role="status">확인하고 있어요…</p>}
        {hourly.status === 'unavailable' && <p>시간대별 혼잡도를 볼 수 없어요</p>}
        {hourly.status === 'error' && (
          <>
            <p role="alert">혼잡도를 불러오지 못했어요</p>
            <button type="button" className="secondary" onClick={hourly.retry}>
              다시 시도
            </button>
          </>
        )}
        {hourly.status === 'success' && (
          <div role="img" aria-label={`${displayName} 시간대별 혼잡도: ${barsLabel}`}>
            <div className="station-card-bars">
              {hourly.bars.map((bar, index) => {
                const gradeClass = `grade-${bar.grade ? bar.grade.toLowerCase() : 'none'}`
                const height = bar.level === null ? 12 : Math.max(4, Math.min(bar.level, 100))
                return (
                  <div key={bar.departureTime} className="station-card-bar-cell">
                    <small>{bar.level === null ? '-' : Math.round(bar.level)}</small>
                    <span
                      className={`station-card-bar ${gradeClass}${
                        index === HOURLY_NOW_INDEX ? ' now' : ''
                      }`}
                      style={{ height: `${height}%` }}
                    />
                  </div>
                )
              })}
            </div>
            <div className="station-card-bar-labels">
              {hourly.bars.map((bar) => (
                <small key={bar.departureTime}>{bar.label}</small>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="station-card-actions bike-station-actions">
        <button type="button" className="secondary" onClick={() => onSetOrigin(place)}>
          출발지로 설정
        </button>
        <button type="button" className="primary" onClick={() => onSetDestination(place)}>
          도착지로 설정
        </button>
      </div>
    </section>
  )
}
