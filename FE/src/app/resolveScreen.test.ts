import { describe, expect, it } from 'vitest'
import { places, routes } from '../api/mock/fixtures'
import { initialGuidance, type GuidanceState } from '../features/guidance/guidanceReducer'
import type { TripState } from '../features/route/tripReducer'
import { previewTrip } from './preview'
import { resolveScreen } from './resolveScreen'

const loadedTrip: TripState = {
  ...previewTrip,
  destination: places[1],
  candidates: routes,
  selected: routes[0],
  status: 'success',
}

describe('브라우저 기록으로 요청한 화면 검증', () => {
  it('선택 경로가 사라져도 활성 안내 URL은 안내 스냅샷으로 유지한다', () => {
    const withoutSelection = { ...loadedTrip, selected: null }
    const oldGuidance: GuidanceState = {
      ...initialGuidance,
      route: routes[0],
      origin: places[0],
      destination: places[1],
    }
    expect(resolveScreen('detail', withoutSelection, oldGuidance)).toBe('results')
    expect(resolveScreen('guide', withoutSelection, oldGuidance)).toBe('guide')
  })
  it('탐색 중 선택과 다른 안내 경로도 독립된 세션으로 복구한다', () => {
    const activeGuidance: GuidanceState = {
      ...initialGuidance,
      route: routes[1],
      origin: places[0],
      destination: places[1],
      step: 1,
    }
    expect(resolveScreen('guide', loadedTrip, activeGuidance)).toBe('guide')
    expect(resolveScreen('arrival', loadedTrip, activeGuidance)).toBe('guide')
  })
  it('완료 여부에 따라 안내와 도착 기록을 현재 유효한 화면으로 맞춘다', () => {
    const guiding: GuidanceState = { ...initialGuidance, route: routes[0] }
    const completed: GuidanceState = { ...guiding, completed: true }
    expect(resolveScreen('arrival', loadedTrip, guiding)).toBe('guide')
    expect(resolveScreen('guide', loadedTrip, completed)).toBe('arrival')
  })
  it('검색 전 상태에서 과거 결과 URL로 이동하면 홈으로 돌아간다', () => {
    expect(resolveScreen('results', previewTrip, initialGuidance)).toBe('home')
  })
  it('안내를 명시적으로 끝낸 뒤 과거 안내 URL로 돌아오면 현재 선택 경로의 상세로 보낸다', () => {
    expect(resolveScreen('guide', loadedTrip, initialGuidance)).toBe('detail')
  })
})
