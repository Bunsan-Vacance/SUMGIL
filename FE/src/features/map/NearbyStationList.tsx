import { ChevronRight } from 'lucide-react'
import {
  SEGMENT_CONGESTION_LEVELS,
  segmentCongestionPresentation,
} from '../route/segmentCongestion'
import type { NearbyStationStatus, StationCongestion } from './useNearbyStationCongestion'

interface Props {
  stations: StationCongestion[]
  status: NearbyStationStatus
  onSelect: (station: StationCongestion) => void
  onRetry: () => void
}

const NO_INFO_COLOR = '#82909b'

const formatDistance = (meters: number) =>
  meters < 1000 ? `${Math.round(meters)}m` : `${(meters / 1000).toFixed(1)}km`

/** 홈 혼잡도 탭의 주변 역 목록. 지도 마커와 같은 배열을 가까운 순으로 보여 준다. */
export default function NearbyStationList({ stations, status, onSelect, onRetry }: Props) {
  const sorted = [...stations].sort((a, b) => a.distanceMeters - b.distanceMeters)
  let body
  if (status === 'error') {
    body = (
      <div className="home-sheet-empty" role="alert">
        <p>주변 역을 불러오지 못했어요</p>
        <button type="button" className="secondary" onClick={onRetry}>
          다시 시도
        </button>
      </div>
    )
  } else if (sorted.length === 0) {
    body =
      status === 'ready' ? (
        <p className="home-sheet-empty">주변 1.5km에 역이 없어요</p>
      ) : (
        <p className="home-sheet-empty" role="status">
          <span className="spinner" /> 주변 역을 찾고 있어요
        </p>
      )
  } else {
    body = (
      <ul className="nearby-station-list">
        {sorted.map((station) => {
          const presentation = station.grade
            ? segmentCongestionPresentation(station.grade)
            : undefined
          const color = presentation?.color ?? NO_INFO_COLOR
          const lineNames = station.lines.map((line) => line.lineName || line.lineId).join(' · ')
          return (
            <li key={station.stationId}>
              <button type="button" onClick={() => onSelect(station)}>
                <i className="nearby-station-grade" style={{ background: color }} />
                <span>
                  <strong>{station.stationName}</strong>
                  <small style={{ color }}>{presentation?.label ?? '정보 없음'}</small>
                  <small>
                    {lineNames ? `${lineNames} · ` : ''}
                    {formatDistance(station.distanceMeters)}
                  </small>
                </span>
                <ChevronRight size={18} aria-hidden="true" />
              </button>
            </li>
          )
        })}
      </ul>
    )
  }
  return (
    <>
      <div className="home-sheet-heading">
        <h2 className="home-sheet-title">주변 역 혼잡도</h2>
        <small>가까운 순 · 1.5km</small>
      </div>
      <div className="home-layer-legend">
        {SEGMENT_CONGESTION_LEVELS.map((level) => (
          <span key={level.grade}>
            <i className="legend-dot" style={{ background: level.color }} />
            {level.label}
          </span>
        ))}
        <span>
          <i className="legend-dot" style={{ background: NO_INFO_COLOR }} />
          정보 없음
        </span>
      </div>
      {body}
    </>
  )
}
