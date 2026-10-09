import { ChevronRight } from 'lucide-react'
import { BIKE_STOCK_LOW_MAX, bikeStockBadgeLevel, bikeStockBadgeText } from './bikeStockBadge'
import { getBikeStationDisplayName } from './bikeStations'
import type { BikeStation } from './bikeStations'

interface Props {
  stations: BikeStation[]
  onSelect: (station: BikeStation) => void
}

// 목록에 보여 줄 최대 대여소 수.
const LIST_LIMIT = 20

const formatDistance = (meters: number) =>
  meters < 1000 ? `${Math.round(meters)}m` : `${(meters / 1000).toFixed(1)}km`

const byDistance = (a: BikeStation, b: BikeStation) =>
  (a.distanceMeters ?? Infinity) - (b.distanceMeters ?? Infinity)

/** 홈 자전거 탭의 주변 따릉이 대여소 목록. 지도가 받은 대여소를 가까운 순으로 보여 준다. */
export default function NearbyBikeStationList({ stations, onSelect }: Props) {
  const sorted = [...stations].sort(byDistance).slice(0, LIST_LIMIT)
  return (
    <>
      <div className="home-sheet-heading">
        <h2 className="home-sheet-title">주변 따릉이</h2>
        <small>가까운 순</small>
      </div>
      <div className="home-layer-legend">
        <strong>따릉이 대여 가능 대수</strong>
        <span>
          <i className="legend-dot level-ok" />
          {BIKE_STOCK_LOW_MAX + 1}대 이상
        </span>
        <span>
          <i className="legend-dot level-low" />
          {BIKE_STOCK_LOW_MAX}대 이하
        </span>
      </div>
      {sorted.length === 0 ? (
        <p className="home-sheet-empty">주변에 대여소가 없어요</p>
      ) : (
        <ul className="nearby-station-list">
          {sorted.map((station) => {
            const details = [
              typeof station.availableBikes === 'number'
                ? `대여 가능 ${station.availableBikes}대`
                : null,
              station.dockCount !== undefined ? `거치대 ${station.dockCount}` : null,
              station.distanceMeters !== undefined ? formatDistance(station.distanceMeters) : null,
            ].filter((item): item is string => item !== null)
            return (
              <li key={station.id}>
                <button type="button" onClick={() => onSelect(station)}>
                  <i
                    className={`nearby-bike-badge level-${bikeStockBadgeLevel(station.availableBikes)}`}
                  >
                    {bikeStockBadgeText(station.availableBikes)}
                  </i>
                  <span>
                    <strong>{getBikeStationDisplayName(station.name)}</strong>
                    {details.length > 0 && <small>{details.join(' · ')}</small>}
                  </span>
                  <ChevronRight size={18} aria-hidden="true" />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}
