import { describe, expect, it } from 'vitest'
import { previewTrip } from './preview'
import { restoredTripFor } from './restoreTrip'
import { serializeRouteQuery } from './routeQuery'
import type { Place } from '../features/route/types'

const origin: Place = { id: 'o', name: '강남', address: '서울 강남구', kind: '역', stationId: 's1' }
const destination: Place = {
  id: 'd',
  name: '서울시청',
  address: '서울 중구',
  kind: '장소',
  lat: 37.56,
  lng: 126.97,
}

describe('restoredTripFor', () => {
  it('결과 해시의 출발·도착을 loading 상태로 복원한다', () => {
    const query = serializeRouteQuery({ origin, destination })
    const restored = restoredTripFor(`#results?${query}`, previewTrip)
    expect(restored?.trip).toMatchObject({ origin, destination, status: 'loading' })
    expect(restored?.departureAt).toBeUndefined()
  })

  it('상세 해시와 출발 시각도 복원한다', () => {
    const query = serializeRouteQuery({ origin, destination, departureAt: '2026-10-09T18:30' })
    const restored = restoredTripFor(`#detail?${query}`, previewTrip)
    expect(restored?.trip.status).toBe('loading')
    expect(restored?.departureAt).toBe('2026-10-09T18:30')
  })

  it('다른 화면이거나 쿼리가 없거나 잘못되면 null이다', () => {
    const query = serializeRouteQuery({ origin, destination })
    expect(restoredTripFor(`#home?${query}`, previewTrip)).toBeNull()
    expect(restoredTripFor('#results', previewTrip)).toBeNull()
    expect(restoredTripFor('#results?from=%7B&to=x', previewTrip)).toBeNull()
  })
})
