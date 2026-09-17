import { expect, it } from 'vitest'
import { mapRouteApiResponse } from '../routeMapper'
import { emptyRouteSearchMockResponse } from './routeResponses'
import { mockPlaceRepository, mockRouteRepository, routeSearchMockRepository } from './repositories'
import { places } from './fixtures'

it('취소된 검색은 결과를 돌려주지 않는다', async () => {
  const request = new AbortController()
  const result = mockRouteRepository.search(
    { origin: places[0], destination: places[1] },
    request.signal,
  )
  request.abort()
  await expect(result).rejects.toMatchObject({ name: 'AbortError' })
})
it('장소 검색은 공백을 정리하고 등록된 후보만 반환한다', async () => {
  const result = await mockPlaceRepository.search(' 도곡역 ', new AbortController().signal)
  expect(result).toHaveLength(3)
  expect(result.every((place) => place.name.includes('도곡역'))).toBe(true)
})

it('최종 경로 API mock은 서버 순서와 DTO 필드를 화면 모델로 보존한다', async () => {
  const result = await routeSearchMockRepository.search(
    {
      origin: places[0],
      destination: places[1],
      modes: ['walk', 'bike', 'subway'],
      priority: 'fast',
      departedAt: '2026-09-15T08:30:00.000Z',
    },
    new AbortController().signal,
  )

  expect(result.map(({ routeType }) => routeType)).toEqual([
    'SHORTEST',
    'ALTERNATIVE',
    'ALTERNATIVE',
    'LOW_CONGESTION',
    'ALTERNATIVE',
    'ALTERNATIVE',
  ])
  expect(result[0]).toMatchObject({
    id: 'shortest-0',
    minutes: 5,
    transfers: 0,
    modes: ['subway'],
    departedAt: '2026-09-15T08:30:00.000Z',
  })
  expect(result[0].legs[0]).toMatchObject({
    mode: 'subway',
    routeId: '1002',
    minutes: 5,
    from: { id: '222', name: '강남', lat: 37.4979, lng: 127.0276 },
    to: { id: '221', name: '역삼', lat: 37.5006, lng: 127.0364 },
  })
  expect(result[0].legs[0].geometry).toBeUndefined()
  expect(result[3]).toMatchObject({ minutes: 8.5, transfers: 0, modes: ['walk', 'bike'] })
  expect(result[1].geometry?.coordinates).toEqual([
    [
      [127.0276, 37.4979],
      [127.0285, 37.4987],
    ],
  ])
  expect(result[2].transfers).toBe(1)
  expect(result[4]).toMatchObject({ minutes: 9.5, totalDistanceMeters: 1120 })
  expect(result[5]).toMatchObject({ minutes: 10.25 })
  expect(result[5].totalDistanceMeters).toBeUndefined()
  expect(result[5].legs[1].distanceMeters).toBeUndefined()
})

it('ApiResult의 빈 data는 빈 경로 목록으로 변환한다', () => {
  expect(mapRouteApiResponse(emptyRouteSearchMockResponse, '2026-09-15T08:30:00')).toEqual([])
})
