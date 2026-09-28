import { describe, expect, it } from 'vitest'
import { places, routes } from '../api/mock/fixtures'
import { emptyOrigin, previewTrip, previewTripFor } from './preview'

describe('개발용 미리보기 초기 경로', () => {
  it('일반 초기 상태는 출발지를 임의로 지정하지 않는다', () => {
    expect(previewTrip.origin).toBe(emptyOrigin)
    expect(previewTrip.origin.name).toBe('')
    expect(previewTrip.origin).not.toHaveProperty('lat')
    expect(previewTrip.origin).not.toHaveProperty('lng')
  })

  it('혼잡도 미리보기에서 첫 샘플 경로를 선택한다', () => {
    const preview = previewTripFor('?preview=congestion', true)
    expect(preview).toMatchObject({
      origin: places[0],
      destination: places[1],
      status: 'success',
    })
    expect(preview.candidates).toHaveLength(routes.length)
    expect(preview.candidates).toEqual(
      expect.arrayContaining(routes.map((route) => expect.objectContaining({ id: route.id }))),
    )
    expect(
      preview.candidates.every((route) => route.departedAt === preview.candidates[0].departedAt),
    ).toBe(true)
    expect(preview.selected).toBe(preview.candidates[0])
  })

  it('개발 모드가 아니면 일반 초기 상태를 유지한다', () => {
    expect(previewTripFor('?preview=congestion', false)).toBe(previewTrip)
    expect(previewTripFor('?preview=bike', false)).toBe(previewTrip)
    expect(previewTripFor('?preview=short', false)).toBe(previewTrip)
  })
  it('따릉이 미리보기는 실제 계약 fixture의 대여소 ID를 유지한다', () => {
    const preview = previewTripFor('?preview=bike', true)
    expect(preview.selected?.legs.find((leg) => leg.mode === 'bike')?.from?.rentalId).toBe('ST-1')
  })
  it('짧은 경로 미리보기는 API 계약의 지하철 단일 구간을 표시한다', () => {
    const preview = previewTripFor('?preview=short', true)
    expect(preview.selected?.legs).toHaveLength(1)
    expect(preview.selected?.legs[0].mode).toBe('subway')
    expect(preview.origin.name).toBe(preview.selected?.legs[0].from?.name)
  })
})
