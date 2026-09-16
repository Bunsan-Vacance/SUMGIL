import { describe, expect, it } from 'vitest'
import { bikeProposal, places, routes } from '../../api/mock/fixtures'
import { previewTrip } from '../../app/preview'
import { tripReducer, type TripState } from './tripReducer'

const loadedTrip: TripState = {
  ...previewTrip,
  destination: places[1],
  candidates: routes,
  selected: routes[0],
  status: 'success',
}

describe('검색 조건과 경로 선택', () => {
  it('출발지나 도착지가 바뀌면 이전 검색 결과와 선택을 즉시 버린다', () => {
    const originChanged = tripReducer(loadedTrip, { type: 'origin', place: places[2] })
    expect(originChanged).toMatchObject({
      origin: places[2],
      candidates: [],
      selected: null,
      status: 'idle',
    })

    const searching = tripReducer(loadedTrip, { type: 'search', destination: places[3] })
    expect(searching).toMatchObject({
      destination: places[3],
      candidates: [],
      selected: null,
      status: 'loading',
    })
  })
  it('필터로 기존 선택이 제외되면 이용 가능한 경로를 선택한다', () => {
    const state = tripReducer(loadedTrip, { type: 'modes', modes: ['walk', 'bus'] })
    expect(state.selected?.id).toBe('bus')
    expect(tripReducer(state, { type: 'select', id: 'fast' })).toBe(state)
  })
  it('필터에 맞는 경로가 없으면 이전 선택을 남기지 않는다', () => {
    const state = tripReducer(loadedTrip, { type: 'modes', modes: ['bike'] })
    expect(state.selected).toBeNull()
    expect(state.candidates).toBe(routes)
  })
  it('필터와 맞지 않는 경로를 새 검색 결과에서 자동 선택하지 않는다', () => {
    const state = tripReducer(loadedTrip, { type: 'modes', modes: ['walk', 'bus'] })
    expect(tripReducer(state, { type: 'loaded', routes }).selected?.id).toBe('bus')
  })
  it('빈 이동수단 설정은 거절하고 정렬 변경은 사용자의 선택을 유지한다', () => {
    expect(tripReducer(loadedTrip, { type: 'modes', modes: [] })).toBe(loadedTrip)
    expect(tripReducer(loadedTrip, { type: 'priority', priority: 'calm' }).selected?.id).toBe(
      'fast',
    )
  })
  it('안내 중 제안 경로를 선택할 수 있고 검색 실패 시 이전 후보를 숨긴다', () => {
    expect(tripReducer(loadedTrip, { type: 'proposal', route: bikeProposal }).selected?.id).toBe(
      'bike-proposal',
    )
    const failed = tripReducer(loadedTrip, { type: 'failed' })
    expect(failed).toMatchObject({ candidates: [], selected: null, status: 'error' })
  })
})
