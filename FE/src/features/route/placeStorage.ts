import type { Place } from './types'

function getStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function isValidCoordinate(value: unknown, min: number, max: number) {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
}

export function isStoredPlace(value: unknown): value is Place {
  if (!isRecord(value)) return false
  if (
    typeof value.id !== 'string' ||
    !value.id.trim() ||
    typeof value.name !== 'string' ||
    !value.name.trim() ||
    typeof value.address !== 'string' ||
    !value.address.trim() ||
    typeof value.kind !== 'string' ||
    !value.kind.trim()
  )
    return false
  if ((value.lat === undefined) !== (value.lng === undefined)) return false
  if (value.lat !== undefined && !isValidCoordinate(value.lat, -90, 90)) return false
  if (value.lng !== undefined && !isValidCoordinate(value.lng, -180, 180)) return false
  if (
    value.stationId !== undefined &&
    (typeof value.stationId !== 'string' || !value.stationId.trim())
  )
    return false
  if (value.placeUrl !== undefined) {
    if (typeof value.placeUrl !== 'string' || !value.placeUrl.trim()) return false
    try {
      const protocol = new URL(value.placeUrl).protocol
      if (protocol !== 'http:' && protocol !== 'https:') return false
    } catch {
      return false
    }
  }
  return true
}

/** localStorage의 JSON 값을 읽는다. 저장소 사용 불가·파싱 실패·값 없음이면 빈 배열을 돌려준다. */
export function readStoredList(key: string): unknown {
  const storage = getStorage()
  if (!storage) return []
  try {
    const raw = storage.getItem(key)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

/** localStorage에 JSON으로 저장한다. 저장 실패는 삼킨다. */
export function writeStoredList(key: string, value: unknown): void {
  try {
    getStorage()?.setItem(key, JSON.stringify(value))
  } catch {
    // 저장소를 사용할 수 없어도 검색 화면은 계속 동작한다.
  }
}
