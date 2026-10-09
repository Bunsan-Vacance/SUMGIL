import { useState } from 'react'
import { Bike, Star, X } from 'lucide-react'
import type { Place } from '../route/types'
import { bikeRentalId } from './bikeStations'
import { bikeStockBadgeLevel } from './bikeStockBadge'
import type { OutlookSlot, OutlookState } from './useBikeStationOutlook'

const WALK_METERS_PER_MINUTE = 80
const slotLabels: Record<OutlookSlot, string> = { now: '지금', in15: '15분 뒤', in30: '30분 뒤' }
const slots: OutlookSlot[] = ['now', 'in15', 'in30']

export interface SlotDescription {
  title: string
  subtitle: string
  count: number | null
  /** 숫자 대신 보여 줄 안내. count가 있으면 빈 문자열이다. */
  message: string
  note: string
  error: boolean
  mock: boolean
  rack: number | null
}

function clockTime(value: string | null | undefined) {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  return date.toLocaleTimeString('en-GB', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function isCount(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
}

/** 선택한 시점의 조회 결과를 카드에 그릴 문구와 숫자로 바꾼다. */
export function describeOutlookSlot(
  slot: OutlookSlot,
  outlook: Pick<OutlookState, 'stock' | 'predictions'>,
  dockCount?: number,
): SlotDescription {
  const base: SlotDescription = {
    title: '',
    subtitle: '',
    count: null,
    message: '',
    note: '',
    error: false,
    mock: false,
    rack: isCount(dockCount) ? dockCount : null,
  }
  if (slot === 'now') {
    const stock = outlook.stock
    const title = '지금 대여 가능'
    if (stock.status === 'loading') return { ...base, title, message: '확인하고 있어요…' }
    if (stock.status === 'error') {
      return { ...base, title, message: '재고를 불러오지 못했어요', error: true }
    }
    if (stock.status === 'success') {
      const { value } = stock
      const rack = isCount(value.rackCount) ? value.rackCount : base.rack
      if (value.status !== 'UNAVAILABLE' && isCount(value.availableBikes)) {
        const time = clockTime(value.stockUpdatedAt)
        return value.status === 'STALE'
          ? {
              ...base,
              title,
              count: value.availableBikes,
              subtitle: time ? `마지막 확인 ${time}` : '마지막 확인',
              note: '최신 정보가 아닐 수 있어요',
              rack,
            }
          : {
              ...base,
              title,
              count: value.availableBikes,
              subtitle: time ? `${time} 갱신` : '',
              rack,
            }
      }
    }
    return { ...base, title, message: '지금 재고를 확인할 수 없어요' }
  }
  const prediction = outlook.predictions[slot]
  const fallbackTitle = `${slotLabels[slot]} 도착하면`
  if (prediction.status === 'loading') {
    return { ...base, title: fallbackTitle, message: '확인하고 있어요…' }
  }
  if (prediction.status === 'error') {
    return { ...base, title: fallbackTitle, message: '예측을 불러오지 못했어요', error: true }
  }
  if (prediction.status === 'success') {
    const { value } = prediction
    if (value.status === 'AVAILABLE' && isCount(value.predictedBikes)) {
      const time = clockTime(value.arrivalTime)
      const probability = value.availabilityProbability
      return {
        ...base,
        title: time ? `${time} 도착하면` : fallbackTitle,
        subtitle:
          typeof probability === 'number'
            ? `예측 · 대여 가능성 ${Math.round(probability * 100)}%`
            : '예측',
        count: value.predictedBikes,
        mock: value.source === 'MOCK',
      }
    }
  }
  return { ...base, title: fallbackTitle, message: '이 시점 예측이 아직 없어요' }
}

function slotValue(slot: OutlookSlot, outlook: OutlookState) {
  const status = slot === 'now' ? outlook.stock.status : outlook.predictions[slot].status
  if (status === 'loading') return '…'
  const { count } = describeOutlookSlot(slot, outlook)
  return count === null ? '-' : `${count}대`
}

interface Props {
  station: Place
  outlook: OutlookState
  favorite: boolean
  onToggleFavorite: () => void
  onClose: () => void
  onSetOrigin: (place: Place) => void
  onSetDestination: (place: Place) => void
}

export default function BikeStationCard({
  station,
  outlook,
  favorite,
  onToggleFavorite,
  onClose,
  onSetOrigin,
  onSetDestination,
}: Props) {
  const [slot, setSlot] = useState<OutlookSlot>('now')
  const rentalId = bikeRentalId(station)
  const description = describeOutlookSlot(slot, outlook, station.dockCount)
  const { count, rack } = description
  const level = bikeStockBadgeLevel(count)
  const barRatio = count !== null && rack ? Math.min(1, count / rack) : null
  // distanceMeters는 nearby 조회 지도 중심 기준 거리다. 현재 위치까지의 거리가 아니다.
  const distance = station.distanceMeters
  return (
    <section className="bike-station-card" aria-label="선택한 따릉이 대여소" aria-live="polite">
      <header className="bike-station-card-header">
        <span className="bike-station-card-icon">
          <Bike size={22} />
        </span>
        <div className="bike-station-card-title">
          <small>{rentalId ? `따릉이 대여소 · ${rentalId}` : '따릉이 대여소'}</small>
          <h2>{station.name}</h2>
          {distance !== undefined && (
            <small>
              {Math.round(distance)}m · 도보{' '}
              {Math.max(1, Math.ceil(distance / WALK_METERS_PER_MINUTE))}분
            </small>
          )}
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
        <button
          type="button"
          className="icon-button"
          aria-label="대여소 정보 닫기"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </header>
      <div className="bike-station-outlook">
        <div className="bike-station-outlook-head">
          <strong>{description.title}</strong>
          {description.subtitle && <small>{description.subtitle}</small>}
          {description.mock && <span className="bike-station-mock-badge">샘플 예측</span>}
        </div>
        {count !== null ? (
          <div className="bike-station-outlook-count">
            <strong className={`level-${level}`}>{count}대</strong>
            {rack !== null && <span>/ 거치대 {rack}</span>}
          </div>
        ) : (
          <p className="bike-station-outlook-message" role={description.error ? 'alert' : 'status'}>
            {description.message}
          </p>
        )}
        {barRatio !== null && (
          <div className="bike-station-outlook-bar" aria-hidden="true">
            <span
              className={`level-${level}`}
              style={{ width: `${Math.round(barRatio * 100)}%` }}
            />
          </div>
        )}
        {description.note && <small>{description.note}</small>}
        {description.error && (
          <button type="button" className="secondary" onClick={outlook.retry}>
            다시 시도
          </button>
        )}
        <div className="bike-station-slots" role="group" aria-label="예측 시점">
          {slots.map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={slot === item}
              onClick={() => setSlot(item)}
            >
              <span>{slotLabels[item]}</span>
              <small>{slotValue(item, outlook)}</small>
            </button>
          ))}
        </div>
      </div>
      <div className="bike-station-actions">
        <button type="button" className="secondary" onClick={() => onSetOrigin(station)}>
          출발지로 설정
        </button>
        <button type="button" className="primary" onClick={() => onSetDestination(station)}>
          도착지로 설정
        </button>
      </div>
    </section>
  )
}
