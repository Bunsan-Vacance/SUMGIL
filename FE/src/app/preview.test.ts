import { describe, expect, it } from 'vitest'
import { places, routes } from '../api/mock/fixtures'
import { previewTrip, previewTripFor } from './preview'

describe('개발용 미리보기 초기 경로', () => {
  it('혼잡도 미리보기에서 첫 샘플 경로를 선택한다', () => {
    expect(previewTripFor('?preview=congestion', true)).toMatchObject({
      origin: places[0],
      destination: places[1],
      candidates: routes,
      selected: routes[0],
      status: 'success',
    })
  })

  it('개발 모드가 아니면 일반 초기 상태를 유지한다', () => {
    expect(previewTripFor('?preview=congestion', false)).toBe(previewTrip)
  })
})
